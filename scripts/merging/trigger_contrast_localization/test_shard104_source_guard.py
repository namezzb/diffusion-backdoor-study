import hashlib
import datetime
import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import test_shard104_plan as plan_fixtures
SHA = plan_fixtures.SHA

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "research/tasks/2026-10-29-trigger-contrast-localization/shard104_source_guard.py"
spec = importlib.util.spec_from_file_location("shard104_source_guard_fixture", SOURCE)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def stat_line(pid, state, flags, start):
    fields = [state] + ["0"] * 19
    fields[6], fields[19] = str(flags), str(start)
    return f"{pid} (python with spaces) " + " ".join(fields)


class SourceGuardTests(unittest.TestCase):
    def setUp(self):
        self.fixture = plan_fixtures.ShardPlanTests()
        self.fixture.setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.proc = Path(self.temp.name) / "proc"
        self.proc.mkdir()
        self.process = self.proc / "586456"
        (self.process / "task/586456").mkdir(parents=True)
        (self.process / "task/588542").mkdir(parents=True)
        self.process.joinpath("stat").write_text(stat_line(586456, "Z", 4228108, 9222972))
        for pid, state, flags, start in ((586456, "Z", 4228108, 9222972), (588542, "R", 4195404, 9253469)):
            path = self.process / "task" / str(pid)
            path.joinpath("stat").write_text(stat_line(pid, state, flags, start))
            path.joinpath("status").write_text("Tgid:\t586456\nFDSize:\t0\n")
        self.lock = self.fixture.root / "run/.run.lock"
        self.lock.touch()
        st = self.lock.stat()
        self.proc.joinpath("locks").write_text(f"8: FLOCK ADVISORY WRITE 586456 {os.major(st.st_dev):02x}:{os.minor(st.st_dev):02x}:{st.st_ino} 0 EOF\n")
        self.machine = Path(self.temp.name) / "machine-id"
        self.machine.write_text("fixture-machine")
        self.machine_sha = hashlib.sha256(self.machine.read_bytes()).hexdigest()
        # This file is not part of the immutable snapshot fixture's manifest.
        self.lock.unlink()
        self.candidate = self.fixture.candidate()
        self.lock.touch()
        st = self.lock.stat()
        self.proc.joinpath("locks").write_text(f"8: FLOCK ADVISORY WRITE 586456 {os.major(st.st_dev):02x}:{os.minor(st.st_dev):02x}:{st.st_ino} 0 EOF\n")

    def tearDown(self):
        self.fixture.tearDown()
        self.temp.cleanup()

    def observe(self, now=None):
        return guard.observe(self.fixture.root / "run", self.proc, self.machine, self.machine_sha, 586456, 9222972,
            {586456: 9222972, 588542: 9253469}, self.candidate["source_attempts_logical_sha256"], "run", SHA, "b" * 64, now=now)

    def test_exiting_locked_unchanged_source_produces_bounded_observation(self):
        result = self.observe()
        self.assertEqual(result["status"], "source_quiescent_observation")
        self.assertEqual(len(result["threads"]), 2)
        self.assertTrue(all(row["flags"] & 4 for row in result["threads"]))

    def test_timestamp_is_conservatively_backdated_without_extending_expiry(self):
        receiver_now = datetime.datetime.now(datetime.timezone.utc)
        source_now = receiver_now + datetime.timedelta(milliseconds=80)
        result = self.observe(source_now)
        issued = datetime.datetime.fromisoformat(result['issued_at_utc'])
        expires = datetime.datetime.fromisoformat(result['expires_at_utc'])
        self.assertEqual(issued, source_now - datetime.timedelta(seconds=2))
        self.assertLessEqual(issued, receiver_now)
        self.assertEqual(expires - issued, datetime.timedelta(seconds=30))
        self.assertEqual(expires, source_now + datetime.timedelta(seconds=28))

    def test_lock_sequence_change_is_ignored_but_range_change_is_rejected(self):
        locks = self.proc / 'locks'
        original = Path.read_text
        calls = []
        def changing_sequence(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            if path == locks:
                calls.append(1)
                if len(calls) == 2:
                    return value.replace('8: ', '42: ', 1)
            return value
        with patch.object(Path, 'read_text', changing_sequence):
            self.assertTrue(self.observe()['lock_line'].startswith('42: '))
        locks.write_text(original(locks).replace(' 0 EOF', ' 1 EOF'))
        with self.assertRaisesRegex(ValueError, 'source lock'):
            self.observe()

    def test_nonexiting_thread_lock_change_or_new_attempt_fails(self):
        thread = self.process / "task/588542/stat"
        original = thread.read_text()
        thread.write_text(stat_line(588542, "R", 0, 9253469))
        with self.assertRaisesRegex(ValueError, "PF_EXITING"):
            self.observe()
        thread.write_text(original)
        lock_line = self.proc.joinpath("locks").read_text()
        self.proc.joinpath("locks").write_text(lock_line.replace("586456", "12345"))
        with self.assertRaisesRegex(ValueError, "source lock"):
            self.observe()
        self.proc.joinpath("locks").write_text(lock_line)
        with sqlite3.connect(self.fixture.root / "run/images.sqlite") as db:
            db.execute("UPDATE attempts SET resource=? WHERE status='started'", (json.dumps({"changed": 1}),))
        with self.assertRaisesRegex(ValueError, "attempts changed"):
            self.observe()


if __name__ == "__main__":
    unittest.main()
