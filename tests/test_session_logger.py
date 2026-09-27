"""Comprehensive Unit & Integration Tests for Session Logging & Driver Analysis."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app
from src.data.causal_features import FEATURE_NAMES_EXP_C
from src.data.session_logger import (
    SessionLogger,
    get_log_detail,
    get_log_event_timeline,
    list_saved_logs,
)
from src.model.inference import SurfaceWarningPredictor


class TestSessionLogger(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="f1_test_logs_")
        self.logger = SessionLogger(logs_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_dummy_frame(self, index: int, t: float, prob: float, speed: float = 220.0, throttle: float = 0.9, brake: float = 0.0):
        state = "SAFE"
        if prob >= 0.50:
            state = "WARNING"
        elif prob >= 0.30:
            state = "CAUTION"

        return {
            "index": index,
            "total_frames": 100,
            "telemetry": {
                "sessionTime": round(t, 3),
                "frameIdentifier": 1000 + index,
                "speed": speed,
                "throttle": throttle,
                "brake": brake,
                "steer": 0.05 * (index % 5),
                "gear": 6,
                "engineRPM": 11500,
                "drs": 0,
                "gForceLateral": 1.2 if prob > 0.4 else 0.5,
                "gForceLongitudinal": -0.2,
                "gForceVertical": 0.1,
                "sector": 1,
                "currentLapNum": 1,
            },
            "prediction": {
                "departure_probability": round(prob, 4),
                "is_warning": prob >= 0.50,
                "warning_state": state,
                "threshold": 0.50,
                "top_factors": {},
            },
            "features": {
                "acceleration_kmh_s": 0.0,
                "throttle_rate_s": 0.0,
                "brake_rate_s": 0.0,
                "steer_rate_s": 0.0,
                "speed_roll_mean_0_5s": speed,
                "speed_roll_mean_1s": speed,
                "speed_roll_std_1s": 1.0,
                "throttle_roll_mean_0_5s": throttle,
                "throttle_roll_mean_1s": throttle,
                "throttle_roll_std_1s": 0.05,
                "brake_roll_mean_0_5s": brake,
                "brake_roll_mean_1s": brake,
                "steer_roll_mean_0_5s": 0.0,
                "steer_roll_std_1s": 0.01,
                "gforce_lat_max_1s": 1.5,
                "brake_max_1s": brake,
                "throttle_change_0_5s": 0.0,
                "steer_change_0_5s": 0.0,
                "accel_change_0_5s": 0.0,
            },
            "position": {"x": 100.0, "z": 200.0},
        }

    def test_log_start_and_stop(self):
        """Verify logger starts, records frames, and serializes required files on stop."""
        log_id = self.logger.start_logging("4048657932346004126", "Spa", 0, 1)
        self.assertTrue(self.logger.is_logging)
        self.assertIsNotNone(log_id)

        # Log 5 frames
        for i in range(5):
            self.logger.log_frame(self._make_dummy_frame(i, i * 0.052, 0.10))

        self.assertEqual(len(self.logger.recorded_frames), 5)
        saved = self.logger.stop_logging()
        self.assertFalse(self.logger.is_logging)
        self.assertIsNotNone(saved)

        log_dir = Path(self.temp_dir) / log_id
        self.assertTrue((log_dir / "session.json").exists())
        self.assertTrue((log_dir / "telemetry.csv").exists())
        self.assertTrue((log_dir / "events.json").exists())

        # Verify session.json contents
        with open(log_dir / "session.json", "r") as f:
            meta = json.load(f)
        self.assertEqual(meta["total_frames"], 5)
        self.assertEqual(meta["circuit"], "Spa")
        self.assertEqual(meta["pilot_index"], 0)

    def test_frames_recorded_only_when_active(self):
        """Ensure frames are ignored when logging is inactive."""
        self.assertFalse(self.logger.is_logging)
        self.logger.log_frame(self._make_dummy_frame(0, 0.0, 0.10))
        self.assertEqual(len(self.logger.recorded_frames), 0)

    def test_model_prediction_unchanged(self):
        """Explicitly prove that logging cannot alter model inference predictions."""
        predictor = SurfaceWarningPredictor()
        samples = [
            {
                "sessionTime": float(i * 0.0524),
                "frameIdentifier": 2000 + i,
                "pilot_index": 0,
                "speed": 230.0 + i * 2.0,
                "throttle": 0.95,
                "brake": 0.0,
                "steer": float(np.sin(i * 0.2) * 0.1),
                "gear": 6.0,
                "engineRPM": 11800.0,
                "drs": 0.0,
                "gForceLateral": float(np.cos(i * 0.2) * 1.5),
                "gForceLongitudinal": 0.1,
                "gForceVertical": 0.0,
                "sector": 1.0,
            }
            for i in range(15)
        ]

        # 1. Predict without logger
        predictor.reset_history(0)
        probas_unlogged = [predictor.predict_frame(s)["departure_probability"] for s in samples]

        # 2. Predict with logger active
        predictor.reset_history(0)
        self.logger.start_logging("4048657932346004126", "Spa", 0)
        probas_logged = []
        for s in samples:
            out = predictor.predict_frame(s)
            probas_logged.append(out["departure_probability"])
            self.logger.log_frame({"telemetry": s, "prediction": out, "features": out.get("features", {})})
        self.logger.stop_logging()

        # Compare exact equality
        self.assertEqual(probas_unlogged, probas_logged)

    def test_caution_and_warning_detection(self):
        """Verify CAUTION (<0.30 -> >=0.30) and WARNING (<0.50 -> >=0.50) detection and event life cycles."""
        self.logger.start_logging("test_session", "Monza", 0)

        # Feed sequence:
        # Frame 0-9: prob 0.15 (SAFE)
        # Frame 10-14: prob 0.35 (CAUTION triggered at frame 10)
        # Frame 15-19: prob 0.65 (WARNING triggered at frame 15)
        # Frame 20-25: prob 0.20 (both events end)
        for i in range(10):
            self.logger.log_frame(self._make_dummy_frame(i, i * 0.052, 0.15))
        for i in range(10, 15):
            self.logger.log_frame(self._make_dummy_frame(i, i * 0.052, 0.35))
        for i in range(15, 20):
            self.logger.log_frame(self._make_dummy_frame(i, i * 0.052, 0.65))
        for i in range(20, 26):
            self.logger.log_frame(self._make_dummy_frame(i, i * 0.052, 0.20))

        self.logger.stop_logging()

        events = self.logger.detected_events
        caution_events = [e for e in events if e["event_type"] == "CAUTION"]
        warning_events = [e for e in events if e["event_type"] == "WARNING"]

        self.assertGreaterEqual(len(caution_events), 1)
        self.assertGreaterEqual(len(warning_events), 1)

        first_c = caution_events[0]
        self.assertEqual(first_c["frame_index"], 10)
        self.assertAlmostEqual(first_c["start_probability"], 0.35, places=2)

        first_w = warning_events[0]
        self.assertEqual(first_w["frame_index"], 15)
        self.assertAlmostEqual(first_w["start_probability"], 0.65, places=2)

    def test_event_preceding_conditions_causal(self):
        """Verify preceding condition deltas use historical frames only."""
        self.logger.start_logging("test_session", "Sakhir", 0)

        # 15 baseline frames (~0.75s) at speed 200 km/h, throttle 1.0, brake 0.0
        for i in range(15):
            self.logger.log_frame(self._make_dummy_frame(i, i * 0.052, 0.10, speed=200.0, throttle=1.0, brake=0.0))

        # Event trigger at frame 16: speed 220 km/h (+20), throttle 0.8 (-0.2), brake 0.5 (+0.5), prob 0.55
        self.logger.log_frame(self._make_dummy_frame(15, 15 * 0.052, 0.55, speed=220.0, throttle=0.8, brake=0.5))
        self.logger.stop_logging()

        warnings = [e for e in self.logger.detected_events if e["event_type"] == "WARNING"]
        self.assertEqual(len(warnings), 1)
        w = warnings[0]
        prec = w["preceding_conditions"]

        self.assertEqual(prec["speed_0_5s_before"], 200.0)
        self.assertEqual(prec["speed_change_0_5s"], 20.0)
        self.assertAlmostEqual(prec["throttle_change_0_5s"], -0.2, places=2)
        self.assertAlmostEqual(prec["brake_change_0_5s"], 0.5, places=2)

    def test_no_overwrite_multiple_logs(self):
        """Verify consecutive logs create distinct directories and do not overwrite each other."""
        id1 = self.logger.start_logging("session_a", "Mexico", 0)
        self.logger.log_frame(self._make_dummy_frame(0, 0.0, 0.1))
        self.logger.stop_logging()

        id2 = self.logger.start_logging("session_a", "Mexico", 0)
        self.logger.log_frame(self._make_dummy_frame(0, 0.0, 0.1))
        self.logger.stop_logging()

        self.assertNotEqual(id1, id2)
        self.assertTrue((Path(self.temp_dir) / id1).exists())
        self.assertTrue((Path(self.temp_dir) / id2).exists())

    def test_neutral_incident_analysis_language(self):
        """Confirm that incident analysis text is strictly factual and lacks subjective ratings/coaching."""
        self.logger.start_logging("test_session", "Spa", 0)
        for i in range(12):
            self.logger.log_frame(self._make_dummy_frame(i, i * 0.052, 0.10 if i < 10 else 0.70))
        self.logger.stop_logging()

        detail = get_log_detail(self.logger.detected_events[0]["session_id"] if self.logger.detected_events else "", self.temp_dir)
        # Check detected event narrative directly
        w = self.logger.detected_events[-1]
        text = w["incident_analysis"].lower()

        # Must not contain subjective coaching or grades
        for forbidden in ["bad driver", "poor driving", "score", "/10", "amateur", "fault"]:
            self.assertNotIn(forbidden, text)
        self.assertIn("event observed", text)


class TestAppLoggingIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_logger_rest_endpoints(self):
        """Test /api/log/start, /api/log/stop, /api/log/status, /api/logs."""
        # 1. Start logging
        res_start = self.client.post("/api/log/start")
        self.assertEqual(res_start.status_code, 200)
        data_start = res_start.json()
        self.assertEqual(data_start["status"], "started")
        log_id = data_start["log_id"]

        # 2. Check status
        res_status = self.client.get("/api/log/status")
        self.assertEqual(res_status.status_code, 200)
        self.assertTrue(res_status.json()["is_logging"])

        # 3. Stop logging
        res_stop = self.client.post("/api/log/stop")
        self.assertEqual(res_stop.status_code, 200)
        self.assertEqual(res_stop.json()["status"], "stopped")

        # 4. List logs
        res_logs = self.client.get("/api/logs")
        self.assertEqual(res_logs.status_code, 200)
        logs = res_logs.json()
        self.assertTrue(any(l["log_id"] == log_id for l in logs))

        # 5. Get detail
        res_detail = self.client.get(f"/api/logs/{log_id}")
        self.assertEqual(res_detail.status_code, 200)
        self.assertIn("session", res_detail.json())
        self.assertIn("events", res_detail.json())

        # 6. Export file
        res_export = self.client.get(f"/api/logs/{log_id}/export/csv")
        self.assertEqual(res_export.status_code, 200)
        self.assertEqual(res_export.headers["content-type"], "text/csv; charset=utf-8")

    def test_ws_logging_commands(self):
        """Test WebSocket client sending start_log and stop_log commands."""
        with self.client.websocket_connect("/ws/telemetry") as ws:
            # Receive initial state
            msg = ws.receive_json()
            self.assertEqual(msg["type"], "state")

            # Send start_log command
            ws.send_json({"command": "start_log"})
            state_msg = None
            for _ in range(10):
                m = ws.receive_json()
                if m.get("type") == "state" and m.get("logging") is True:
                    state_msg = m
                    break
            self.assertIsNotNone(state_msg)
            self.assertTrue(state_msg["logging"])

            # Send stop_log command
            ws.send_json({"command": "stop_log"})
            state_msg2 = None
            for _ in range(10):
                m = ws.receive_json()
                if m.get("type") == "state" and m.get("logging") is False:
                    state_msg2 = m
                    break
            self.assertIsNotNone(state_msg2)
            self.assertFalse(state_msg2["logging"])


if __name__ == "__main__":
    unittest.main()
