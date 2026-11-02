import copy
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from pilot24_coordinator import offline_stage_report, validate_partition
from pilot24_inputs import RUN, frozen_units
from test_pilot24_offline import TASK


class PartitionAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stages = frozen_units(TASK / "pilot24_plan_candidate.json", TASK / "pilot24_context_ids.json",
                                  TASK / "manifest_candidate.json", TASK / "prompts_tokenized_candidate.jsonl")

    def assignments(self):
        return [{"run_id": RUN, "stage": stage, "worker_id": "one", "server": "104",
                 "gpu_uuid": "GPU-01234567-89ab-cdef-0123-456789abcdef", "manifest_sha256": "a" * 64,
                 "gate_sha256": "b" * 64, "retry_tokens": 32,
                 "units": [{"key": list(k), "input_sha": "c" * 64, "mask_sha": "d" * 64} for k in self.stages[stage]]}
                for stage in ("S0", "S1", "M0", "M1")]

    def test_exhaustive_partition_and_source_merge_retry_limits(self):
        assignments = self.assignments()
        audit = validate_partition(self.stages, assignments, [])
        self.assertEqual(audit["assigned"], 6144)
        self.assertEqual(audit["retry_tokens"], {"source": 64, "merge": 64})
        assignments[0]["retry_tokens"] += 1
        with self.assertRaises(ValueError):
            validate_partition(self.stages, assignments, [])

    def test_duplicate_missing_and_import_collision_rejected(self):
        for variant in ("duplicate", "missing", "import_collision"):
            assignments = self.assignments()
            imported = []
            if variant == "duplicate":
                assignments[0]["units"].append(copy.deepcopy(assignments[0]["units"][0]))
            elif variant == "missing":
                assignments[0]["units"].pop()
            else:
                imported.append(assignments[0]["units"][0]["key"])
            with self.assertRaises(ValueError):
                validate_partition(self.stages, assignments, imported)

    def test_short_uuid_and_mixed_manifests_rejected(self):
        assignments = self.assignments()
        assignments[0]["gpu_uuid"] = "GPU-1234"
        with self.assertRaises(ValueError):
            validate_partition(self.stages, assignments, [])
        assignments = self.assignments()
        assignments[0]["manifest_sha256"] = "e" * 64
        with self.assertRaises(ValueError):
            validate_partition(self.stages, assignments, [])

    def test_baseline_requires_all_verified_bound_images(self):
        keys = self.stages["S0"]
        labels = {k[4]: {"trigger": list(range(281, 288)), "dog": [151], "cat": [281], "other": [330]} for k in keys}
        bindings = {k: {"input_sha": "c" * 64, "mask_sha": "d" * 64} for k in keys}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "original.png"
            Image.new("RGB", (512, 512)).save(image)
            sha = hashlib.sha256(image.read_bytes()).hexdigest()
            records = []
            for i, key in enumerate(keys):
                path = root / (str(i) + ".png")
                os.link(image, path)
                category = key[3]
                score_class = {"trigger": 281 if key[2] == "backdoor" else 151,
                               "dog": 151, "cat": 281, "other": 330}[category]
                records.append({"key": list(key), **bindings[key], "model_bundle_sha256": "a" * 64,
                                "scorer_sha256": "b" * 64, "image_path": str(path), "image_sha": sha,
                                "scores": {"vit_class": score_class, "clip_score": 30.0}})
            result = offline_stage_report("S0", self.stages, bindings, records, labels, "a" * 64, "b" * 64)
            self.assertTrue(result["passed"])
            self.assertEqual(result["records"], 1024)
            self.assertEqual(result["authorization"], "none_offline_report_only")
            with self.assertRaises(ValueError):
                offline_stage_report("S0", self.stages, bindings, records[:-1], labels, "a" * 64, "b" * 64)
            records[0]["mask_sha"] = "e" * 64
            with self.assertRaises(ValueError):
                offline_stage_report("S0", self.stages, bindings, records, labels, "a" * 64, "b" * 64)
if __name__ == "__main__":
    unittest.main()
