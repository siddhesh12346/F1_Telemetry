"""Sequential Telemetry Replay Engine.

Streams telemetry frames sequentially, feeding each packet to the SurfaceWarningPredictor
without lookahead, while cleanly separating ML inputs from evaluation and visualization fields.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Generator
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.model.inference import SurfaceWarningPredictor

REPLAY_COLS = [
    "sessionTime",
    "frameIdentifier",
    "pilot_index",
    "speed",
    "throttle",
    "brake",
    "steer",
    "gear",
    "engineRPM",
    "drs",
    "gForceLateral",
    "gForceLongitudinal",
    "gForceVertical",
    "sector",
    "lapDistance",
    "currentLapNum",
    "surfaceType",
    "worldPositionX",
    "worldPositionZ",
]


class TelemetryReplaySession:
    """Loads and streams sequential telemetry for a selected session, driver, and lap."""

    def __init__(
        self,
        session_id: str,
        pilot_index: int = 0,
        lap_number: int | None = None,
        predictor: SurfaceWarningPredictor | None = None,
    ):
        self.session_id = str(session_id)
        self.pilot_index = int(pilot_index)
        self.lap_number = int(lap_number) if lap_number is not None else None
        self.predictor = predictor or SurfaceWarningPredictor()

        # Cache loaded frames
        self._frames: list[dict[str, Any]] = []
        self._current_index = 0
        self._load_telemetry()

    def _load_telemetry(self) -> None:
        """Load telemetry rows for the specific driver and lap."""
        csv_path = ROOT / f"TelemetryData_{self.session_id}.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"Telemetry file not found: {csv_path}")

        chunks = []
        with pd.read_csv(csv_path, usecols=REPLAY_COLS, chunksize=150_000) as reader:
            for chunk in reader:
                sub = chunk[chunk["pilot_index"].eq(self.pilot_index)]
                if self.lap_number is not None:
                    sub = sub[sub["currentLapNum"].eq(self.lap_number)]
                if not sub.empty:
                    chunks.append(sub)

                # Cap max in-memory replay rows to ~6,000 frames (approx 5 minutes of driving per session)
                # to keep UI fast and memory tiny
                if sum(len(c) for c in chunks) >= 6000:
                    break

        if chunks:
            df = pd.concat(chunks, ignore_index=True).sort_values("frameIdentifier").reset_index(drop=True)
            self._frames = df.to_dict(orient="records")
        else:
            self._frames = []

        self._current_index = 0
        self.predictor.reset_history(self.pilot_index)

    @property
    def total_frames(self) -> int:
        return len(self._frames)

    @property
    def current_frame_index(self) -> int:
        return self._current_index

    def seek(self, frame_index: int) -> None:
        """Seek to a specific index in the replay stream and rebuild predictor history."""
        target_idx = max(0, min(frame_index, self.total_frames - 1))
        self._current_index = target_idx
        self.predictor.reset_history(self.pilot_index)

        # Re-warm history buffer up to target_idx (last 20 frames)
        warm_start = max(0, target_idx - 20)
        for i in range(warm_start, target_idx):
            self.predictor.predict_frame(self._frames[i])

    def next_frame(self) -> dict[str, Any] | None:
        """Yield the next sequential frame with live prediction, evaluation, and position separated."""
        if self._current_index >= self.total_frames:
            return None

        raw_row = self._frames[self._current_index]
        self._current_index += 1

        # 1. RUN PREDICTION: strictly using causal raw telemetry
        pred_out = self.predictor.predict_frame(raw_row)

        # 2. EVALUATION DATA: Ground truth surface codes (for comparison display only)
        surface = str(raw_row.get("surfaceType", "0/0/0/0"))
        is_off_track = "7" in surface

        # 3. VISUALIZATION POSITION: For 2D map ONLY (completely excluded from ML)
        pos_x = float(raw_row.get("worldPositionX", 0.0))
        pos_z = float(raw_row.get("worldPositionZ", 0.0))

        # Pack clean modular payload
        return {
            "index": self._current_index - 1,
            "total_frames": self.total_frames,
            "telemetry": {
                "sessionTime": round(float(raw_row["sessionTime"]), 3),
                "frameIdentifier": int(raw_row["frameIdentifier"]),
                "speed": round(float(raw_row["speed"]), 1),
                "throttle": round(float(raw_row["throttle"]), 3),
                "brake": round(float(raw_row["brake"]), 3),
                "steer": round(float(raw_row["steer"]), 3),
                "gear": int(raw_row["gear"]),
                "engineRPM": int(raw_row["engineRPM"]),
                "drs": int(raw_row.get("drs", 0)),
                "gForceLateral": round(float(raw_row["gForceLateral"]), 2),
                "gForceLongitudinal": round(float(raw_row["gForceLongitudinal"]), 2),
                "gForceVertical": round(float(raw_row.get("gForceVertical", 0.0)), 2),
                "sector": int(raw_row.get("sector", 1)),
                "currentLapNum": int(raw_row.get("currentLapNum", 1)),
            },
            "prediction": {
                "departure_probability": pred_out["departure_probability"],
                "is_warning": pred_out["is_warning"],
                "warning_state": pred_out["warning_state"],
                "threshold": pred_out["threshold"],
                "top_factors": pred_out["top_factors"],
            },
            "features": pred_out.get("features", {}),
            "evaluation": {
                "surfaceType": surface,
                "is_off_track": is_off_track,
            },
            "position": {
                "x": pos_x,
                "z": pos_z,
            },
        }

    def frame_stream(self) -> Generator[dict[str, Any], None, None]:
        """Generator yielding all remaining frames sequentially."""
        while True:
            frame = self.next_frame()
            if frame is None:
                break
            yield frame
