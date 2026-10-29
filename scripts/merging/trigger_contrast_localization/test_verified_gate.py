import hashlib
import tempfile
import unittest
from pathlib import Path

from bindings import FrozenBindings
from evidence import CLASSES, Ledger
from generation import _image_path

SHA = "a" * 64


class VerifiedGateTests(unittest.TestCase):
    def test_2048_scored_records_and_images_derive_frozen_baseline_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ids = {"source": [f"s{i}" for i in range(128)], "merge": [f"m{i}" for i in range(128)]}
            labels_by_class = {"trigger": list(range(281, 288)), "dog": [151], "cat": [281], "other": [330, 332]}
            keys = [(state, context, category) for state in ids for context in ids[state] for category in CLASSES]
            binding = FrozenBindings("run", SHA, SHA, SHA, (1, 2), 99, (1, 2, 3),
                                     {key: SHA for key in keys}, {"clean": SHA, "backdoor": SHA}, {},
                                     {key: tuple(labels_by_class[key[2]]) for key in keys}, {}, {})
            ledger = Ledger(root / "ledger.sqlite", "run", SHA, ids, [1, 2], binding)
            data = b"fixture image bytes"
            image_sha = hashlib.sha256(data).hexdigest()
            for version in ("clean", "backdoor"):
                for context in ids["source"]:
                    for category in CLASSES:
                        for seed in (1, 2):
                            ledger.start("source", version, category, context, seed, SHA, SHA)
                            key = ("run", "source", version, category, context, seed)
                            path = _image_path(root / "images", key)
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_bytes(data)
                            prediction = 151 if version == "clean" and category == "trigger" else labels_by_class[category][0]
                            ledger.complete("source", version, category, context, seed, image_sha,
                                            {"vit_class": prediction, "clip_score": 20.}, {})
            result = ledger.evaluate_gate("source_baseline", root / "images")
            self.assertEqual(result["value"], "pass")
            self.assertEqual(result["result"]["delta"], 1.)
            self.assertTrue(ledger._passed("source_baseline"))
            path.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "altered scored image"):
                ledger.evaluate_gate("source_baseline", root / "images")
            ledger.close()


if __name__ == "__main__":
    unittest.main()
