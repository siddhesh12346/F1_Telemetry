"""Session Logging & Driver Analysis Module.

Records live telemetry and model predictions sequentially during replay,
detects CAUTION (>= 0.30) and WARNING (>= 0.50) events,
analyzes preceding conditions strictly using causal historical frames,
and produces persistent session logs and neutral incident analyses.
"""
from __future__ import annotations

from collections import deque
import csv
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("session_logger")

ROOT = Path(__file__).resolve().parents[2]
LOGS_DIR = ROOT / "logs"


class SessionLogger:
    """Manages active session logging, event detection, and causal analysis."""

    def __init__(self, logs_dir: Path | str = LOGS_DIR):
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        self.is_logging: bool = False
        self.log_id: Optional[str] = None
        self.session_info: dict[str, Any] = {}
        self.start_wall_time: Optional[float] = None
        self.start_session_time: Optional[float] = None
        self.last_session_time: Optional[float] = None

        self.recorded_frames: list[dict[str, Any]] = []
        self.detected_events: list[dict[str, Any]] = []

        # Circular buffer of recent frames (up to 40 frames, ~2.0s) for causal pre-event analysis
        self._history_buffer: deque[dict[str, Any]] = deque(maxlen=40)

        # Event tracking state
        self._prev_prob: float = 0.0
        self._active_caution: Optional[dict[str, Any]] = None
        self._active_warning: Optional[dict[str, Any]] = None

        # Cumulative time spent in each state (seconds based on dt)
        self._time_safe: float = 0.0
        self._time_caution: float = 0.0
        self._time_warning: float = 0.0

    def start_logging(
        self,
        session_id: str,
        circuit: str = "Unknown",
        pilot_index: int = 0,
        lap_number: Optional[int] = None,
    ) -> str:
        """Start a new logging session and generate unique log_id."""
        if self.is_logging:
            self.stop_logging()

        self.session_info = {
            "session_id": str(session_id),
            "circuit": str(circuit),
            "pilot_index": int(pilot_index),
            "lap_number": int(lap_number) if lap_number is not None else None,
        }

        # Generate unique directory name: YYYYMMDD_HHMMSS_<circuit>_p<pilot>
        timestamp_str = time.strftime("%Y%m%d_%H%M%S")
        safe_circuit = "".join(c for c in circuit if c.isalnum() or c in ("-", "_")).lower()
        base_id = f"{timestamp_str}_{safe_circuit}_p{pilot_index}"

        # Collision avoidance
        candidate_id = base_id
        counter = 1
        while (self.logs_dir / candidate_id).exists():
            candidate_id = f"{base_id}_{counter}"
            counter += 1

        self.log_id = candidate_id
        self.is_logging = True
        self.start_wall_time = time.time()
        self.start_session_time = None
        self.last_session_time = None

        self.recorded_frames.clear()
        self.detected_events.clear()
        self._history_buffer.clear()

        self._prev_prob = 0.0
        self._active_caution = None
        self._active_warning = None

        self._time_safe = 0.0
        self._time_caution = 0.0
        self._time_warning = 0.0

        logger.info(f"Started session logging: log_id={self.log_id} ({circuit}, pilot {pilot_index})")
        return self.log_id

    def log_frame(self, frame_data: dict[str, Any]) -> None:
        """Record a single frame sequentially and evaluate event thresholds."""
        if not self.is_logging:
            return

        telemetry = frame_data.get("telemetry", {})
        prediction = frame_data.get("prediction", {})
        features = frame_data.get("features", {})
        position = frame_data.get("position", {})

        cur_time = float(telemetry.get("sessionTime", 0.0))
        if self.start_session_time is None:
            self.start_session_time = cur_time

        # Calculate time delta for state durations
        dt = 0.0524
        if self.last_session_time is not None:
            diff = cur_time - self.last_session_time
            if 0 < diff < 0.5:
                dt = diff
        self.last_session_time = cur_time

        prob = float(prediction.get("departure_probability", 0.0))
        state = str(prediction.get("warning_state", "SAFE"))

        # Accumulate state durations
        if prob >= 0.50:
            self._time_warning += dt
        elif prob >= 0.30:
            self._time_caution += dt
        else:
            self._time_safe += dt

        # Build clean recorded row
        recorded_row = {
            "frame_index": int(frame_data.get("index", len(self.recorded_frames))),
            "sessionTime": round(cur_time, 3),
            "frameIdentifier": int(telemetry.get("frameIdentifier", 0)),
            "session_id": self.session_info.get("session_id", ""),
            "circuit": self.session_info.get("circuit", ""),
            "pilot_index": self.session_info.get("pilot_index", 0),
            "lap": int(telemetry.get("currentLapNum", 1)),
            "speed": round(float(telemetry.get("speed", 0.0)), 1),
            "throttle": round(float(telemetry.get("throttle", 0.0)), 3),
            "brake": round(float(telemetry.get("brake", 0.0)), 3),
            "steer": round(float(telemetry.get("steer", 0.0)), 3),
            "gear": int(telemetry.get("gear", 0)),
            "engineRPM": int(telemetry.get("engineRPM", 0)),
            "drs": int(telemetry.get("drs", 0)),
            "gForceLateral": round(float(telemetry.get("gForceLateral", 0.0)), 2),
            "gForceLongitudinal": round(float(telemetry.get("gForceLongitudinal", 0.0)), 2),
            "gForceVertical": round(float(telemetry.get("gForceVertical", 0.0)), 2),
            "sector": int(telemetry.get("sector", 1)),
            "worldPositionX": round(float(position.get("x", 0.0)), 2),
            "worldPositionZ": round(float(position.get("z", 0.0)), 2),
            # Model Output
            "departure_probability": round(prob, 4),
            "prediction_state": state,
            "threshold": float(prediction.get("threshold", 0.50)),
            # Derived causal features from existing pipeline
            "acceleration_kmh_s": round(float(features.get("acceleration_kmh_s", 0.0)), 2),
            "throttle_rate_s": round(float(features.get("throttle_rate_s", 0.0)), 3),
            "brake_rate_s": round(float(features.get("brake_rate_s", 0.0)), 3),
            "steer_rate_s": round(float(features.get("steer_rate_s", 0.0)), 3),
            "speed_roll_mean_0_5s": round(float(features.get("speed_roll_mean_0_5s", 0.0)), 1),
            "speed_roll_mean_1s": round(float(features.get("speed_roll_mean_1s", 0.0)), 1),
            "speed_roll_std_1s": round(float(features.get("speed_roll_std_1s", 0.0)), 2),
            "throttle_roll_mean_0_5s": round(float(features.get("throttle_roll_mean_0_5s", 0.0)), 3),
            "throttle_roll_mean_1s": round(float(features.get("throttle_roll_mean_1s", 0.0)), 3),
            "throttle_roll_std_1s": round(float(features.get("throttle_roll_std_1s", 0.0)), 3),
            "brake_roll_mean_0_5s": round(float(features.get("brake_roll_mean_0_5s", 0.0)), 3),
            "brake_roll_mean_1s": round(float(features.get("brake_roll_mean_1s", 0.0)), 3),
            "steer_roll_mean_0_5s": round(float(features.get("steer_roll_mean_0_5s", 0.0)), 3),
            "steer_roll_std_1s": round(float(features.get("steer_roll_std_1s", 0.0)), 3),
            "gforce_lat_max_1s": round(float(features.get("gforce_lat_max_1s", 0.0)), 2),
            "brake_max_1s": round(float(features.get("brake_max_1s", 0.0)), 3),
            "throttle_change_0_5s": round(float(features.get("throttle_change_0_5s", 0.0)), 3),
            "steer_change_0_5s": round(float(features.get("steer_change_0_5s", 0.0)), 3),
            "accel_change_0_5s": round(float(features.get("accel_change_0_5s", 0.0)), 2),
        }

        self.recorded_frames.append(recorded_row)

        # -------------------------------------------------------------
        # Event Detection (Transitions: < 0.30 -> >= 0.30, < 0.50 -> >= 0.50)
        # -------------------------------------------------------------
        # 1. CAUTION Event detection
        if self._prev_prob < 0.30 and prob >= 0.30:
            # Start Caution Event
            self._active_caution = self._create_event_record("CAUTION", recorded_row)
        elif self._active_caution is not None:
            # Update peak and duration
            if prob > self._active_caution["max_probability"]:
                self._active_caution["max_probability"] = round(prob, 4)
            self._active_caution["duration"] = round(cur_time - self._active_caution["start_time"], 3)
            self._active_caution["end_time"] = round(cur_time, 3)

            # Check for end of Caution event
            if prob < 0.30:
                self.detected_events.append(self._active_caution)
                self._active_caution = None

        # 2. WARNING Event detection
        if self._prev_prob < 0.50 and prob >= 0.50:
            # Start Warning Event
            self._active_warning = self._create_event_record("WARNING", recorded_row)
        elif self._active_warning is not None:
            # Update peak and duration
            if prob > self._active_warning["max_probability"]:
                self._active_warning["max_probability"] = round(prob, 4)
            self._active_warning["duration"] = round(cur_time - self._active_warning["start_time"], 3)
            self._active_warning["end_time"] = round(cur_time, 3)

            # Check for end of Warning event
            if prob < 0.50:
                self.detected_events.append(self._active_warning)
                self._active_warning = None

        # Append to causal historical buffer
        self._history_buffer.append(recorded_row)
        self._prev_prob = prob

    def _create_event_record(self, event_type: str, cur_row: dict[str, Any]) -> dict[str, Any]:
        """Construct event record and compute preceding conditions strictly from history buffer."""
        event_time = cur_row["sessionTime"]

        # Look back ~0.5s in history buffer (historical frames only)
        ref_row = cur_row
        target_ref_time = event_time - 0.50
        for h in reversed(self._history_buffer):
            if h["sessionTime"] <= target_ref_time:
                ref_row = h
                break
        else:
            if len(self._history_buffer) > 0:
                ref_row = self._history_buffer[0]

        # Calculate preceding changes (t - t_ref)
        speed_before = ref_row["speed"]
        throttle_before = ref_row["throttle"]
        brake_before = ref_row["brake"]
        steer_before = ref_row["steer"]

        delta_speed = round(cur_row["speed"] - speed_before, 1)
        delta_throttle = round(cur_row["throttle"] - throttle_before, 3)
        delta_brake = round(cur_row["brake"] - brake_before, 3)
        delta_steer = round(cur_row["steer"] - steer_before, 3)

        # Historical behavior in window
        history_window = [h for h in self._history_buffer if h["sessionTime"] >= target_ref_time]
        braking_applied = any(h["brake"] > 0.05 for h in history_window)
        throttle_reduced = delta_throttle <= -0.05
        peak_lat_g = max([abs(h["gForceLateral"]) for h in history_window]) if history_window else abs(cur_row["gForceLateral"])

        # Preceding conditions object
        preceding = {
            "speed_0_5s_before": speed_before,
            "throttle_0_5s_before": throttle_before,
            "brake_0_5s_before": brake_before,
            "steer_0_5s_before": steer_before,
            "speed_change_0_5s": delta_speed,
            "throttle_change_0_5s": delta_throttle,
            "brake_change_0_5s": delta_brake,
            "steer_change_0_5s": delta_steer,
            "braking_applied_before": bool(braking_applied),
            "throttle_reduced_before": bool(throttle_reduced),
            "peak_lateral_g_0_5s": round(peak_lat_g, 2),
        }

        # Build neutral incident analysis narrative
        analysis_text = self._build_incident_analysis_narrative(event_type, cur_row, preceding)

        return {
            "event_id": f"{event_type.lower()}_{len(self.detected_events) + 1}",
            "event_type": event_type,
            "frame_index": cur_row["frame_index"],
            "start_time": event_time,
            "end_time": event_time,
            "duration": 0.052,
            "session_id": cur_row["session_id"],
            "circuit": cur_row["circuit"],
            "pilot_index": cur_row["pilot_index"],
            "lap": cur_row["lap"],
            "sector": cur_row["sector"],
            "start_probability": cur_row["departure_probability"],
            "max_probability": cur_row["departure_probability"],
            "telemetry_at_start": {
                "speed": cur_row["speed"],
                "throttle": cur_row["throttle"],
                "brake": cur_row["brake"],
                "steer": cur_row["steer"],
                "gear": cur_row["gear"],
                "engineRPM": cur_row["engineRPM"],
                "gForceLateral": cur_row["gForceLateral"],
                "gForceLongitudinal": cur_row["gForceLongitudinal"],
            },
            "preceding_conditions": preceding,
            "incident_analysis": analysis_text,
        }

    def _build_incident_analysis_narrative(
        self, event_type: str, cur: dict[str, Any], prec: dict[str, Any]
    ) -> str:
        """Formulate neutral, objective telemetry analysis narrative without subjective coaching."""
        obs = []

        # Speed and throttle observations
        if cur["throttle"] >= 0.85:
            obs.append("High throttle was maintained leading into the event")
        elif prec["throttle_change_0_5s"] <= -0.15:
            obs.append("Throttle lift detected prior to onset")

        # Steering & Lateral load
        if prec["peak_lateral_g_0_5s"] >= 1.5:
            obs.append(f"Elevated lateral load ({prec['peak_lateral_g_0_5s']}G peak) observed in preceding 0.5 s")
        if abs(prec["steer_change_0_5s"]) >= 0.10:
            obs.append("Rapid steering input adjustment observed")

        # Braking
        if not prec["braking_applied_before"] and cur["brake"] < 0.05:
            obs.append("No braking input detected prior to threshold crossing")
        elif prec["braking_applied_before"]:
            obs.append("Braking input was active preceding the event")

        obs_str = ". ".join(obs) + "." if obs else "Standard vehicle dynamics leading into event."

        # Potential areas for review (strictly neutral phrasing)
        areas = []
        if cur["speed"] > 180 and cur["throttle"] > 0.8:
            areas.append("Earlier throttle reduction or braking point could be investigated")
        if abs(prec["steer_change_0_5s"]) >= 0.15:
            areas.append("Smoother steering input rate could be investigated")

        area_str = " ".join(areas) if areas else "Review corner entry trajectory and lateral load build-up."

        return (
            f"{event_type} event observed at {cur['speed']} km/h (probability {cur['departure_probability']:.2f}). "
            f"Preceding behavior: {obs_str} Potential area for review: {area_str}"
        )

    def stop_logging(self) -> Optional[dict[str, Any]]:
        """Finalize logging session, compute driver analysis, and write files to disk."""
        if not self.is_logging or not self.log_id:
            return None

        # Finalize any ongoing events
        if self._active_caution is not None:
            self.detected_events.append(self._active_caution)
            self._active_caution = None
        if self._active_warning is not None:
            self.detected_events.append(self._active_warning)
            self._active_warning = None

        wall_duration = round(time.time() - (self.start_wall_time or time.time()), 2)
        total_frames = len(self.recorded_frames)

        cautions = [e for e in self.detected_events if e["event_type"] == "CAUTION"]
        warnings = [e for e in self.detected_events if e["event_type"] == "WARNING"]

        # Compute driver summary statistics (strictly from recorded events)
        avg_warn_speed = round(float(np.mean([w["telemetry_at_start"]["speed"] for w in warnings])), 1) if warnings else 0.0
        avg_warn_throttle = round(float(np.mean([w["telemetry_at_start"]["throttle"] for w in warnings])), 3) if warnings else 0.0
        avg_warn_brake = round(float(np.mean([w["telemetry_at_start"]["brake"] for w in warnings])), 3) if warnings else 0.0

        common_preceding = []
        if warnings:
            high_throttle_count = sum(1 for w in warnings if w["telemetry_at_start"]["throttle"] >= 0.80)
            no_brake_count = sum(1 for w in warnings if not w["preceding_conditions"]["braking_applied_before"])
            high_lat_g_count = sum(1 for w in warnings if w["preceding_conditions"]["peak_lateral_g_0_5s"] >= 1.2)
            steer_delta_count = sum(1 for w in warnings if abs(w["preceding_conditions"]["steer_change_0_5s"]) >= 0.08)

            if high_throttle_count >= len(warnings) / 2:
                common_preceding.append("High throttle (>= 80%) maintained before warning")
            if no_brake_count >= len(warnings) / 2:
                common_preceding.append("Limited or zero braking applied in the 0.5 s preceding warning")
            if high_lat_g_count >= len(warnings) / 2:
                common_preceding.append("Elevated lateral-G load (>= 1.2G) prior to onset")
            if steer_delta_count >= len(warnings) / 2:
                common_preceding.append("Rapid steering angle adjustments preceding onset")

        if not common_preceding and warnings:
            common_preceding.append("Varied dynamic factors across detected events")

        total_time_active = max(0.01, self._time_safe + self._time_caution + self._time_warning)

        session_meta = {
            "log_id": self.log_id,
            "session_id": self.session_info.get("session_id", ""),
            "circuit": self.session_info.get("circuit", ""),
            "pilot_index": self.session_info.get("pilot_index", 0),
            "lap_number": self.session_info.get("lap_number"),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_seconds": round(total_time_active, 2),
            "wall_duration_seconds": wall_duration,
            "total_frames": total_frames,
            "caution_events_count": len(cautions),
            "warning_events_count": len(warnings),
            "time_in_safe_seconds": round(self._time_safe, 2),
            "time_in_caution_seconds": round(self._time_caution, 2),
            "time_in_warning_seconds": round(self._time_warning, 2),
            "time_in_safe_pct": round((self._time_safe / total_time_active) * 100, 1),
            "time_in_caution_pct": round((self._time_caution / total_time_active) * 100, 1),
            "time_in_warning_pct": round((self._time_warning / total_time_active) * 100, 1),
            "driver_analysis": {
                "warnings_count": len(warnings),
                "cautions_count": len(cautions),
                "avg_warning_speed_kmh": avg_warn_speed,
                "avg_warning_throttle_pct": round(avg_warn_throttle * 100, 1),
                "avg_warning_brake_pct": round(avg_warn_brake * 100, 1),
                "common_preceding_conditions": common_preceding,
            },
        }

        # -------------------------------------------------------------
        # Write files to logs/<log_id>/
        # -------------------------------------------------------------
        target_dir = self.logs_dir / self.log_id
        target_dir.mkdir(parents=True, exist_ok=True)

        # 1. session.json
        with open(target_dir / "session.json", "w", encoding="utf-8") as f:
            json.dump(session_meta, f, indent=2)

        # 2. events.json
        with open(target_dir / "events.json", "w", encoding="utf-8") as f:
            json.dump(self.detected_events, f, indent=2)

        # 3. telemetry.csv
        if self.recorded_frames:
            df = pd.DataFrame(self.recorded_frames)
            df.to_csv(target_dir / "telemetry.csv", index=False)
        else:
            # Create empty CSV with headers
            cols = [
                "frame_index", "sessionTime", "frameIdentifier", "speed", "throttle", "brake",
                "steer", "gear", "engineRPM", "departure_probability", "prediction_state",
            ]
            pd.DataFrame(columns=cols).to_csv(target_dir / "telemetry.csv", index=False)

        logger.info(f"Finalized and saved session log: {target_dir} ({total_frames} frames, {len(warnings)} warnings)")

        saved_info = {
            "log_id": self.log_id,
            "directory": str(target_dir),
            "metadata": session_meta,
        }

        self.is_logging = False
        self.log_id = None
        return saved_info

    def get_status(self) -> dict[str, Any]:
        """Return current logging status and metrics."""
        duration = 0.0
        if self.is_logging and self.start_wall_time:
            duration = round(time.time() - self.start_wall_time, 1)

        cautions = sum(1 for e in self.detected_events if e["event_type"] == "CAUTION")
        if self._active_caution:
            cautions += 1
        warnings = sum(1 for e in self.detected_events if e["event_type"] == "WARNING")
        if self._active_warning:
            warnings += 1

        return {
            "is_logging": self.is_logging,
            "log_id": self.log_id,
            "session_id": self.session_info.get("session_id"),
            "circuit": self.session_info.get("circuit"),
            "pilot_index": self.session_info.get("pilot_index"),
            "frames_recorded": len(self.recorded_frames),
            "duration_seconds": duration,
            "cautions_count": cautions,
            "warnings_count": warnings,
        }


