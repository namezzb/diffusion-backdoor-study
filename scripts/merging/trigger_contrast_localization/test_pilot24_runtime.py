import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from bindings import FrozenBindings
from pilot24_inputs import RUN, PARENT, frozen_units
from pilot24_runtime import (PreparedWorker, ReadOnlyLocalization, REQUIRED_V2_CODE,
    _check_code, _check_loaded_modules, _labels, _read_ref, create_runtime, prepare_assets, prepare_worker)
from pilot24_worker_ledger import canonical, digest

REPOSITORY = Path(__file__).resolve().parents[3]
TASK = REPOSITORY / "research/tasks/2026-10-29-trigger-contrast-localization"


def write(path, value):
    raw = (canonical(value) + "\n").encode() if not isinstance(value, bytes) else value
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


class RuntimeBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.inputs = {}
        for name, file in (("context_ids", "pilot24_context_ids.json"), ("parent_manifest", "manifest_candidate.json"),
            ("prompts", "prompts_tokenized_candidate.jsonl"), ("parent_review", "m06_review.json"),
            ("context_review", "context_review.json")):
            self.inputs[name] = write(self.root / (name + ".json"), (TASK / file).read_bytes())
        self.parent = json.loads((TASK / "manifest_candidate.json").read_bytes())
        self.inputs["selection"] = write(self.root / "selection.json", {"status": "frozen"})
        self.inputs["localization_terminal"] = write(self.root / "terminal.json", {
            "run_id": PARENT, "manifest_sha256": self.inputs["parent_manifest"]["sha256"],
            "phase": "localize", "status": "complete"})
        for name in ("protocol", "asset_manifest", "localization_ledger", "source_isolation"):
            self.inputs[name] = write(self.root / (name + ".json"), {})
        # Preserve the real parent identities for the small loader inputs.
        self.parent["source_protocol_sha256"] = self.inputs["protocol"]["sha256"]
        self.parent["source_asset_manifest_sha256"] = self.inputs["asset_manifest"]["sha256"]
        self.inputs["parent_manifest"] = write(self.root / "parent_manifest.json", self.parent)
        ids = json.loads((TASK / "pilot24_context_ids.json").read_bytes())
        plan = json.loads((TASK / "pilot24_plan_candidate.json").read_bytes())
        plan["parent_manifest_sha256"] = self.inputs["parent_manifest"]["sha256"]
        plan["localization"]["selection_sha256"] = self.inputs["selection"]["sha256"]
        plan["localization"]["terminal_sha256"] = self.inputs["localization_terminal"]["sha256"]
        self.inputs["localization_terminal"] = write(self.root / "terminal.json", {
            "run_id": PARENT, "manifest_sha256": self.inputs["parent_manifest"]["sha256"],
            "phase": "localize", "status": "complete"})
        plan["localization"]["terminal_sha256"] = self.inputs["localization_terminal"]["sha256"]
        self.inputs["plan"] = write(self.root / "plan.json", plan)
        self.stages = frozen_units(self.inputs["plan"]["path"], self.inputs["context_ids"]["path"],
            self.inputs["parent_manifest"]["path"], self.inputs["prompts"]["path"])
        hashes = {(key[1], key[4], key[3]): digest(key[1:]) for stage in self.stages.values() for key in stage}
        masks = {key[2]: digest(key[2]) for stage in self.stages.values() for key in stage}
        self.bound = FrozenBindings(PARENT, self.inputs["parent_manifest"]["sha256"], "e" * 64,
            self.inputs["selection"]["sha256"], (271101, 271102), plan["bootstrap_seed"],
            tuple(plan["random_control_seeds"]), hashes, masks, {}, {key: (281,) for key in hashes}, {}, self.parent["asset_sha256"])
        self.bundle = {"schema_version": 1, "run_id": RUN, "status": "frozen", "repository_root": str(REPOSITORY),
            "models_root": str(self.root / "models"), "review_file": str(self.root / "review.json"),
            "inputs": self.inputs, "code_sha256": self.parent["code_sha256"]}
        self.bundle_ref = write(self.root / "bundle.json", self.bundle)
        self.review = {"status": "passed", "run_id": RUN, "manifest_sha256": self.bundle_ref["sha256"],
            "reviewer": "independent", "implementer": "worker"}
        write(self.root / "review.json", self.review)
        self.gate = {"run_id": RUN, "manifest_sha256": self.bundle_ref["sha256"], "stage": "S0", "passed": True,
            "config_sha256": "a" * 64, "predecessor_report_sha256": None}
        gate_ref = write(self.root / "gate.json", self.gate)
        key = self.stages["S0"][0]
        self.assignment = {"run_id": RUN, "stage": "S0", "manifest_sha256": self.bundle_ref["sha256"],
            "gate_sha256": gate_ref["sha256"], "output_root": str(self.root / "worker"),
            "units": [{"key": list(key), "input_sha": self.bound.input_hashes[(key[1], key[4], key[3])],
                "mask_sha": self.bound.mask_hashes[key[2]]}]}
        self.assignment["assignment_id"] = "worker-S0"
        template = {**self.assignment, "gate_sha256": digest({"run_id": RUN, "manifest_sha256": self.bundle_ref["sha256"], "stage": "S0"})}
        self.config = {"imports": [], "run_id": RUN, "manifest_sha256": self.bundle_ref["sha256"], "coordinator_root": str(self.root), "assignments": [template]}
        hashes = self.parent["asset_sha256"]
        self.config.update(model_bundle_sha256=digest(hashes), scorer_sha256=digest({
            "assets": {name: value for name, value in hashes.items() if name.split('/')[0] in ("vit", "clip")},
            "code": {name: self.parent["code_sha256"][name] for name in ("scripts/merging/tssa_mvp_score.py", "scripts/merging/tssa_sd_runtime.py")},
            "dtype": "float32", "device": "cpu", "image_source": "saved_rgb_png", "score_prompt": "untriggered_paired_prompt"}),
            stages={stage: [list(key) for key in keys] for stage, keys in self.stages.items()},
            units=[{"key": list(key), "input_sha": self.bound.input_hashes[(key[1], key[4], key[3])],
                "mask_sha": self.bound.mask_hashes[key[2]]} for keys in self.stages.values() for key in keys],
            labels=_labels(self.stages, self.bound))
        config_ref = write(self.root / "config.json", self.config)
        self.review.update(coordinator_config_file=config_ref["path"], coordinator_config_sha256=config_ref["sha256"])
        write(self.root / "review.json", self.review)
        self.gate["config_sha256"] = digest(self.config)
        gate_ref = write(self.root / "gate.json", self.gate)
        self.assignment["gate_sha256"] = gate_ref["sha256"]
        write(self.root / "assignment.json", self.assignment)
        self.modules = patch("pilot24_runtime._module", side_effect=self.module)
        self.code = patch("pilot24_runtime._check_code")
        self.modules.start()
        self.code.start()

    def tearDown(self):
        self.modules.stop()
        self.code.stop()
        self.temp.cleanup()

    def module(self, root, name):
        if name == "preflight":
            return SimpleNamespace(load_plan=lambda *args: SimpleNamespace(run_id=PARENT, manifest_sha=self.bound.manifest_sha))
        if name == "bindings":
            return SimpleNamespace(load_frozen_bindings=lambda *args: self.bound)
        if name == "pilot24_coordinator":
            return SimpleNamespace(verify_release=lambda *args: True)
        if name == "pilot24_provenance":
            return SimpleNamespace(validate_source_isolation=lambda *args, **kwargs: {"mode": "copied_namespace", "old_writer": "unknown",
                "parent_manifest": self.inputs["parent_manifest"], "context_ids": self.inputs["context_ids"],
                "copies": [{"role": role, **self.inputs[role]} for role in ("selection", "localization_terminal", "localization_ledger")], "imports": []})
        return SimpleNamespace()

    def prepare(self):
        return prepare_worker(self.root / "bundle.json", self.root / "assignment.json", self.root / "gate.json")

    def test_frozen_inputs_map_exact_v2_keys_without_gpu_load(self):
        prepared = self.prepare()
        self.assertEqual(sum(map(len, prepared.stages.values())), 6144)
        self.assertEqual(prepared.bindings.run_id, RUN)
        self.assertEqual(prepared.bindings.seeds, (271101,))
        self.assertIsNone(prepared.assets)
        self.assertEqual({state: len(rows) for state, rows in prepared.labels.items()}, {"source": 128, "merge": 64})
        self.assertEqual(prepared.provenance["source_isolation"]["old_writer"], "unknown")
        self.assertEqual(prepared.model_bundle_sha256, digest(self.parent["asset_sha256"]))

    def test_review_of_other_bundle_or_same_implementer_is_rejected(self):
        for change in ({"manifest_sha256": "f" * 64}, {"reviewer": "worker"}):
            write(self.root / "review.json", {**self.review, **change})
            with self.assertRaisesRegex(ValueError, "independent review"):
                self.prepare()

    def test_forged_assignment_prompt_mask_or_outside_stage_rejected(self):
        for field, value in (("input_sha", "0" * 64), ("mask_sha", "0" * 64), ("key", list(self.stages["M0"][0]))):
            changed = json.loads(canonical(self.assignment))
            changed["units"][0][field] = value
            write(self.root / "assignment.json", changed)
            with self.assertRaisesRegex(ValueError, "assignment differs|assigned key"):
                self.prepare()

    def test_duplicate_key_rejected(self):
        self.assignment["units"].append(self.assignment["units"][0])
        write(self.root / "assignment.json", self.assignment)
        with self.assertRaisesRegex(ValueError, "assignment differs|assigned key"):
            self.prepare()

    def test_unreviewed_configuration_and_forged_template_rejected(self):
        modified = json.loads(canonical(self.config))
        modified["coordinator_root"] = "/different/root"
        write(self.root / "config.json", modified)
        with self.assertRaisesRegex(ValueError, "differs from independent review"):
            self.prepare()
        write(self.root / "config.json", self.config)
        self.assignment["worker_id"] = "other-worker"
        write(self.root / "assignment.json", self.assignment)
        with self.assertRaisesRegex(ValueError, "reviewed template"):
            self.prepare()

    def test_reviewed_configuration_cannot_change_the_scientific_inputs(self):
        self.config["units"][0]["input_sha"] = "1" * 64
        config_ref = write(self.root / "config.json", self.config)
        self.review["coordinator_config_sha256"] = config_ref["sha256"]
        write(self.root / "review.json", self.review)
        self.gate["config_sha256"] = digest(self.config)
        gate_ref = write(self.root / "gate.json", self.gate)
        self.assignment["gate_sha256"] = gate_ref["sha256"]
        write(self.root / "assignment.json", self.assignment)
        with self.assertRaisesRegex(ValueError, "scientific inputs differ"):
            self.prepare()

    def test_changed_gate_bytes_rejected(self):
        self.gate["passed"] = False
        write(self.root / "gate.json", self.gate)
        with self.assertRaisesRegex(ValueError, "stage release"):
            self.prepare()

    def test_equal_hash_elsewhere_does_not_replace_the_sealed_localization_copy(self):
        original = self.module
        def module(root, name):
            value = original(root, name)
            if name == "pilot24_provenance":
                proof = value.validate_source_isolation()
                proof["copies"][2]["path"] = str(self.root / "different-original.sqlite")
                return SimpleNamespace(validate_source_isolation=lambda *args, **kwargs: proof)
            return value
        with patch("pilot24_runtime._module", side_effect=module):
            with self.assertRaisesRegex(ValueError, "authenticated snapshot copies"):
                self.prepare()

    def test_changed_bound_input_rejected_before_loader(self):
        Path(self.inputs["source_isolation"]["path"]).write_text("changed")
        with self.assertRaisesRegex(ValueError, "bound input changed"):
            self.prepare()

    def test_cpu_assets_are_checked_and_selection_is_recomputed_without_cuda(self):
        prepared = self.prepare()
        assets = SimpleNamespace(file_hashes={k: {"sha256": v} for k, v in self.parent["asset_sha256"].items()})
        rows = [{"id": "ctx-" + str(i), "partition": "localize"} for i in range(64)]
        calls = []
        def module(root, name):
            if name == "runtime_assets":
                return SimpleNamespace(load_tcl_cpu_assets=lambda *args: (assets, rows, {"cpu_only": True}))
            if name == "selection_audit":
                def verify(shell, binding, ledger, contexts):
                    calls.append((binding.run_id, len(contexts)))
                    shell._tcl_verified_selection_sha = binding.selection_sha
                    return {"selection_sha256": binding.selection_sha}
                return SimpleNamespace(verify_selection=verify)
            return self.module(root, name)
        with patch("pilot24_runtime._module", side_effect=module), patch("pilot24_runtime.ReadOnlyLocalization"), patch("torch.cuda.is_initialized", return_value=False), patch("pilot24_runtime._verify_parent_selection_v2", side_effect=lambda audit, *args: audit.verify_selection(*args)):
            self.assertIs(prepare_assets(prepared), prepared)
            self.assertEqual(calls, [(PARENT, 64)])
            self.assertIs(prepare_assets(prepared), prepared)
            self.assertEqual(len(calls), 1)
        self.assertIs(prepared.assets, assets)
        self.assertTrue(prepared.cpu_report["cpu_only"])

    def test_cpu_asset_hash_mismatch_or_prior_cuda_initialization_rejected(self):
        prepared = self.prepare()
        with patch("torch.cuda.is_initialized", return_value=True):
            with self.assertRaisesRegex(ValueError, "precede CUDA"):
                prepare_assets(prepared)
        with patch("torch.cuda.is_initialized", return_value=False), patch("pilot24_runtime._module", return_value=SimpleNamespace(
                load_tcl_cpu_assets=lambda *args: (SimpleNamespace(file_hashes={}), [], {}))):
            with self.assertRaisesRegex(ValueError, "differ from frozen assets"):
                prepare_assets(prepared)

    def test_cuda_factory_rejects_unprepared_and_wrong_gpu(self):
        prepared = self.prepare()
        with self.assertRaisesRegex(ValueError, "CPU preparation"):
            create_runtime(prepared)
        prepared.assets, prepared.selection_report = object(), {}
        prepared.assignment["gpu_uuid"] = "GPU-assigned"
        with patch.dict(os.environ, {"CUBLAS_WORKSPACE_CONFIG": ":4096:8", "GPU_UUID": "GPU-other", "CUDA_VISIBLE_DEVICES": "GPU-other"}):
            with self.assertRaisesRegex(ValueError, "assigned GPU"):
                create_runtime(prepared)


