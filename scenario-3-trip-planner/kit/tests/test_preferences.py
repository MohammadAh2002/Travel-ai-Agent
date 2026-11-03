import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from services import preference_store as store


class PreferenceStoreTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "preferences.sqlite3"
        env = patch.dict(os.environ, {"PREFERENCES_DB_PATH": str(self.path)})
        env.start()
        self.addCleanup(env.stop)
        self.seed = [{"traveller_id": "TRV-101", "name": "Sara", "preferences": {"dietary": ["vegetarian"]}}]
        store.initialize(self.seed)

    def test_preferences_survive_new_process_and_startup_seeding(self):
        store.save("TRV-101", {"dietary": ["vegan"]}, "now")
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        result = subprocess.run([sys.executable, "-c",
            "from services.travel_api import get_preferences; "
            "assert get_preferences('TRV-101')['preferences']['dietary'] == ['vegan']"],
            env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_merge_case_insensitive_identity_and_isolation(self):
        store.save("TRV-new", {"dietary": ["vegetarian"]}, "first")
        store.save("trv-NEW", {"interests": ["museums"]}, "second")
        saved = store.get("TRV-new")
        self.assertEqual(saved["preferences"], {"dietary": ["vegetarian"], "interests": ["museums"]})
        self.assertEqual(saved["updated_at"], "second")
        self.assertIsNone(store.get("TRV-other"))
        self.assertEqual(len(store.list_travellers()), 2)

    def test_explicit_reset_restores_seed(self):
        store.save("TRV-new", {"interests": ["museums"]}, "now")
        store.save("TRV-101", {"dietary": ["vegan"]}, "now")
        store.initialize(self.seed, reset=True)
        self.assertIsNone(store.get("TRV-new"))
        self.assertEqual(store.get("TRV-101")["preferences"]["dietary"], ["vegetarian"])
