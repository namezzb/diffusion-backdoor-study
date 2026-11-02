from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest

from pilot24_watchdog import create_t0, load_t0, supervise


class WatchdogTests(unittest.TestCase):
    def test_t0_cannot_be_reset_or_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "t0.json"
            sha = create_t0(path, "a" * 64, now_utc="2026-11-02T00:00:00Z")
            self.assertEqual(load_t0(path, sha, "a" * 64)["t0_utc"], "2026-11-02T00:00:00Z")
            with self.assertRaises(FileExistsError):
                create_t0(path, "a" * 64, now_utc="2026-11-02T01:00:00Z")
            path.write_text("{}")
            with self.assertRaises(ValueError):
                load_t0(path, sha, "a" * 64)

    def test_owned_process_is_terminated_at_deadline(self):
        t0 = (datetime.now(timezone.utc) - timedelta(hours=22, minutes=14, seconds=59)).isoformat()
        outcome = supervise([sys.executable, "-c", "import time; time.sleep(30)"], t0, grace_seconds=.5)
        self.assertTrue(outcome["deadline_stop"])
        self.assertNotEqual(outcome["returncode"], 0)

    def test_normal_exit_is_not_a_deadline_failure(self):
        t0 = datetime.now(timezone.utc).isoformat()
        outcome = supervise([sys.executable, "-c", "pass"], t0)
        self.assertEqual(outcome['returncode'], 0)
        self.assertFalse(outcome['deadline_stop'])

    def test_explicit_stop_is_limited_to_the_owned_child(self):
        with tempfile.TemporaryDirectory() as directory:
            stop = Path(directory) / 'stop.json'
            stop.write_text('{}')
            outcome = supervise([sys.executable, '-c', 'import time; time.sleep(30)'],
                                datetime.now(timezone.utc).isoformat(), stop_file=stop, grace_seconds=.2)
            self.assertEqual(outcome['stop_reason'], 'coordinator_stop')
            self.assertNotEqual(outcome['returncode'], 0)


if __name__ == "__main__":
    unittest.main()