class ReadOnlyAndCodeTests(unittest.TestCase):
    def test_readonly_localization_cannot_write_or_accept_wal(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp).resolve() / "localization.sqlite"
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE forwards(unit TEXT,class TEXT,context TEXT,status TEXT,output_sha TEXT,output BLOB)")
            data = b"embedding"
            db.execute("INSERT INTO forwards VALUES('unit','dog','ctx','complete',?,?)", (hashlib.sha256(data).hexdigest(), data))
            db.commit()
            db.close()
            before = path.read_bytes()
            ledger = ReadOnlyLocalization(path, ["ctx"])
            self.assertEqual(ledger.load("unit", "dog", "ctx"), data)
            with self.assertRaises(sqlite3.OperationalError):
                ledger.db.execute("DELETE FROM forwards")
            ledger.close()
            self.assertEqual(before, path.read_bytes())
            Path(str(path) + "-wal").write_bytes(b"uncheckpointed")
            with self.assertRaisesRegex(ValueError, "standalone"):
                ReadOnlyLocalization(path, ["ctx"])

    def test_code_hash_tamper_and_missing_dependency_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            sources = {}
            for relative in REQUIRED_V2_CODE:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# approved\n")
                sources[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            _check_code(root, sources)
            name = sorted(sources)[0]
            (root / name).write_text("# changed\n")
            with self.assertRaisesRegex(ValueError, "implementation differs"):
                _check_code(root, sources)
            del sources[name]
            with self.assertRaisesRegex(ValueError, "complete v2"):
                _check_code(root, sources)

    def test_loaded_module_shadow_is_rejected(self):
        relative = "scripts/merging/trigger_contrast_localization/fake_runtime_module.py"
        with patch.dict(sys.modules, {"fake_runtime_module": SimpleNamespace(__file__="/different/fake_runtime_module.py")}):
            with self.assertRaisesRegex(ValueError, "shadowed"):
                _check_loaded_modules(REPOSITORY, {relative: "a" * 64})

    def test_large_snapshot_hashing_streams_and_cache_detects_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp).resolve() / "large.sqlite"
            raw = b"x" * (2 * 1024 * 1024)
            path.write_bytes(raw)
            ref = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
            path.chmod(0o444)
            with patch.object(Path, "read_bytes", side_effect=AssertionError("must stream")):
                self.assertIsNone(_read_ref(ref, contents=False))
                self.assertIsNone(_read_ref(ref, contents=False))
            path.chmod(0o644)
            path.write_bytes(b"y" * len(raw))
            path.chmod(0o444)
            with self.assertRaisesRegex(ValueError, "bound input changed"):
                _read_ref(ref, contents=False)

    def test_input_symlink_and_missing_hash_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = root / "target"
            target.write_bytes(b"data")
            link = root / "link"
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                _read_ref({"path": str(link), "sha256": hashlib.sha256(b"data").hexdigest()})
            with self.assertRaises(ValueError):
                _read_ref({"path": str(target), "sha256": "unknown"})


if __name__ == "__main__":
    unittest.main()
