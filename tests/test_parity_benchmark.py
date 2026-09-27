"""Automated Parity Verification Test for Frozen Experiment C XGBoost Model.

Validates that the existing models/surface_departure_xgboost/model.joblib reproduces
the exact frozen Spa test benchmark metrics within strict tolerances.
"""
from __future__ import annotations

import sys
from pathlib import Path
import unittest
import joblib
import pandas as pd
from sklearn.metrics import roc_auc_score, average_precision_score, precision_score, recall_score, f1_score

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.causal_features import FEATURE_NAMES_EXP_C, verify_feature_integrity
from src.model.export_model import evaluate_event_level, load_session_samples, SESSIONS, TEST_CIRCUIT, FROZEN_BENCHMARK


class TestModelParityBenchmark(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model_dir = ROOT / "models" / "surface_departure_xgboost"
        cls.model_path = cls.model_dir / "model.joblib"
        cls.prep_path = cls.model_dir / "preprocessor.joblib"

        assert cls.model_path.exists(), f"Model file missing: {cls.model_path}"
        assert cls.prep_path.exists(), f"Preprocessor file missing: {cls.prep_path}"

        cls.model = joblib.load(cls.model_path)
        cls.preprocessor = joblib.load(cls.prep_path)

        # Load Spa test data
        cls.test_df = load_session_samples(TEST_CIRCUIT, SESSIONS[TEST_CIRCUIT])
        X_test = cls.test_df[FEATURE_NAMES_EXP_C]
        cls.y_test = cls.test_df["target_departure_next_1s"]

        X_test_imp = cls.preprocessor.transform(X_test)
        cls.probas = cls.model.predict_proba(X_test_imp)[:, 1]
        cls.preds = (cls.probas >= 0.50).astype(int)

    def test_feature_integrity(self):
        """Verify strict feature list contract on the existing model."""
        self.assertEqual(len(FEATURE_NAMES_EXP_C), 30)
        self.assertTrue(verify_feature_integrity(FEATURE_NAMES_EXP_C))
        self.assertEqual(self.model.n_features_in_, 30)

    def test_reproduce_frozen_spa_metrics(self):
        """Verify exact/tight parity against frozen Spa benchmarks."""
        roc_auc = float(roc_auc_score(self.y_test, self.probas))
        pr_auc = float(average_precision_score(self.y_test, self.probas))
        prec = float(precision_score(self.y_test, self.preds, zero_division=0))
        rec = float(recall_score(self.y_test, self.preds, zero_division=0))
        f1 = float(f1_score(self.y_test, self.preds, zero_division=0))
        ev_res = evaluate_event_level(self.test_df, self.probas, threshold=0.50)

        # Numerical checks
        self.assertAlmostEqual(roc_auc, FROZEN_BENCHMARK["roc_auc"], places=3)
        self.assertAlmostEqual(pr_auc, FROZEN_BENCHMARK["pr_auc"], places=3)
        self.assertAlmostEqual(prec, FROZEN_BENCHMARK["precision"], places=3)
        self.assertAlmostEqual(rec, FROZEN_BENCHMARK["recall"], places=3)
        self.assertAlmostEqual(ev_res["event_recall"], FROZEN_BENCHMARK["event_recall"], places=3)
        self.assertEqual(ev_res["events_detected"], FROZEN_BENCHMARK["events_detected"])


if __name__ == "__main__":
    unittest.main()
