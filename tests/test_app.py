"""Tests for FastAPI backend REST and WebSocket endpoints."""
from __future__ import annotations

import sys
from pathlib import Path
import unittest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app


class TestAppEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_status_endpoint(self):
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "online")
        self.assertEqual(data["model_type"], "XGBClassifier")
        self.assertEqual(data["feature_count"], 30)
        self.assertEqual(data["threshold"], 0.50)
        self.assertNotIn("lapDistance", data["features"])
        self.assertNotIn("surfaceType", data["features"])

    def test_research_benchmark_endpoint(self):
        resp = self.client.get("/api/research/benchmark")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["benchmark_circuit"], "Spa")
        self.assertIn("clarification_note", data)
        self.assertAlmostEqual(data["frozen_metrics"]["roc_auc"], 0.73095, places=3)
        self.assertAlmostEqual(data["frozen_metrics"]["pr_auc"], 0.24385, places=3)
        self.assertAlmostEqual(data["frozen_metrics"]["event_recall"], 0.3116, places=3)

    def test_sessions_and_drivers(self):
        resp = self.client.get("/api/sessions")
        self.assertEqual(resp.status_code, 200)
        sessions = resp.json()
        self.assertGreater(len(sessions), 0)

        # Check Spa session
        spa_id = "4048657932346004126"
        d_resp = self.client.get(f"/api/sessions/{spa_id}/drivers")
        self.assertEqual(d_resp.status_code, 200)
        drivers = d_resp.json()
        self.assertGreater(len(drivers), 0)

    def test_trackmap_endpoint(self):
        spa_id = "4048657932346004126"
        resp = self.client.get(f"/api/sessions/{spa_id}/trackmap")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("points", data)
        self.assertGreater(len(data["points"]), 0)
        self.assertIn("bounds", data)

    def test_replay_state_and_control(self):
        resp = self.client.get("/api/replay/state")
        self.assertEqual(resp.status_code, 200)
        state = resp.json()
        self.assertIn("session_id", state)
        self.assertIn("total_frames", state)

        # Pause control
        c_resp = self.client.post("/api/replay/control", json={"action": "pause"})
        self.assertEqual(c_resp.status_code, 200)
        self.assertFalse(c_resp.json()["is_playing"])

        # Seek control
        s_resp = self.client.post("/api/replay/control", json={"action": "seek", "frame_index": 5})
        self.assertEqual(s_resp.status_code, 200)
        self.assertEqual(s_resp.json()["current_frame"], 5)

    def test_static_index_html(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("SURFACE DEPARTURE EARLY WARNING SYSTEM", resp.text)

    def test_websocket_telemetry_flow(self):
        with self.client.websocket_connect("/ws/telemetry") as websocket:
            # 1. First message should be initial state
            initial = websocket.receive_json()
            self.assertEqual(initial["type"], "state")

            # 2. Send play command
            websocket.send_json({"command": "play"})

            # 3. Receive next state confirmation or telemetry frame
            msg = websocket.receive_json()
            if msg["type"] == "state":
                self.assertTrue(msg["data"]["is_playing"])
                msg = websocket.receive_json()

            self.assertEqual(msg["type"], "telemetry")
            telemetry_data = msg["data"]
            self.assertIn("telemetry", telemetry_data)
            self.assertIn("prediction", telemetry_data)
            self.assertIn("evaluation", telemetry_data)
            self.assertIn("position", telemetry_data)

            # Check ML prediction
            pred = telemetry_data["prediction"]
            self.assertIn("departure_probability", pred)
            self.assertIn("warning_state", pred)
            self.assertIn("is_warning", pred)
            self.assertTrue(0.0 <= pred["departure_probability"] <= 1.0)

            # Pause playback before disconnecting
            websocket.send_json({"command": "pause"})
            for _ in range(5):
                p_msg = websocket.receive_json()
                if p_msg.get("type") == "state" and not p_msg.get("data", {}).get("is_playing", True):
                    break


if __name__ == "__main__":
    unittest.main()
