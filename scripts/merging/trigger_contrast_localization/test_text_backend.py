import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import torch
from safetensors.torch import save

from localization_ledger import LocalizationLedger
from text_backend import TextBackend


class Tokenizer:
    def __call__(self, text, **kwargs):
        if kwargs.get("padding"):
            return {"input_ids": [1] * 77, "attention_mask": [1] * 77}
        return {"input_ids": [1, 2]}


class Runtime:
    def __init__(self):
        self.assets = SimpleNamespace(tokenizer=Tokenizer())
        self.text_encoder = object()
        self.calls = 0
    def activate_source(self, source):
        self.source = source
    def _embeddings(self, texts, scalars, alpha):
        self.calls += 1
        return torch.ones(1, 77, 2)


class TextBackendTests(unittest.TestCase):
    def test_baseline_reuses_saved_per_context_output(self):
        frozen = {"input_ids": [1] * 77, "attention_mask": [1] * 77}
        rows = []
        for i in range(64):
            texts = {kind: f"{kind}-{i}" for kind in ("trigger", "dog", "cat", "other")}
            rows.append({"id": f"c{i}", "partition": "localize", "texts": texts,
                         "tokenization": {kind: frozen for kind in texts}})
        runtime = Runtime()
        adapter = TextBackend(runtime, rows)
        with tempfile.TemporaryDirectory() as directory:
            ledger = LocalizationLedger(Path(directory) / "ledger.sqlite", "run", "a" * 64, adapter.ids, ["b0"])
            ledger.begin("baseline:clean")
            ledger.reserve("baseline:clean", "trigger", adapter.ids[0])
            ledger.record("baseline:clean", "trigger", adapter.ids[0], save({"embedding": torch.ones(77, 2)}))
            output = adapter.baseline(ledger, "clean")
            self.assertEqual(runtime.calls, 255)
            self.assertEqual(output["trigger"].shape, (64, 77, 2))
            self.assertEqual(ledger.db.execute("SELECT COUNT(*) FROM forwards").fetchone()[0], 256)
            with self.assertRaisesRegex(ValueError, "completed baseline"):
                adapter.baseline(ledger, "clean")
            ledger.close()


if __name__ == "__main__":
    unittest.main()
