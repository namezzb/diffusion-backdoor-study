import tempfile
import unittest
import importlib.util
from pathlib import Path

import torch

from intervene import intervene_once, intervene_resumable
from localization_ledger import KINDS, LocalizationLedger
from core import mask_hash


class MiniTE(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.weight = torch.nn.Parameter(torch.tensor([2., 3.]))


class InterventionTests(unittest.TestCase):
    def test_empty_paths_are_noops_without_changing_mask_or_unsorted_coordinates(self):
        patch_path = Path(__file__).resolve().parents[3] / "research/tasks/2026-10-29-trigger-contrast-localization/intervene_patch.py"
        spec = importlib.util.spec_from_file_location("tcl_reviewed_patch_test", patch_path)
        amended = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(amended)
        model = MiniTE()
        model.other = torch.nn.Parameter(torch.tensor([9.]))
        clean = {"weight": torch.tensor([0., 0.]), "other": torch.tensor([4.])}
        coordinates = {"weight": torch.tensor([1, 0]), "other": torch.tensor([], dtype=torch.int64)}
        original_hash = mask_hash(coordinates)
        prompts = {k: [k] for k in KINDS}
        base_clean = {k: torch.tensor([[0.]]) for k in KINDS}
        base_bd = {k: torch.tensor([[5. if k == "trigger" else 0.]]) for k in KINDS}
        charged = []
        def forward(m, prompt):
            return m.weight.sum().reshape(1) if prompt == "trigger" else m.weight[:1] * 0
        result = amended.intervene_once(model, clean, coordinates, prompts, base_clean, base_bd, charged.append, forward)
        self.assertEqual(result["size"], 2)
        self.assertEqual(result["response_after"], 0.)
        self.assertEqual(model.weight.tolist(), [2., 3.])
        self.assertEqual(model.other.tolist(), [9.])
        self.assertEqual(coordinates["weight"].tolist(), [1, 0])
        self.assertEqual(mask_hash(coordinates), original_hash)
        self.assertEqual(len(charged), 4)
        for indices in (torch.tensor([0, 0]), torch.tensor([-1]), torch.tensor([2])):
            with self.assertRaisesRegex(ValueError, "invalid or repeated coordinate"):
                amended.intervene_once(model, clean, {"weight": indices, "other": coordinates["other"]}, prompts,
                               base_clean, base_bd, charged.append, forward)
        with self.assertRaisesRegex(ValueError, "at least one"):
            amended.intervene_once(model, clean, {"weight": torch.tensor([], dtype=torch.int64)}, prompts,
                           base_clean, base_bd, charged.append, forward)
        self.assertEqual(len(charged), 4)

    def test_exact_parameter_intervention_and_finally_restore(self):
        model = MiniTE()
        clean = {"weight": torch.tensor([0., 3.])}
        prompts = {k: [k] for k in ("trigger", "dog", "cat", "other")}
        base_clean = {k: torch.tensor([[0.]]) for k in prompts}
        base_bd = {k: torch.tensor([[2. if k == "trigger" else 0.]]) for k in prompts}
        charged = []
        def forward(m, prompt):
            return m.weight[:1] if prompt == "trigger" else m.weight[:1] * 0
        result = intervene_once(model, clean, {"weight": torch.tensor([0])}, prompts, base_clean, base_bd, charged.append, forward)
        self.assertEqual(result["response_before"], 4.)
        self.assertEqual(result["response_after"], 0.)
        self.assertEqual(result["score"], 4.)
        self.assertEqual(len(charged), 4)
        self.assertEqual(model.weight.tolist(), [2., 3.])
        def fail(m, prompt):
            raise RuntimeError("interrupted")
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            intervene_once(model, clean, {"weight": torch.tensor([0])}, prompts, base_clean, base_bd, charged.append, fail)
        self.assertEqual(len(charged), 5)
        self.assertEqual(model.weight.tolist(), [2., 3.])

    def test_resumable_reuses_prior_output_and_charges_only_remaining(self):
        model = MiniTE()
        clean = {"weight": torch.tensor([0., 3.])}
        contexts = [f"c{i}" for i in range(64)]
        prompts = {k: [k] * 64 for k in KINDS}
        base_clean = {k: torch.zeros(64, 1) for k in KINDS}
        base_bd = {k: torch.full((64, 1), 2. if k == "trigger" else 0.) for k in KINDS}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "localize.sqlite"
            ledger = LocalizationLedger(path, "run", "a" * 64, contexts, ["b0"])
            for baseline in ("clean", "backdoor"):
                unit = "baseline:" + baseline
                ledger.begin(unit)
                for kind in KINDS:
                    for context in contexts:
                        ledger.reserve(unit, kind, context)
                        ledger.record(unit, kind, context, b"baseline fixture")
                ledger.complete(unit, b"baseline evidence")
            ledger.begin("block:b0")
            # A completed preexisting unit entry is loaded, not forwarded again.
            from safetensors.torch import save
            ledger.reserve("block:b0", "trigger", contexts[0])
            ledger.record("block:b0", "trigger", contexts[0], save({"embedding": torch.tensor([0.])}))
            ledger.close()
            ledger = LocalizationLedger(path, "run", "a" * 64, contexts, ["b0"])
            ledger.resume("block:b0")
            calls = []
            def forward(m, prompt):
                calls.append(prompt)
                return m.weight[:1] if prompt == "trigger" else m.weight[:1] * 0
            result = intervene_resumable(model, clean, {"weight": torch.tensor([0])}, contexts, prompts,
                                         base_clean, base_bd, ledger, "block:b0", forward)
            self.assertEqual(len(calls), 255)
            self.assertEqual(result["score"], 4.)
            self.assertEqual(len(result["evidence_sha256"]), 64)
            self.assertEqual(model.weight.tolist(), [2., 3.])
            self.assertEqual(ledger.db.execute("SELECT COUNT(*) FROM forwards").fetchone()[0], 768)
            ledger.close()


if __name__ == "__main__":
    unittest.main()
