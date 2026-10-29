import tempfile
import unittest
from pathlib import Path

import torch

from intervene import intervene_once, intervene_resumable
from localization_ledger import KINDS, LocalizationLedger


class MiniTE(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.weight = torch.nn.Parameter(torch.tensor([2., 3.]))


class InterventionTests(unittest.TestCase):
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
