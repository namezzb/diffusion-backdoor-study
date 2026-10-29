import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime_assets import load_tcl_cpu_assets


class RuntimeAssetsTests(unittest.TestCase):
    def test_verified_loader_checks_all_candidate_texts_without_forward(self):
        verified = {"sd15/file": {"sha256": "a" * 64}}
        fixture = SimpleNamespace(file_hashes=verified, tokenizer=object())
        semantic = types.ModuleType("tssa_target_semantic_runtime")
        semantic.load_semantic_cpu_assets = lambda *args: fixture
        calls = []
        sd_runtime = types.ModuleType("tssa_sd_runtime")
        sd_runtime._check_tokenizers = lambda left, right, prompts, label: calls.append((prompts, label))
        with tempfile.TemporaryDirectory() as directory:
            prompt = Path(directory) / "rows.jsonl"
            prompt.write_text(json.dumps({"texts": {"trigger": "tr", "dog": "dog", "cat": "cat", "other": "rabbit"}}) + "\n")
            with patch.dict(sys.modules, {"tssa_target_semantic_runtime": semantic, "tssa_sd_runtime": sd_runtime}), \
                    patch("runtime_assets.verify_active_assets", return_value=verified), \
                    patch("runtime_assets.validate_contexts", return_value={"tokenizer_verified": True}), \
                    patch("transformers.CLIPTokenizer.from_pretrained", return_value=object()):
                actual, rows, report = load_tcl_cpu_assets("protocol", "manifest", directory, prompt, "review", "a" * 64)
            self.assertIs(actual, fixture)
            self.assertEqual(calls, [(["tr", "dog", "cat", "rabbit"], "TCL Edev")])
            self.assertTrue(report["cpu_only"])
            self.assertEqual(report["model_forward_count"], 0)
            self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
