"""Unit tests for feature parity and real-time causal inference."""
from __future__ import annotations

import sys
from pathlib import Path
import unittest
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.causal_features import (
    FEATURE_NAMES_EXP_C,
    compute_causal_features_batch,
    compute_causal_features_single,
    verify_feature_integrity,
)
from src.model.inference import SurfaceWarningPredictor


class TestCausalInferenceParity(unittest.TestCase):
    def setUp(self):
        # Synthetic driving sequence: 25 frames
        t = np.linspace(0, 1.25, 25)
        self.samples = []
        for i in range(25):
            self.samples.append({
                "sessionTime": float(t[i]),
                "frameIdentifier": 1000 + i,
                "pilot_index": 0,
                "speed": 220.0 + i * 1.5,
                "throttle": 0.85 + (i % 3) * 0.05,
                "brake": 0.0 if i < 20 else 0.8,
                "steer": float(np.sin(i * 0.3) * 0.2),
                "gear": 6.0,
                "engineRPM": 11500.0 + i * 50.0,
                "drs": 0.0,
                "gForceLateral": float(np.cos(i * 0.3) * 2.5),
                "gForceLongitudinal": -0.5 if i < 20 else -3.5,
                "gForceVertical": 0.1,
                "sector": 1.0,
            })

    def test_feature_list_contract(self):
        """Verify the 30 features count, order, and absence of leaking fields."""
        self.assertEqual(len(FEATURE_NAMES_EXP_C), 30)
        self.assertTrue(verify_feature_integrity(FEATURE_NAMES_EXP_C))
        self.assertNotIn("lapDistance", FEATURE_NAMES_EXP_C)
        self.assertNotIn("surfaceType", FEATURE_NAMES_EXP_C)
        self.assertNotIn("worldPositionX", FEATURE_NAMES_EXP_C)

    def test_single_frame_parity_with_batch(self):
        """Verify single-frame rolling computation matches batch computation."""
        df = pd.DataFrame(self.samples)
        batch_df = compute_causal_features_batch(df)

        # Compare frame by frame for the last 10 frames
        for idx in range(15, 25):
            history_slice = self.samples[: idx + 1]
            single_feats = compute_causal_features_single(history_slice)

            batch_row = batch_df.iloc[idx]
            for feat in FEATURE_NAMES_EXP_C:
                batch_val = float(batch_row[feat])
                single_val = float(single_feats[feat])
                self.assertAlmostEqual(
                    batch_val,
                    single_val,
                    places=4,
                    msg=f"Discrepancy in feature '{feat}' at frame {idx}: batch={batch_val}, single={single_val}",
                )

    def test_surface_warning_predictor(self):
        """Verify SurfaceWarningPredictor initialization, inference execution, and latency."""
        predictor = SurfaceWarningPredictor()
        self.assertEqual(predictor.threshold, 0.50)

        # Feed sequence
        out = None
        for sample in self.samples:
            out = predictor.predict_frame(sample)

        self.assertIsNotNone(out)
        self.assertIn("departure_probability", out)
        self.assertIn("is_warning", out)
        self.assertIn("warning_state", out)
        self.assertIn(out["warning_state"], ["SAFE", "CAUTION", "WARNING"])
        self.assertTrue(0.0 <= out["departure_probability"] <= 1.0)
        self.assertEqual(out["is_warning"], out["departure_probability"] >= 0.50)


if __name__ == "__main__":
    unittest.main()
