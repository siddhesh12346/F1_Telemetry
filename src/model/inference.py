"""Real-Time Causal Inference Engine for Surface-Departure Warning.

Loads the packaged Experiment C XGBoost model, maintains per-driver circular history buffers,
computes causal rolling features without lookahead, and outputs calibrated departure probabilities.
"""
from __future__ import annotations

from collections import deque
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from src.data.causal_features import (
    FEATURE_NAMES_EXP_C,
    compute_causal_features_single,
    verify_feature_integrity,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_DIR = ROOT / "models" / "surface_departure_xgboost"


class SurfaceWarningPredictor:
    """Predicts surface departure probability strictly from causal historical telemetry."""

    def __init__(self, model_dir: Path | str = DEFAULT_MODEL_DIR, threshold: float = 0.50):
        self.model_dir = Path(model_dir)
        self.threshold = float(threshold)

        # Load artifacts
        model_path = self.model_dir / "model.joblib"
        prep_path = self.model_dir / "preprocessor.joblib"
        feat_path = self.model_dir / "feature_list.json"
        meta_path = self.model_dir / "model_metadata.json"

        if not model_path.exists():
            raise FileNotFoundError(f"Model artifact missing: {model_path}")
        if not prep_path.exists():
            raise FileNotFoundError(f"Preprocessor artifact missing: {prep_path}")
        if not feat_path.exists():
            raise FileNotFoundError(f"Feature list missing: {feat_path}")

        self.model = joblib.load(model_path)
        self.preprocessor = joblib.load(prep_path)

        with open(feat_path, "r", encoding="utf-8") as f:
            self.features = json.load(f)

        self.metadata = {}
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                self.metadata = json.load(f)

        # Enforce feature integrity & exact ordering
        verify_feature_integrity(self.features)
        assert self.features == FEATURE_NAMES_EXP_C, "Feature order does not match Exp C contract!"

        # Per-driver FIFO ring buffers (max 25 samples is enough for 19-sample ~1s window)
        self._driver_history: dict[int, deque[dict[str, Any]]] = {}

    def reset_history(self, pilot_index: int | None = None) -> None:
        """Reset historical buffer for a given pilot or all pilots."""
        if pilot_index is not None:
            self._driver_history.pop(int(pilot_index), None)
        else:
            self._driver_history.clear()

    def predict_frame(self, frame_data: dict[str, Any]) -> dict[str, Any]:
        """Process a single incoming telemetry packet at time t.

        Parameters:
            frame_data: dict containing current raw telemetry fields:
                sessionTime, frameIdentifier, pilot_index, speed, throttle, brake,
                steer, gear, engineRPM, drs, gForceLateral, gForceLongitudinal,
                gForceVertical, sector.
                (Note: surfaceType, lapDistance, world coordinates must NEVER be used for prediction).

        Returns:
            dict containing departure_probability, is_warning, warning_state, and top dynamics.
        """
        pilot = int(frame_data.get("pilot_index", 0))
        if pilot not in self._driver_history:
            self._driver_history[pilot] = deque(maxlen=25)

        history = self._driver_history[pilot]

        # Extract only the safe raw telemetry fields
        safe_sample = {
            "sessionTime": float(frame_data["sessionTime"]),
            "frameIdentifier": int(frame_data["frameIdentifier"]),
            "pilot_index": pilot,
            "speed": float(frame_data["speed"]),
            "throttle": float(frame_data["throttle"]),
            "brake": float(frame_data["brake"]),
            "steer": float(frame_data["steer"]),
            "gear": float(frame_data.get("gear", 0)),
            "engineRPM": float(frame_data.get("engineRPM", 0)),
            "drs": float(frame_data.get("drs", 0)),
            "gForceLateral": float(frame_data["gForceLateral"]),
            "gForceLongitudinal": float(frame_data["gForceLongitudinal"]),
            "gForceVertical": float(frame_data.get("gForceVertical", 0)),
            "sector": float(frame_data.get("sector", 1)),
        }

        # Append to causal history
        history.append(safe_sample)

        # Compute the exact 30 Exp C features from history
        feature_dict = compute_causal_features_single(list(history))

        # Build feature dataframe in exact order
        feature_df = pd.DataFrame([[feature_dict[f] for f in self.features]], columns=self.features)

        # Preprocess & Predict probability
        vector_imp = self.preprocessor.transform(feature_df)
        proba = float(self.model.predict_proba(vector_imp)[0, 1])

        # Warning state classification
        is_warning = bool(proba >= self.threshold)
        if proba >= 0.50:
            warning_state = "WARNING"
        elif proba >= 0.30:
            warning_state = "CAUTION"
        else:
            warning_state = "SAFE"

        # Diagnostic contributing factors
        top_factors = {
            "gForceLateral_abs": abs(safe_sample["gForceLateral"]),
            "speed_roll_mean_1s": feature_dict["speed_roll_mean_1s"],
            "steer_roll_std_1s": feature_dict["steer_roll_std_1s"],
            "throttle_change_0_5s": feature_dict["throttle_change_0_5s"],
        }

        return {
            "frameIdentifier": safe_sample["frameIdentifier"],
            "sessionTime": safe_sample["sessionTime"],
            "pilot_index": pilot,
            "departure_probability": round(proba, 4),
            "is_warning": is_warning,
            "warning_state": warning_state,
            "threshold": self.threshold,
            "features": feature_dict,
            "top_factors": top_factors,
        }
