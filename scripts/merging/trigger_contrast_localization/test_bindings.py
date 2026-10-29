import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from bindings import load_frozen_bindings
from evidence import VERSIONS


def sha(data):
    return hashlib.sha256(data).hexdigest()


class BindingTests(unittest.TestCase):
    def test_review_and_post_localization_selection_bind_exact_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code = root / "runner.py"
            code.write_text("# fixture\n")
            prompts = Path("research/tasks/2026-10-29-trigger-contrast-localization/prompts_tokenized_candidate.jsonl")
            manifest = {"status": "frozen", "task_id": "TCL-20261029-01", "run_id": "fixture",
                        "prompts_sha256": sha(prompts.read_bytes()), "generation_seeds": [11, 12], "bootstrap_seed": 99, "random_control_seeds": [1, 2, 3],
                        "asset_sha256": {"fixture/model": "a" * 64}, "code_sha256": {"runner.py": sha(code.read_bytes())}}
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest))
            msha = sha(manifest_path.read_bytes())
            review = root / "m06.json"
            review.write_text(json.dumps({"status": "passed", "manifest_sha256": msha, "reviewer": "fixture"}))
            selection = root / "selection.json"
            mask_files, masks = {}, {}
            for i, name in enumerate(VERSIONS):
                mask = {} if name in ("clean", "backdoor") else {"w": [i]}
                content = json.dumps(mask, sort_keys=True, separators=(",", ":")).encode()
                file = root / f"{name}.json"
                file.write_bytes(content)
                mask_files[name], masks[name] = file.name, sha(content)
            selection.write_text(json.dumps({"status": "frozen", "run_id": "fixture", "manifest_sha256": msha,
                                              "mask_sha256": masks, "mask_files": mask_files}))
            binding = load_frozen_bindings(manifest_path, prompts, review, selection, root)
            self.assertEqual(len(binding.input_hashes), 1024)
            self.assertEqual(len(binding.labels), 1024)
            self.assertEqual(binding.seeds, (11, 12))
            selection.write_text(json.dumps({"status": "frozen", "run_id": "other", "manifest_sha256": msha}))
            with self.assertRaisesRegex(ValueError, "selection"):
                load_frozen_bindings(manifest_path, prompts, review, selection, root)


if __name__ == "__main__":
    unittest.main()