# Global singleton instance
session_logger = SessionLogger()


# -------------------------------------------------------------
# Disk Query & Inspection Utilities
# -------------------------------------------------------------
def list_saved_logs(logs_dir: Path | str = LOGS_DIR) -> list[dict[str, Any]]:
    """Scan logs directory and return summaries of all saved sessions sorted newest first."""
    p = Path(logs_dir)
    if not p.exists():
        return []

    logs = []
    for item in sorted(p.iterdir(), reverse=True):
        if item.is_dir() and (item / "session.json").exists():
            try:
                with open(item / "session.json", "r", encoding="utf-8") as f:
                    meta = json.load(f)
                logs.append(meta)
            except Exception as e:
                logger.warning(f"Failed to read session.json from {item}: {e}")
    return logs


def get_log_detail(log_id: str, logs_dir: Path | str = LOGS_DIR) -> Optional[dict[str, Any]]:
    """Load session metadata and detected events for a specific log_id."""
    target_dir = Path(logs_dir) / log_id
    if not target_dir.exists():
        return None

    meta_file = target_dir / "session.json"
    events_file = target_dir / "events.json"

    if not meta_file.exists():
        return None

    with open(meta_file, "r", encoding="utf-8") as f:
        meta = json.load(f)

    events = []
    if events_file.exists():
        with open(events_file, "r", encoding="utf-8") as f:
            events = json.load(f)

    return {
        "session": meta,
        "events": events,
    }


