import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from evidence import Ledger
from generation import _image_path, run_image
from localization_ledger import LocalizationLedger
from recovery import recover_interrupted
from run_store import lock_run
import test_generation as generation_fixtures

Runtime, SHA, Scorer = generation_fixtures.Runtime, generation_fixtures.SHA, generation_fixtures.Scorer


def recover(root, plan, kind, reason):
    fd = lock_run(root)
    try:
        return recover_interrupted(root, plan, kind, reason, fd)
    finally:
        os.close(fd)


class RecoveryTests(unittest.TestCase):
    def test_te_repeated_interruptions_reopen_and_budget(self):
        contexts = [f"c{i}" for i in range(64)]
        plan = SimpleNamespace(run_id="run", manifest_sha=SHA)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = LocalizationLedger(root / "localization.sqlite", "run", SHA, contexts, ["b"])
            ledger.begin("baseline:clean")
            ledger.reserve("baseline:clean", "trigger", "c0")
            ledger.close()
            with patch("recovery.LIMIT", 1):
                with self.assertRaisesRegex(ValueError, "budget insufficient"):
                    recover(root, plan, "localization", "disconnected process exited")
            self.assertEqual(recover(root, plan, "localization", "disconnected process exited")["archived_attempts"], 1)
            ledger = LocalizationLedger(root / "localization.sqlite", "run", SHA, contexts, ["b"])
            self.assertEqual(ledger.attempt_count(), 2)
            self.assertEqual(ledger.resume("baseline:clean"), {})
            self.assertTrue(ledger.reserve("baseline:clean", "trigger", "c0"))
            ledger.close()
            self.assertEqual(recover(root, plan, "localization", "second process interruption")["archived_attempts"], 1)
            ledger = LocalizationLedger(root / "localization.sqlite", "run", SHA, contexts, ["b"])
            self.assertEqual(ledger.attempt_count(), 3)
            self.assertTrue(ledger.reserve("baseline:clean", "trigger", "c0"))
            ledger.record("baseline:clean", "trigger", "c0", b"result")
            self.assertFalse(ledger.reserve("baseline:clean", "trigger", "c0"))
            self.assertEqual(ledger.load("baseline:clean", "trigger", "c0"), b"result")
            self.assertEqual(ledger.db.execute("SELECT COUNT(*) FROM forward_history").fetchone()[0], 2)
            ledger.close()
            self.assertEqual(recover(root, plan, "localization", "recheck completed attempts")["archived_attempts"], 0)

    def test_image_interruption_counts_each_attempt_and_blocks_unregistered_file(self):
        ids = {"source": [f"s{i}" for i in range(128)], "merge": [f"m{i}" for i in range(128)]}
        plan = SimpleNamespace(run_id="run", manifest_sha=SHA)
        binding = generation_fixtures.GenerationTests().binding()
        frozen = {"input_ids": [1] * 77, "attention_mask": [1] * 77}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = Ledger(root / "images.sqlite", "run", SHA, ids, [1, 2], binding)
            runtime = Runtime(fail_at=3)
            args = lambda r, l: (r, Scorer(), l, root / "images", "source", "clean", "dog", "s0", 1, SHA, SHA, "dog", "dog", frozen)
            with self.assertRaisesRegex(RuntimeError, "interruption"):
                run_image(*args(runtime, ledger))
            old = _image_path(root / "images", ("run", "source", "clean", "dog", "s0", 1))
            old.parent.mkdir(exist_ok=True)
            old.write_bytes(b"possible interrupted png")
            ledger.close()
            with self.assertRaisesRegex(ValueError, "unregistered"):
                recover(root, plan, "images", "disconnected process exited")
            old.unlink()
            with patch("recovery.MAX_IMAGES_PER_STATE", 1):
                with self.assertRaisesRegex(ValueError, "budget insufficient"):
                    recover(root, plan, "images", "disconnected process exited")
            recover(root, plan, "images", "disconnected process exited")
            ledger = Ledger(root / "images.sqlite", "run", SHA, ids, [1, 2], binding)
            self.assertEqual(ledger.attempt_count("source"), 2)
            self.assertIsNone(ledger.db.execute("SELECT image_observed_sha FROM attempt_history").fetchone()[0])
            with self.assertRaisesRegex(RuntimeError, "interruption"):
                run_image(*args(Runtime(fail_at=2), ledger))
            ledger.close()
            recover(root, plan, "images", "second process interruption")
            ledger = Ledger(root / "images.sqlite", "run", SHA, ids, [1, 2], binding)
            result = run_image(*args(Runtime(), ledger))
            self.assertEqual(ledger.attempt_count("source"), 3)
            self.assertNotEqual(Path(result["image_path"]), old)
            self.assertFalse(old.exists())
            self.assertTrue(run_image(*args(Runtime(), ledger))["reused"])
            self.assertEqual(ledger.db.execute("SELECT COUNT(*) FROM attempt_history").fetchone()[0], 2)
            ledger.close()

    def test_interrupted_scoring_reuses_registered_png_without_new_attempt(self):
        ids = {"source": [f"s{i}" for i in range(128)], "merge": [f"m{i}" for i in range(128)]}
        plan = SimpleNamespace(run_id="run", manifest_sha=SHA)
        binding = generation_fixtures.GenerationTests().binding()
        frozen = {"input_ids": [1] * 77, "attention_mask": [1] * 77}
        class FailedScorer:
            def score(self, image, prompt):
                raise RuntimeError("scoring interrupted")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = Ledger(root / "images.sqlite", "run", SHA, ids, [1, 2], binding)
            runtime = Runtime()
            args = lambda r, scorer, l: (r, scorer, l, root / "images", "source", "clean", "dog", "s0", 1, SHA, SHA, "dog", "dog", frozen)
            with self.assertRaisesRegex(RuntimeError, "scoring interrupted"):
                run_image(*args(runtime, FailedScorer(), ledger))
            image = _image_path(root / "images", ("run", "source", "clean", "dog", "s0", 1))
            original = image.read_bytes()
            self.assertEqual(runtime.calls, 50)
            self.assertEqual(ledger.db.execute("SELECT image_sha FROM attempts").fetchone()[0], hashlib.sha256(original).hexdigest())
            ledger.close()
            image.write_bytes(b"corrupted")
            with self.assertRaisesRegex(ValueError, "hash differs"):
                recover(root, plan, "images", "scoring process interrupted")
            image.write_bytes(original)
            with patch("recovery.MAX_IMAGES_PER_STATE", 1):
                result = recover(root, plan, "images", "scoring process interrupted")
            self.assertEqual(result["resume_scoring"], 1)
            self.assertEqual(result["archived_attempts"], 0)
            ledger = Ledger(root / "images.sqlite", "run", SHA, ids, [1, 2], binding)
            resumed_runtime = Runtime()
            scored = run_image(*args(resumed_runtime, Scorer(), ledger))
            self.assertEqual(resumed_runtime.calls, 0)
            self.assertEqual(scored["image_path"], str(image))
            self.assertEqual(image.read_bytes(), original)
            self.assertEqual(ledger.attempt_count("source"), 1)
            self.assertEqual(ledger.db.execute("SELECT action FROM attempt_dispositions").fetchone()[0], "resume_scoring")
            self.assertTrue(run_image(*args(Runtime(), Scorer(), ledger))["reused"])
            ledger.close()

    def test_run_lock_blocks_concurrent_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            first = lock_run(directory)
            try:
                with self.assertRaises(BlockingIOError):
                    lock_run(directory)
            finally:
                os.close(first)
            second = lock_run(directory)
            os.close(second)


if __name__ == "__main__":
    unittest.main()
