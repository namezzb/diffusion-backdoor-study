import tempfile
import unittest
import json
from pathlib import Path

from PIL import Image
from pilot24_inputs import RUN, SEED
from pilot24_worker_ledger import WorkerLedger


def assignment(tokens=1):
    return {"run_id": RUN, "stage": "S0", "worker_id": "worker-a", "manifest_sha256": "a" * 64,
            "gate_sha256": "b" * 64, "retry_tokens": tokens, "units": [
                {"key": [RUN, "source", "clean", "dog", "home-04", SEED], "input_sha": "c" * 64, "mask_sha": "d" * 64},
                {"key": [RUN, "source", "backdoor", "dog", "home-04", SEED], "input_sha": "e" * 64, "mask_sha": "d" * 64}]}


class WorkerLedgerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.plan = assignment()
        self.key1, self.key2 = [x["key"] for x in self.plan["units"]]
        self.ledger = WorkerLedger(self.root, self.plan)

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def test_lock_assignment_and_persistent_attempts(self):
        self.assertEqual(self.ledger.start(self.key1), 1)
        with self.assertRaises((OSError, BlockingIOError)):
            WorkerLedger(self.root, self.plan)
        self.ledger.close()
        self.ledger = WorkerLedger(self.root, self.plan)
        with self.assertRaises(ValueError):
            self.ledger.start(self.key1)
        self.assertEqual(self.ledger.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 1)

    def test_retry_is_bounded_and_requires_empty_path(self):
        self.ledger.start(self.key1)
        path = self.ledger.image_path(self.key1)
        path.parent.mkdir()
        Image.new("RGB", (512, 512)).save(path)
        with self.assertRaises(ValueError):
            self.ledger.resolve_interrupted(self.key1, "f" * 64)
        path.unlink()
        with self.assertRaises(ValueError):
            self.ledger.recover_interrupted(self.key1)
        self.ledger.fail_attempt(self.key1, "synchronous compute failed")
        self.assertEqual(self.ledger.start(self.key1), 2)
        self.ledger.fail_attempt(self.key1, "synchronous retry failed")
        with self.assertRaises(ValueError):
            self.ledger.start(self.key1)
        self.ledger.start(self.key2)
        self.ledger.fail_attempt(self.key2, "second key failed, shared retry pool exhausted")
        with self.assertRaises(ValueError):
            self.ledger.start(self.key2)
        self.assertEqual(self.ledger.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 3)

    def test_reacquired_lock_recovers_published_png_without_regeneration(self):
        self.ledger.start(self.key1)
        image = self.ledger.image_path(self.key1)
        image.parent.mkdir()
        Image.new("RGB", (512, 512)).save(image)
        self.ledger.close()
        self.ledger = WorkerLedger(self.root, self.plan)
        self.assertEqual(self.ledger.recover_interrupted(self.key1), "scoring")
        self.ledger.begin_score(self.key1)
        self.ledger.finish_score(self.key1, image, {"vit_class": 151, "clip_score": 23.5})
        snapshot = self.ledger.snapshot("a" * 64, "b" * 64, verify_images=True)
        self.assertEqual(len(snapshot["records"]), 1)
        self.assertEqual(len(snapshot["attempts"]), 1)
        self.assertEqual(snapshot["attempts"][0]["resource"]["scoring_calls"], 1)

    def test_reacquired_lock_proves_local_interruption_and_retains_charge(self):
        self.ledger.start(self.key1)
        self.ledger.close()
        self.ledger = WorkerLedger(self.root, self.plan)
        self.assertEqual(self.ledger.recover_interrupted(self.key1), "retry_ready")
        self.assertEqual(self.ledger.start(self.key1), 2)
        evidence = json.loads(self.ledger.db.execute("SELECT detail FROM events").fetchone()[0])
        self.assertEqual(evidence["kind"], "exclusive_local_worker_lock_reacquired")
        with self.assertRaises(ValueError):
            self.ledger.recover_interrupted(self.key1)

    def test_corrupt_published_image_cannot_be_silently_retried(self):
        self.ledger.start(self.key1)
        image = self.ledger.image_path(self.key1)
        image.parent.mkdir()
        image.write_bytes(b"not png")
        self.ledger.close()
        self.ledger = WorkerLedger(self.root, self.plan)
        with self.assertRaises(Exception):
            self.ledger.recover_interrupted(self.key1)
        self.assertEqual(self.ledger.status(self.key1), "started")
        self.assertEqual(self.ledger.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 1)

    def test_altered_complete_image_detected_on_export(self):
        self.ledger.start(self.key1)
        image = self.ledger.image_path(self.key1)
        image.parent.mkdir()
        Image.new("RGB", (512, 512)).save(image)
        self.ledger.register_image(self.key1, image)
        self.ledger.finish_score(self.key1, image, {"vit_class": 151, "clip_score": 23.5})
        image.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.ledger.snapshot("a" * 64, "b" * 64, verify_images=True)

    def test_valid_png_is_scored_without_regeneration(self):
        self.ledger.start(self.key1)
        self.ledger.checkpoint(self.key1, {"te": 2, "unet": 50})
        with self.assertRaises(ValueError):
            self.ledger.checkpoint(self.key1, {"te": 1, "unet": 50})
        image = self.ledger.image_path(self.key1)
        image.parent.mkdir()
        Image.new("RGB", (512, 512)).save(image)
        sha = self.ledger.register_image(self.key1, image)
        with self.assertRaises(ValueError):
            self.ledger.start(self.key1)
        self.ledger.close()
        self.ledger = WorkerLedger(self.root, self.plan)
        self.ledger.finish_score(self.key1, image, {"vit_class": 151, "clip_score": 23.5})
        row = self.ledger.db.execute("SELECT status,image_sha FROM units WHERE key=?", (__import__("json").dumps(self.key1, separators=(",", ":")),)).fetchone()
        self.assertEqual(row, ("complete", sha))
        self.assertEqual(self.ledger.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 1)

    def test_unauthorized_key_and_assignment_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.start([RUN, "source", "clean", "dog", "home-11", SEED])
        self.ledger.close()
        with self.assertRaises(ValueError):
            WorkerLedger(self.root, assignment(tokens=2))
        self.ledger = WorkerLedger(self.root, self.plan)


if __name__ == "__main__":
    unittest.main()