def get_log_event_timeline(
    log_id: str,
    event_index: int,
    pre_sec: float = 1.0,
    post_sec: float = 0.5,
    logs_dir: Path | str = LOGS_DIR,
) -> Optional[dict[str, Any]]:
    """Extract a window of frames (-pre_sec to +post_sec) around an event for visualization."""
    target_dir = Path(logs_dir) / log_id
    detail = get_log_detail(log_id, logs_dir)
    if not detail:
        return None

    events = detail.get("events", [])
    if event_index < 0 or event_index >= len(events):
        return None

    target_event = events[event_index]
    event_time = target_event["start_time"]

    csv_file = target_dir / "telemetry.csv"
    if not csv_file.exists():
        return None

    df = pd.read_csv(csv_file)
    t_min = event_time - pre_sec
    t_max = event_time + post_sec

    slice_df = df[(df["sessionTime"] >= t_min) & (df["sessionTime"] <= t_max)]

    cols = [
        "frame_index", "sessionTime", "speed", "throttle", "brake",
        "steer", "gear", "engineRPM", "departure_probability", "prediction_state",
    ]
    avail_cols = [c for c in cols if c in slice_df.columns]
    timeline_frames = slice_df[avail_cols].to_dict(orient="records")

    return {
        "event": target_event,
        "timeline": timeline_frames,
        "pre_sec": pre_sec,
        "post_sec": post_sec,
    }
