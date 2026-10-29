import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from run_store import append_event, lock_run, prepare_run_root


class RunStoreTests(unittest.TestCase):
    def test_owned_run_identity_resume_lock_and_event(self):
        with tempfile.TemporaryDirectory() as directory:
            user = Path(directory).resolve() / "zhangzibo"
            user.mkdir()
            base = user / "arxiv-tssa" / "results"
            plan = SimpleNamespace(run_id="tcl-test", manifest_sha="a" * 64)
            path = base / plan.run_id
            manifest = {"server": "school103", "output_root": str(path)}
            with patch("run_store.SCHOOL_RESULTS", {"school103": base}), \
                    patch("run_store.pwd.getpwuid", return_value=SimpleNamespace(pw_name="zhangzibo")), \
                    patch("run_store._check_data_disk"):
                self.assertEqual(prepare_run_root(path, plan, manifest), path)
                self.assertEqual(prepare_run_root(path, plan, manifest), path)
                with self.assertRaisesRegex(ValueError, "exact run identity"):
                    prepare_run_root(path, SimpleNamespace(run_id="tcl-test", manifest_sha="b" * 64), manifest)
                fd = lock_run(path)
                with self.assertRaises(BlockingIOError):
                    lock_run(path)
                os.close(fd)
                event = append_event(path, plan, "localize", "error", {"reason": "fixture"})
                data = Path(event["path"]).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), event["sha256"])
                self.assertEqual(json.loads(data)["status"], "error")

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            real = root / "real"
            real.mkdir()
            alias = root / "alias"
            alias.symlink_to(real, target_is_directory=True)
            base = alias / "zhangzibo" / "arxiv-tssa" / "results"
            plan = SimpleNamespace(run_id="run", manifest_sha="a" * 64)
            with patch("run_store.SCHOOL_RESULTS", {"school103": base}), \
                    patch("run_store.pwd.getpwuid", return_value=SimpleNamespace(pw_name="zhangzibo")):
                with self.assertRaisesRegex(ValueError, "symbolic link"):
                    prepare_run_root(base / "run", plan, {"server": "school103", "output_root": str(base / "run")})


if __name__ == "__main__":
    unittest.main()
