import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

from core import partition
from localization_ledger import LocalizationLedger
from localization_runner import run_localization
from preflight import FrozenPlan
from report import persist_localization_stop
from selection import ScientificStop
from selection_audit import block_id
from test_localization_runner import Runtime, SHA


class StopRuntime(Runtime):
    def __init__(self, mode):
        super().__init__()
        self.mode = mode
        if mode == "random_control_insufficient":
            state = torch.zeros(40)
            state[0] = 1
            self.assets.text_states["backdoor"]["layer.weight"] = state

    def _embeddings(self, texts, scalars, alpha):
        self.calls += 1
        w = self.text_encoder.layer.weight
        value = 0.
        if texts[0].startswith("trigger"):
            if self.mode == "combined_response_not_improved":
                value = (0. if w[0] == w[1] == 0 else 2.) if w[2] == 0 else (2. if w[0] == w[1] else 1.)
            elif self.mode == "random_control_insufficient":
                value = float(w[0]) * 2
        return torch.full((1, 77, 1), value)


class ScientificStopTests(unittest.TestCase):
    def test_all_actual_localization_stops_write_resolved_immutable_terminal(self):
        frozen = {"input_ids": [1] * 77, "attention_mask": [1] * 77}
        rows = []
        for i in range(64):
            texts = {kind: f"{kind}-{i}" for kind in ("trigger", "dog", "cat", "other")}
            rows.append({"id": f"c{i}", "partition": "localize", "texts": texts,
                         "tokenization": {kind: frozen for kind in texts}})
        plan = FrozenPlan("run", SHA, SHA, rows, (11, 12), (1, 2, 3), 99, {"fixture": SHA})
        for reason in ("no_positive_block", "combined_response_not_improved", "random_control_insufficient"):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                (output / "run_identity.json").write_text(json.dumps({"run_id": "run", "manifest_sha256": SHA}))
                runtime = StopRuntime(reason)
                blocks, _ = partition(runtime.assets.text_states["clean"], runtime.assets.text_states["backdoor"], block_size=1)
                ledger = LocalizationLedger(output / "localization.sqlite", "run", SHA,
                                            [row["id"] for row in rows], [block_id(b) for b in blocks])
                with patch("localization_runner.partition", side_effect=lambda a, b: partition(a, b, block_size=1)):
                    with self.assertRaises(ScientificStop) as caught:
                        run_localization(plan, runtime, ledger, output / "selection")
                self.assertEqual(caught.exception.reason_code, reason)
                ledger.db.execute("UPDATE forwards SET status='started' WHERE rowid=(SELECT MIN(rowid) FROM forwards)")
                with self.assertRaisesRegex(ValueError, "uncertain localization"):
                    persist_localization_stop(output, plan, ledger, caught.exception)
                ledger.db.execute("UPDATE forwards SET status='complete' WHERE status='started'")
                with sqlite3.connect(output / "images.sqlite") as db:
                    db.execute("CREATE TABLE attempts (id INTEGER)")
                    db.execute("INSERT INTO attempts VALUES (1)")
                with self.assertRaisesRegex(ValueError, "image attempts already exist"):
                    persist_localization_stop(output, plan, ledger, caught.exception)
                (output / "images.sqlite").unlink()
                terminal = persist_localization_stop(output, plan, ledger, caught.exception)
                self.assertEqual(terminal["outcome"], "inconclusive")
                self.assertEqual(terminal["resources"]["te_forward_completed"], runtime.calls)
                self.assertEqual(terminal["resources"]["te_forward_reservations"], runtime.calls)
                self.assertEqual(terminal["resources"]["source_image_attempts"], 0)
                self.assertEqual(terminal["resources"]["merge_image_attempts"], 0)
                self.assertEqual(terminal["resources"]["training_updates"], 0)
                self.assertEqual(set(terminal["skipped"]), {"source", "merge"})
                self.assertEqual(persist_localization_stop(output, plan, ledger, caught.exception), terminal)
                self.assertTrue((output / "localization_stop_report.md").exists())
                ledger.close()


if __name__ == "__main__":
    unittest.main()
