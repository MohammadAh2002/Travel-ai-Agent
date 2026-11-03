import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.core.models import SessionState
from app.services import memory


class SessionMemoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db_path = Path(self.directory.name) / "nested" / "sessions.sqlite3"
        patcher = patch.object(memory, "SESSION_DB_PATH", self.db_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_full_state_survives_a_new_python_process(self):
        state = SessionState(session_id="chat-123")
        state.profile.destination = "Istanbul"
        state.history = [{"role": "user", "content": "مرحبا"}]
        state.itinerary = {"days": [{"date": "2026-11-06"}]}
        state.pending_action = {"action_id": "act-1", "type": "save_trip"}
        state.completed_actions = {"act-0": {"result": {"trip_id": "trip-1"}}}
        memory.save_session(state)
        env = {**os.environ, "SESSION_DB_PATH": str(self.db_path), "PYTHONIOENCODING": "utf-8"}
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        result = subprocess.run(
            [sys.executable, "-c",
             "from app.services.memory import get_session; "
             "print(get_session('chat-123').model_dump_json())"],
            env=env, capture_output=True, text=True, encoding="utf-8", check=True,
        )
        self.assertEqual(SessionState.model_validate_json(result.stdout), state)

    def test_updates_and_session_isolation(self):
        first = memory.get_session("first")
        first.profile.destination = "Paris"
        memory.save_session(first)
        first.profile.destination = "Istanbul"
        memory.save_session(first)
        self.assertEqual(memory.get_session("first").profile.destination, "Istanbul")
        self.assertIsNone(memory.get_session("second").profile.destination)

    def test_expiry_and_read_refresh(self):
        with patch.object(memory, "SESSION_TTL_SECONDS", 100):
            with patch.object(memory.time, "time", return_value=1000):
                state = memory.get_session("active")
                state.profile.destination = "Paris"
                memory.save_session(state)
                memory.save_session(SessionState(session_id="inactive", history=[{"role": "user", "content": "old"}]))
            with patch.object(memory.time, "time", return_value=1090):
                memory.get_session("active")
            with patch.object(memory.time, "time", return_value=1150):
                self.assertEqual(memory.get_session("active").profile.destination, "Paris")
                self.assertEqual(memory.get_session("inactive").history, [])


if __name__ == "__main__":
    unittest.main()
