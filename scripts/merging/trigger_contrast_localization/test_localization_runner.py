import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import torch

from core import partition
from localization_ledger import LocalizationLedger
from localization_runner import run_localization
from preflight import FrozenPlan
from selection_audit import block_id, verify_selection

SHA = "a" * 64


class Tokenizer:
    def __call__(self, text, **kwargs):
        if kwargs.get("padding"):
            return {"input_ids": [1] * 77, "attention_mask": [1] * 77}
        return {"input_ids": [1, 2]}


class TinyTE(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.layer = torch.nn.Module()
        self.layer.weight = torch.nn.Parameter(torch.ones(40))


class Runtime:
    def __init__(self):
        self.text_encoder = TinyTE()
        self.assets = SimpleNamespace(tokenizer=Tokenizer(), parameter_names=("layer.weight",),
            text_states={"clean": {"layer.weight": torch.zeros(40)}, "backdoor": {"layer.weight": torch.ones(40)}},
            file_hashes={"fixture": {"sha256": SHA}})
        self.calls = 0
    def activate_source(self, source):
        state = "clean" if source == "clean" else "backdoor"
        self.text_encoder.load_state_dict(self.assets.text_states[state])
    def _embeddings(self, texts, scalars, alpha):
        self.calls += 1
        value = self.text_encoder.layer.weight[0] * 2 if texts[0].startswith("trigger") else self.text_encoder.layer.weight[0] * 0
        return value.expand(1, 77, 1)


class LocalizationRunnerTests(unittest.TestCase):
    def test_resume_magnitude_with_empty_paths_preserves_frozen_masks_and_completed_forwards(self):
        import hashlib
        import importlib.util
        import localization_runner
        patch_path = Path(__file__).resolve().parents[3] / "research/tasks/2026-10-29-trigger-contrast-localization/intervene_patch.py"
        spec = importlib.util.spec_from_file_location("tcl_reviewed_resume_test", patch_path)
        amended = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(amended)
        frozen = {"input_ids": [1] * 77, "attention_mask": [1] * 77}
        rows = []
        for i in range(64):
            texts = {kind: f"{kind}-{i}" for kind in ("trigger", "dog", "cat", "other")}
            rows.append({"id": f"c{i}", "partition": "localize", "texts": texts,
                         "tokenization": {kind: frozen for kind in texts}})
        plan = FrozenPlan("run", SHA, SHA, rows, (11, 12), (1, 2, 3), 99, {"fixture": SHA})
        runtime = Runtime()
        runtime.text_encoder.layer.bias = torch.nn.Parameter(torch.zeros(40))
        runtime.assets.parameter_names = ("layer.bias", "layer.weight")
        for state in ("clean", "backdoor"):
            runtime.assets.text_states[state]["layer.bias"] = torch.zeros(40)
        blocks, _ = partition(runtime.assets.text_states["clean"], runtime.assets.text_states["backdoor"], block_size=2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = LocalizationLedger(root / "localization.sqlite", "run", SHA, [r["id"] for r in rows], [block_id(b) for b in blocks])
            original = amended.intervene_resumable
            def stop_at_magnitude(*args):
                if args[8] == "control:magnitude":
                    raise ValueError("simulated historical empty-path rejection")
                return original(*args)
            with patch("localization_runner.partition", side_effect=lambda a, b: partition(a, b, block_size=2)):
                with patch("localization_runner.intervene_resumable", side_effect=stop_at_magnitude):
                    with self.assertRaisesRegex(ValueError, "historical empty-path"):
                        run_localization(plan, runtime, ledger, root / "selection")
                before = ledger.attempt_count()
                self.assertEqual(before, (2 + len(blocks) + 1) * 256)
                self.assertEqual(ledger.db.execute("SELECT COUNT(*) FROM forwards WHERE unit='control:magnitude'").fetchone()[0], 0)
                original_mask = (root / "selection" / "magnitude.mask.json").read_bytes()
                self.assertIn('"layer.bias":[]', original_mask.decode())
                original_preselection = (root / "selection" / "preselection.json").read_bytes()
                ledger.close()
                ledger = LocalizationLedger(root / "localization.sqlite", "run", SHA, [r["id"] for r in rows], [block_id(b) for b in blocks])
                with patch("localization_runner.intervene_resumable", new=amended.intervene_resumable):
                    result = run_localization(plan, runtime, ledger, root / "selection")
                self.assertEqual(ledger.attempt_count(), (2 + len(blocks) + 6) * 256)
                self.assertEqual(runtime.calls, ledger.attempt_count())
                self.assertEqual((root / "selection" / "magnitude.mask.json").read_bytes(), original_mask)
                self.assertEqual((root / "selection" / "preselection.json").read_bytes(), original_preselection)
                self.assertEqual(result["mask_sha256"]["magnitude"], hashlib.sha256(original_mask).hexdigest())
                binding = SimpleNamespace(run_id="run", manifest_sha=SHA, selection_sha="b" * 64,
                                          mask_hashes=result["mask_sha256"], random_seeds=(1, 2, 3))
                with patch("selection_audit.partition", side_effect=lambda a, b: partition(a, b, block_size=2)):
                    self.assertEqual(verify_selection(runtime, binding, ledger, [row["id"] for row in rows])["K"], result["K"])
            ledger.close()

    def test_interrupted_forward_is_recovered_in_same_localization(self):
        import os
        from recovery import recover_interrupted
        from run_store import lock_run
        frozen = {"input_ids": [1] * 77, "attention_mask": [1] * 77}
        rows = []
        for i in range(64):
            texts = {kind: f"{kind}-{i}" for kind in ("trigger", "dog", "cat", "other")}
            rows.append({"id": f"c{i}", "partition": "localize", "texts": texts,
                         "tokenization": {kind: frozen for kind in texts}})
        plan = FrozenPlan("run", SHA, SHA, rows, (11, 12), (1, 2, 3), 99, {"fixture": SHA})
        runtime = Runtime()
        original = runtime._embeddings
        def fail_once(*args):
            if runtime.calls == 3:
                raise RuntimeError("simulated disconnection")
            return original(*args)
        runtime._embeddings = fail_once
        blocks, _ = partition(runtime.assets.text_states["clean"], runtime.assets.text_states["backdoor"], block_size=2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = LocalizationLedger(root / "localization.sqlite", "run", SHA, [r["id"] for r in rows], [block_id(b) for b in blocks])
            with patch("localization_runner.partition", side_effect=lambda a, b: partition(a, b, block_size=2)):
                with self.assertRaisesRegex(RuntimeError, "disconnection"):
                    run_localization(plan, runtime, ledger, root / "selection")
                ledger.close()
                fd = lock_run(root)
                try:
                    recover_interrupted(root, plan, "localization", "simulated process interruption", fd)
                finally:
                    os.close(fd)
                ledger = LocalizationLedger(root / "localization.sqlite", "run", SHA, [r["id"] for r in rows], [block_id(b) for b in blocks])
                runtime._embeddings = original
                result = run_localization(plan, runtime, ledger, root / "selection")
                self.assertEqual(result["K"], 2)
                self.assertEqual(runtime.calls, (2 + len(blocks) + 6) * 256)
                self.assertEqual(ledger.attempt_count(), runtime.calls + 1)
                self.assertEqual(ledger.db.execute("SELECT COUNT(*) FROM forward_history").fetchone()[0], 1)
            ledger.close()

    def test_end_to_end_tiny_localization_and_idempotent_resume(self):
        frozen = {"input_ids": [1] * 77, "attention_mask": [1] * 77}
        rows = []
        for i in range(64):
            texts = {kind: f"{kind}-{i}" for kind in ("trigger", "dog", "cat", "other")}
            rows.append({"id": f"c{i}", "partition": "localize", "texts": texts,
                         "tokenization": {kind: frozen for kind in texts}})
        plan = FrozenPlan("run", SHA, SHA, rows, (11, 12), (1, 2, 3), 99, {"fixture": SHA})
        runtime = Runtime()
        blocks, _ = partition(runtime.assets.text_states["clean"], runtime.assets.text_states["backdoor"], block_size=2)
        with tempfile.TemporaryDirectory() as directory:
            ledger = LocalizationLedger(Path(directory) / "ledger.sqlite", "run", SHA,
                                        [row["id"] for row in rows], [block_id(b) for b in blocks])
            with patch("localization_runner.partition", side_effect=lambda a, b: partition(a, b, block_size=2)):
                result = run_localization(plan, runtime, ledger, Path(directory) / "selection")
                self.assertEqual(result["K"], 2)
                self.assertEqual(result["response_before"], 4.)
                self.assertEqual(result["response_after"], 0.)
                self.assertEqual(runtime.calls, (2 + len(blocks) + 6) * 256)
                binding = SimpleNamespace(run_id="run", manifest_sha=SHA, selection_sha="b" * 64,
                                          mask_hashes=result["mask_sha256"], random_seeds=(1, 2, 3))
                with patch("selection_audit.partition", side_effect=lambda a, b: partition(a, b, block_size=2)):
                    self.assertEqual(verify_selection(runtime, binding, ledger, [row["id"] for row in rows])["K"], 2)
                self.assertEqual(run_localization(plan, runtime, ledger, Path(directory) / "selection"), result)
                self.assertEqual(runtime.calls, (2 + len(blocks) + 6) * 256)
            ledger.close()


if __name__ == "__main__":
    unittest.main()
