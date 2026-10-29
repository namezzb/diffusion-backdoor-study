import json
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from confirmation_runner import run_confirmation
from evidence import CLASSES
from preflight import FrozenPlan


class FakeScorer:
    def __init__(self, root):
        self.root = root.resolve()


class ConfirmationRunnerTests(unittest.TestCase):
    def fixture(self, gates):
        keyset = [(state, state + "0", category) for state in ("source", "merge") for category in CLASSES]
        bindings = SimpleNamespace(run_id="run", manifest_sha="a", seeds=(11,12),
            prompt_rows={key: json.dumps({"prompt": "p", "score_prompt": "p", "tokenization": {}}) for key in keyset},
            input_hashes={key: "h" for key in keyset}, mask_hashes={name: "m" for name in
                ("clean", "backdoor", "new", "magnitude", "block_magnitude", "random_1", "random_2", "random_3")})
        ledger = SimpleNamespace(bindings=bindings, ids={"source": ["source0"], "merge": ["merge0"]},
                                 evaluate_gate=lambda name, path: gates[name])
        runtime = SimpleNamespace(assets=SimpleNamespace(models_root=Path(".")))
        plan = FrozenPlan("run", "a", "b", [{"id": "loc0", "partition": "localize"}], (11,12), (1,2,3), 99, {})
        return plan, runtime, bindings, ledger

    def test_baseline_failure_skips_all_restoration_and_merge(self):
        plan, runtime, bindings, ledger = self.fixture({"source_baseline": {"value": "fail"}})
        module = types.ModuleType("tssa_mvp_score")
        module.IndependentScorer = FakeScorer
        calls = []
        with patch.dict(sys.modules, {"tssa_mvp_score": module}), \
                patch("confirmation_runner.verify_selection", return_value={}), \
                patch("confirmation_runner.run_image", side_effect=lambda *a: calls.append(a)):
            result = run_confirmation(plan, runtime, bindings, ledger, None, FakeScorer(Path(".")), ".")
        self.assertEqual(result["outcome"], "inconclusive")
        self.assertEqual(result["merge"], "skipped")
        self.assertEqual(len(calls), 16)
        self.assertTrue(all(call[4] == "source" and call[5] in ("clean", "backdoor") for call in calls))

    def test_source_pass_then_merge_baseline_failure(self):
        gates = {"source_baseline": {"value": "pass"}, "source_result": {"value": "pass"},
                 "merge_baseline": {"value": "fail"}}
        plan, runtime, bindings, ledger = self.fixture(gates)
        module = types.ModuleType("tssa_mvp_score")
        module.IndependentScorer = FakeScorer
        calls = []
        with patch.dict(sys.modules, {"tssa_mvp_score": module}), \
                patch("confirmation_runner.verify_selection", return_value={}), \
                patch("confirmation_runner.run_image", side_effect=lambda *a: calls.append(a)):
            result = run_confirmation(plan, runtime, bindings, ledger, None, FakeScorer(Path(".")), ".")
        self.assertEqual(result["outcome"], "inconclusive")
        self.assertEqual(result["merge"], "skipped_after_baseline")
        self.assertEqual(len(calls), 80)
        self.assertTrue(all(call[5] in ("clean", "backdoor") for call in calls if call[4] == "merge"))


if __name__ == "__main__":
    unittest.main()
