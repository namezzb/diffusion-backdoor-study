import hashlib
import json
import unittest
from types import SimpleNamespace

import torch
from safetensors.torch import save

from core import coordinates_for_blocks, mask_hash, partition
from selection import build_selection
from selection_audit import block_id, verify_selection


class Cursor:
    def __init__(self, row):
        self.row = row
    def fetchone(self):
        return self.row


class FakeLedger:
    def __init__(self, ids, blocks):
        self.contexts = set(ids)
        self.identity = json.dumps({"run_id": "fixture", "manifest_sha": "b" * 64,
                                    "block_ids": [block_id(b) for b in blocks]})
        self.evidence = {}
        self.db = self
    def execute(self, query, args=()):
        if "metadata" in query:
            return Cursor((self.identity,))
        value = self.evidence.get(args[0])
        return Cursor(None if value is None else ("complete", hashlib.sha256(value).hexdigest(), value))
    def load(self, unit, kind, context):
        if unit == "baseline:backdoor":
            value = 2. if kind == "trigger" else 0.
        elif unit.startswith("control:"):
            value = (1. if unit == "control:new" else 1.5) if kind == "trigger" else 0.
        else:
            value = 0.
        return save({"embedding": torch.tensor([value])})
    def record(self, unit, value):
        self.evidence[unit] = json.dumps(value, sort_keys=True).encode()


class SelectionAuditTests(unittest.TestCase):
    def test_combination_is_recomputed_from_cached_outputs_and_selected_mask(self):
        ids = [f"c{i}" for i in range(64)]
        clean = {"layer.weight": torch.zeros(400)}
        backdoor = {"layer.weight": torch.ones(400)}
        blocks, delta = partition(clean, backdoor, block_size=4)
        scores = {b: 1. if 40 <= b.start < 60 else 0. for b in blocks}
        selected = build_selection(blocks, scores, delta, 4., 1., (1, 2, 3))
        ledger = FakeLedger(ids, blocks)
        ledger.record("baseline:clean", {})
        ledger.record("baseline:backdoor", {})
        for b in blocks:
            ledger.record("block:" + block_id(b), {"size": b.size, "mask_sha256": mask_hash(coordinates_for_blocks([b])),
                "response_before": 4., "response_after": 0. if scores[b] else 4.,
                "normal_costs": {"dog": 0., "cat": 0., "other": 0.}, "score": scores[b]})
        for name, coords in selected["groups"].items():
            after = 1. if name == "new" else 2.25
            ledger.record("control:" + name, {"size": 20, "mask_sha256": mask_hash(coords),
                "response_before": 4., "response_after": after,
                "normal_costs": {"dog": 0., "cat": 0., "other": 0.}, "score": (4. - after) / 20})
        assets = SimpleNamespace(parameter_names=("layer.weight",), text_states={"clean": clean, "backdoor": backdoor})
        runtime = SimpleNamespace(assets=assets)
        binding = SimpleNamespace(mask_hashes={name: mask_hash(coords) for name, coords in selected["groups"].items()},
                                  random_seeds=(1, 2, 3), selection_sha="a" * 64, run_id="fixture", manifest_sha="b" * 64)
        # Production uses fixed 2^19 blocks; this fixture replaces only the
        # block size so the five-percent selection remains meaningful.
        from unittest.mock import patch
        with patch("selection_audit.partition", side_effect=lambda a, b: partition(a, b, block_size=4)):
            result = verify_selection(runtime, binding, ledger, ids)
            self.assertEqual(result["K"], 20)
            self.assertEqual(runtime._tcl_verified_selection_sha, "a" * 64)
            forged = json.loads(ledger.evidence["control:new"])
            forged["response_after"] = .5
            ledger.record("control:new", forged)
            with self.assertRaisesRegex(ValueError, "differs from stored embedding"):
                verify_selection(runtime, binding, ledger, ids)
            self.assertIsNone(runtime._tcl_verified_selection_sha)


if __name__ == "__main__":
    unittest.main()
