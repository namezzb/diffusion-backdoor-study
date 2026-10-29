"""CPU checks of interrupted chunk receipt and exact-prefix recovery; no SSH."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("stage_chunks", Path(__file__).with_name("stage_school_assets.py"))
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)


class ChunkRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="school-chunk-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dest = self.root / "model.uploading"
        self.dest.write_bytes(b"abc")

    def receive(self, payload, *, offset=3, total=6, size=3, expected=None, dest=None):
        source = stage.REMOTE_CHUNK.replace(stage.REMOTE_ROOT, str(self.root))
        command = [sys.executable, "-c", source, str(dest or self.dest), str(offset),
                   str(total), str(size), expected or hashlib.sha256(b"def").hexdigest()]
        return subprocess.run(command, input=payload, capture_output=True)

    def test_truncated_chunk_retains_prefix_and_full_retry_commits(self):
        failed = self.receive(b"d")
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(self.dest.read_bytes(), b"abc")
        leftovers = list(self.root.glob("*.chunk-*"))
        self.assertEqual(len(leftovers), 1)
        succeeded = self.receive(b"def")
        self.assertEqual(succeeded.returncode, 0, succeeded.stderr)
        self.assertEqual(self.dest.read_bytes(), b"abcdef")
        self.assertEqual(json.loads(succeeded.stdout)["committed_size"], 6)
        self.assertTrue(leftovers[0].exists(), "An earlier unverified fragment is preserved")

    def test_wrong_chunk_hash_never_changes_model_prefix(self):
        result = self.receive(b"xyz")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.dest.read_bytes(), b"abc")

    def test_replayed_offset_and_symlink_are_rejected(self):
        for args in ({"offset": 0}, {"size": 4}):
            with self.subTest(args=args):
                self.assertNotEqual(self.receive(b"def", **args).returncode, 0)
                self.assertEqual(self.dest.read_bytes(), b"abc")
        link = self.root / "linked.uploading"
        link.symlink_to(self.dest)
        self.assertNotEqual(self.receive(b"def", dest=link).returncode, 0)
        self.assertEqual(self.dest.read_bytes(), b"abc")

    def test_client_stops_on_failure_then_restarts_from_verified_actual_prefix(self):
        local = self.root / "source"
        local.write_bytes(b"abcdefgh")
        remote_bytes = bytearray()
        session = stage.SchoolSession(ssh_chunk_bytes=3)
        calls = []

        def check(*_):
            return json.dumps({"size": len(remote_bytes), "sha256": hashlib.sha256(remote_bytes).hexdigest()})

        def upload(remote, offset, total, payload):
            calls.append((offset, payload))
            self.assertEqual(offset, len(remote_bytes))
            if len(calls) == 2:
                remote_bytes.extend(payload[:1])  # interruption after part of the verified append
                raise RuntimeError("simulated lost SSH acknowledgement")
            remote_bytes.extend(payload)
            return {"offset": offset, "chunk_size": len(payload), "committed_size": len(remote_bytes),
                    "sha256": hashlib.sha256(payload).hexdigest()}

        with mock.patch.object(session, "remote", side_effect=check), \
                mock.patch.object(session, "_upload_chunk", side_effect=upload):
            with self.assertRaisesRegex(RuntimeError, "lost SSH"):
                session.upload(local, stage.REMOTE_ROOT + "/model.uploading")
            self.assertEqual(len(calls), 2, "No automatic retry after failure")
            session.upload(local, stage.REMOTE_ROOT + "/model.uploading")
        self.assertEqual(bytes(remote_bytes), b"abcdefgh")
        self.assertEqual([x[0] for x in calls], [0, 3, 4, 7])


if __name__ == "__main__":
    unittest.main(verbosity=2)
