"""Unit test for the sequential replay engine."""
from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.replay import TelemetryReplaySession


class TestTelemetryReplay(unittest.TestCase):
    def test_replay_spa_session(self):
        """Verify TelemetryReplaySession loads Spa frames and runs prediction."""
        session_id = "4048657932346004126"  # Spa
        replay = TelemetryReplaySession(session_id=session_id, pilot_index=0)
        self.assertGreater(replay.total_frames, 0)

        # Stream 10 frames
        frames = []
        for _ in range(10):
            f = replay.next_frame()
            if f is not None:
                frames.append(f)

        self.assertEqual(len(frames), 10)
        first = frames[0]
        self.assertIn("telemetry", first)
        self.assertIn("prediction", first)
        self.assertIn("evaluation", first)
        self.assertIn("position", first)

        pred = first["prediction"]
        self.assertIn("departure_probability", pred)
        self.assertIn("is_warning", pred)
        self.assertIn("warning_state", pred)
        self.assertTrue(0.0 <= pred["departure_probability"] <= 1.0)


if __name__ == "__main__":
    unittest.main()
