"""Real TCL backend for the resumable runtime, without pilot24 launch machinery.

The immutable parent review authenticates historical scientific inputs.  It is
not a new launch approval.  The caller owns the run lock, attempt reservations,
deadline and live GPU permission; no function here creates permission evidence.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
from types import SimpleNamespace


STAGES = ("S0", "S1", "M0", "M1")
REQUIRED_INPUTS = frozenset(("parent_manifest", "prompts", "parent_review", "selection",
    "protocol", "asset_manifest", "context_review", "localization_ledger",
    "localization_terminal", "plan", "context_ids"))
SCIENTIFIC_HELPERS = frozenset("scripts/merging/trigger_contrast_localization/" + name + ".py"
    for name in ("pilot24_inputs", "pilot24_statistics", "pilot24_runtime"))
OVERNIGHT_HELPER = "scripts/merging/trigger_contrast_localization/overnight_science.py"
SEMANTIC_HELPERS = frozenset("scripts/merging/trigger_contrast_localization/" + name + ".py"
    for name in ("semantic_science", "semantic_scoring"))


HISTORICAL_RUNS = frozenset(("tcl-20261029-01-v1", "tcl-20261102-pilot24-v2",
                            "tcl-20261102-overnight-v1"))


def require_current_run(run_id, run_root):
    """Cheap ownership boundary, independent of optional scientific audits."""
    if run_id in HISTORICAL_RUNS or HISTORICAL_RUNS.intersection(Path(run_root).parts):
        raise ValueError("historical run identity or directory is read-only")


def stage_of(key):
    if len(key) != 6 or key[1] not in ("source", "merge"):
        raise ValueError("invalid TCL unit key")
    return ("S" if key[1] == "source" else "M") + ("0" if key[2] in ("clean", "backdoor") else "1")


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _regular(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or any(p.is_symlink() for p in path.parents):
        raise ValueError("absolute ordinary input file required: " + str(path))
    return path


def _ref(ref, *, read=True):
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise ValueError("scientific input requires path and SHA256")
    path = _regular(ref["path"])
    digest = hashlib.sha256()
    parts = []
    before = path.stat()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            if read:
                parts.append(block)
    after = path.stat()
    if digest.hexdigest() != ref["sha256"] or (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("scientific input changed: " + str(path))
    return b"".join(parts) if read else None


def audit_build_spec(request):
    """Expand real source paths into one self-contained, directly usable spec.

    This CPU-only operation does not grant compute permission or import images.
    Missing source artifacts remain errors rather than fabricated placeholders.
    """
    if not isinstance(request.get("run_id"), str) or not request["run_id"].strip():
        raise ValueError("a new nonempty run_id is required")
    root = Path(request.get("repository_root", Path(__file__).resolve().parents[3])).resolve()
    inputs = {}
    raw_inputs = request.get("inputs", {})
    if set(raw_inputs) != REQUIRED_INPUTS:
        raise ValueError("request.inputs must contain exactly: " + ", ".join(sorted(REQUIRED_INPUTS)))
    for name, value in raw_inputs.items():
        if isinstance(value, str):
            path = _regular(value)
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            inputs[name] = {"path": str(path), "sha256": digest.hexdigest()}
        else:
            _ref(value, read=False)
            inputs[name] = dict(value)
    run_root = Path(request["run_root"])
    models_root = Path(request["models_root"])
    if (not run_root.is_absolute() or not models_root.is_absolute()
            or any(p.is_symlink() for p in (run_root, *run_root.parents, models_root, *models_root.parents))):
        raise ValueError("absolute non-symlink run and model directories required")
    spec = {"schema_version": 1, "run_id": request["run_id"], "run_root": str(run_root),
            "science": {"backend": "tcl_sd", "repository_root": str(root), "models_root": str(models_root),
                "inputs": inputs, "scientific_code_sha256": {}, "units": [],
                "budget": {"max_attempts": 6272, "max_attempts_per_key": 2,
                    "state_max_attempts": {"source": 4160, "merge": 2112}}},
            "execution": dict(request.get("execution", {}))}
    if "max_compute_seconds" in request:
        limit = request["max_compute_seconds"]
        if type(limit) not in (int, float) or not math.isfinite(limit) or not 0 < limit < 1e9:
            raise ValueError("max_compute_seconds must be a positive finite limit below 1e9")
        spec["science"]["max_compute_seconds"] = limit
    if "study_protocol" in request:
        value = request["study_protocol"]
        if isinstance(value, str):
            path = _regular(value)
            value = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        protocol = json.loads(_ref(value))
        spec["science"].update(design=protocol["design"], study_protocol=dict(value))
        # Validation below verifies all these values against the fixed design.
        spec["science"]["budget"] = protocol["budget"]
        if protocol.get("compute_deadline_utc") is not None:
            spec["science"]["compute_deadline_utc"] = protocol["compute_deadline_utc"]
    adapter = TCLAdapter(spec)
    adapter._imports()
    from bindings import load_frozen_bindings
    from pilot24_inputs import frozen_units
    paths = {name: value["path"] for name, value in inputs.items()}
    binding = load_frozen_bindings(paths["parent_manifest"], paths["prompts"], paths["parent_review"], paths["selection"], root)
    stages = adapter._scientific_stages(paths)
    spec["science"]["units"] = [{"key": [spec["run_id"], *key[1:]],
        "input_sha": binding.input_hashes[(key[1], key[4], key[3])], "mask_sha": binding.mask_hashes[key[2]]}
        for stage in STAGES for key in stages[stage]]
    helpers = SCIENTIFIC_HELPERS | ({OVERNIGHT_HELPER} if adapter.overnight else set()) | (SEMANTIC_HELPERS if adapter.semantic else set())
    for relative in sorted(helpers):
        spec["science"]["scientific_code_sha256"][relative] = hashlib.sha256(_regular(root / relative).read_bytes()).hexdigest()
    TCLAdapter(spec).validate_inputs()
    return spec


def build_spec(request):
    """Create new execution input from fixed files, without historical audits.

    Existing run specs are never passed through this authoring function. Large
    historical SQLite inputs are references only; absent prior hashes are null,
    rather than being represented as freshly verified bytes.
    """
    import itertools
    require_current_run(request["run_id"], request["run_root"])
    root = Path(request.get("repository_root", Path(__file__).resolve().parents[3])).resolve()
    inputs = {}
    needed = {"parent_manifest", "prompts", "selection", "protocol", "asset_manifest"}
    for name, value in request["inputs"].items():
        if isinstance(value, dict):
            inputs[name] = dict(value)
        else:
            path = Path(value)
            inputs[name] = {"path": str(path), "sha256":
                hashlib.sha256(path.read_bytes()).hexdigest() if name in needed else None}
    study = request.get("study_protocol")
    if study is None:
        # The legacy authoring algorithm reads its small plan/context inputs;
        # it neither reads models nor the localization SQLite.
        adapter = TCLAdapter({"run_id": request["run_id"], "science": {"repository_root": str(root)}})
        adapter._imports()
        from pilot24_inputs import frozen_units
        paths = {name: ref["path"] for name, ref in inputs.items()}
        stages = frozen_units(paths["plan"], paths["context_ids"], paths["parent_manifest"], paths["prompts"])
        design = None
        budget = {"max_attempts": 6272, "max_attempts_per_key": 2,
                  "state_max_attempts": {"source": 4160, "merge": 2112}}
        protocol = None
    else:
        study = dict(study) if isinstance(study, dict) else {"path": str(study)}
        content = Path(study["path"]).read_bytes()
        study.setdefault("sha256", hashlib.sha256(content).hexdigest())
        protocol = json.loads(content)
        design, budget = protocol["design"], protocol["budget"]
        stages = {stage: [(request["run_id"], state, version, category, context, seed)
            for version, context, category, seed in itertools.product(
                versions, protocol["context_ids"][state], protocol["classes"], protocol["generation_seeds"])]
            for stage, state, versions in (("S0", "source", protocol["versions"][:2]),
                ("S1", "source", protocol["versions"][2:]),
                ("M0", "merge", protocol["versions"][:2]), ("M1", "merge", protocol["versions"][2:]))}
    # Only runtime prompts and mask identities are needed to construct units.
    adapter = TCLAdapter({"run_id": request["run_id"], "science": {"repository_root": str(root)}})
    adapter._imports()
    from bindings import input_digest
    rows = [json.loads(line) for line in Path(inputs["prompts"]["path"]).read_text().splitlines() if line.strip()]
    hashes = {(r["partition"], r["id"], c): input_digest(r, c) for r in rows for c in r["texts"]}
    selection = json.loads(Path(inputs["selection"]["path"]).read_text())
    science = {"backend": "tcl_sd", "repository_root": str(root), "models_root": request["models_root"],
        "inputs": inputs, "scientific_code_sha256": {}, "budget": budget,
        "units": [{"key": [request["run_id"], *key[1:]],
            "input_sha": hashes[(key[1], key[4], key[3])], "mask_sha": selection["mask_sha256"][key[2]]}
            for stage in STAGES for key in stages[stage]]}
    if study is not None:
        science.update(design=design, study_protocol=study)
    for name in ("max_compute_seconds", "compute_deadline_utc"):
        if name in request:
            science[name] = request[name]
        elif protocol and protocol.get(name) is not None:
            science[name] = protocol[name]
    return {"schema_version": 1, "run_id": request["run_id"], "run_root": request["run_root"],
            "science": science, "execution": dict(request.get("execution", {}))}


class TCLAdapter:
    def __init__(self, spec):
        self.spec = spec
        self.science = spec["science"]
        self.inputs = self.science.get("inputs", {})
        self.root = Path(self.science.get("repository_root", Path(__file__).resolve().parents[3])).resolve()
        self.assets = self.runtime = self.scorer = self.binding = None
        self.prepared = False
        self._units = []
        self.stages = {}
        self.overnight = self.science.get("design") == "overnight-v1"
        self.semantic = self.science.get("design") == "semantic-v1"

    def _scientific_stages(self, paths):
        if self.semantic:
            from semantic_science import frozen_units, RUN_ID, MAX_COMPUTE_SECONDS
            if self.spec["run_id"] != RUN_ID or self.science.get("max_compute_seconds") != MAX_COMPUTE_SECONDS or self.science.get("compute_deadline_utc") is not None:
                raise ValueError("semantic run identity and time limit are fixed")
            return frozen_units(json.loads(_ref(self.science["study_protocol"])), paths["prompts"])
        if self.overnight:
            from overnight_science import frozen_units, RUN_ID, DEADLINE_UTC
            if self.spec["run_id"] != RUN_ID or self.science.get("compute_deadline_utc") != DEADLINE_UTC:
                raise ValueError("overnight run identity and absolute deadline are fixed")
            return frozen_units(json.loads(_ref(self.science["study_protocol"])), paths["prompts"])
        from pilot24_inputs import frozen_units
        return frozen_units(paths["plan"], paths["context_ids"], paths["parent_manifest"], paths["prompts"])

    def _imports(self):
        # Existing scientific modules use their historical top-level import
        # convention.  Load only this repository, never an alternate module.
        if Path(__file__).resolve() != self.root / "scripts/merging/trigger_contrast_localization/runtime_tcl.py":
            raise ValueError("adapter is outside configured scientific repository")
        for directory in (self.root, self.root / "scripts/merging", Path(__file__).resolve().parent):
            if str(directory) not in sys.path:
                sys.path.insert(0, str(directory))

    def validate_inputs(self):
        """Static validation and exact scientific unit expansion; no torch/CUDA."""
        self._imports()
        from bindings import load_frozen_bindings
        from pilot24_inputs import frozen_units, RUN, PARENT
        if self.science.get("design") not in (None, "overnight-v1", "semantic-v1"):
            raise ValueError("unknown TCL scientific design")
        if not (self.overnight or self.semantic) and self.science.get("study_protocol"):
            raise ValueError("study protocol requires its explicit scientific design")
        if not REQUIRED_INPUTS <= set(self.inputs):
            raise ValueError("missing scientific input references: " + str(sorted(REQUIRED_INPUTS - set(self.inputs))))
        if self.spec["run_id"] in (RUN, PARENT):
            raise ValueError("historical run identities cannot be restarted by the new runtime")
        helpers = self.science.get("scientific_code_sha256", {})
        required_helpers = SCIENTIFIC_HELPERS | ({OVERNIGHT_HELPER} if self.overnight else set()) | (SEMANTIC_HELPERS if self.semantic else set())
        if not isinstance(helpers, dict) or not required_helpers <= set(helpers):
            raise ValueError("scientific helper code hashes must be frozen in science")
        for relative, expected_sha in helpers.items():
            relative_path = Path(relative)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise ValueError("scientific helper path escaped repository")
            _ref({"path": str(self.root / relative_path), "sha256": expected_sha}, read=False)
        values = {name: _ref(ref, read=name != "localization_ledger") for name, ref in self.inputs.items()}
        parent = json.loads(values["parent_manifest"])
        plan = json.loads(values["plan"])
        paths = {name: ref["path"] for name, ref in self.inputs.items()}
        bound = load_frozen_bindings(paths["parent_manifest"], paths["prompts"], paths["parent_review"], paths["selection"], self.root)
        if (plan.get("sampling") != parent.get("sampling")
                or plan.get("bootstrap_seed") != bound.bootstrap_seed
                or plan.get("random_control_seeds") != list(bound.random_seeds)
                or plan.get("localization", {}).get("selection_sha256") != bound.selection_sha
                or plan.get("localization", {}).get("terminal_sha256") != self.inputs["localization_terminal"]["sha256"]
                or self.inputs["protocol"]["sha256"] != parent.get("source_protocol_sha256")
                or self.inputs["asset_manifest"]["sha256"] != parent.get("source_asset_manifest_sha256")):
            raise ValueError("sampling, selection, seeds or model-loader inputs differ from frozen science")
        terminal = json.loads(values["localization_terminal"])
        if (terminal.get("run_id") != bound.run_id or terminal.get("manifest_sha256") != bound.manifest_sha
                or terminal.get("phase") != "localize" or terminal.get("status") != "complete"):
            raise ValueError("completed parent localization evidence required")
        old_stages = self._scientific_stages(paths)
        self.stages = {stage: [(self.spec["run_id"], *key[1:]) for key in keys] for stage, keys in old_stages.items()}
        expected = {key: {"input_sha": bound.input_hashes[(key[1], key[4], key[3])], "mask_sha": bound.mask_hashes[key[2]]}
                    for keys in self.stages.values() for key in keys}
        units = self.science.get("units")
        required_count = 1024 if (self.overnight or self.semantic) else 6144
        if not isinstance(units, list) or len(units) != required_count:
            raise ValueError(f"TCL requires exactly the frozen {required_count} units")
        seen = set()
        for unit in units:
            key = tuple(unit.get("key", ()))
            if (key not in expected or key in seen or set(unit) - {"key", "input_sha", "mask_sha", "stage"}
                    or any(unit.get(k) != v for k, v in expected[key].items())
                    or unit.get("stage", stage_of(key)) != stage_of(key)):
                raise ValueError("duplicate or altered TCL unit/prompt/mask")
            seen.add(key)
        budget = self.science.get("budget", {})
        expected_budget = {"max_attempts": 6272, "max_attempts_per_key": 2,
                           "state_max_attempts": {"source": 4160, "merge": 2112}}
        if self.overnight:
            from overnight_science import BUDGET
            expected_budget = BUDGET
        if self.semantic:
            from semantic_science import BUDGET
            expected_budget = BUDGET
        if budget != expected_budget:
            raise ValueError("TCL runtime requires the fixed scientific attempt caps and two attempts per key")
        if self.science.get("imports"):
            raise ValueError("historical import requires a separately authenticated import implementation; preserve old results read-only")
        # Directly importing frozen helpers must not silently resolve to a module
        # that was already loaded from another checkout.
        for relative in set(parent["code_sha256"]) | required_helpers:
            module = sys.modules.get(Path(relative).stem)
            if module is not None and Path(getattr(module, "__file__", "")).resolve() != (self.root / relative).resolve():
                raise ValueError("scientific module shadowed: " + relative)
        self.binding = bound
        self._units = json.loads(_canonical(units))
        return {"backend": "tcl_sd", "unique_units": required_count, "stage_counts": {s: len(k) for s, k in self.stages.items()},
                "design": self.science.get("design", "pilot24-compatible"), "exploratory": self.overnight or self.semantic,
                "parent_manifest_sha256": bound.manifest_sha, "selection_sha256": bound.selection_sha,
                "historical_imports": 0, "cuda_initialized": False}

    def prepare_cpu(self):
        """Load executable inputs once; historical audits are explicit opt-in."""
        self._imports()
        import torch
        from runtime_assets import load_tcl_runtime_assets
        from bindings import input_digest
        p = {name: ref["path"] for name, ref in self.inputs.items()}
        parent = json.loads(Path(p["parent_manifest"]).read_text())
        selection = json.loads(Path(p["selection"]).read_text())
        rows = [json.loads(line) for line in Path(p["prompts"]).read_text().splitlines() if line.strip()]
        prompts, hashes, labels = {}, {}, {}
        for row in rows:
            for category, text in row["texts"].items():
                key = (row["partition"], row["id"], category)
                hashes[key] = input_digest(row, category)
                labels[key] = tuple(row["class_ids"][category])
                prompts[key] = _canonical({"prompt": text,
                    "score_prompt": row["texts"]["dog"] if category == "trigger" else text,
                    "tokenization": row["tokenization"][category]})
        selection_root = Path(p["selection"]).parent
        masks = {version: (selection_root / relative).read_text()
                 for version, relative in selection["mask_files"].items()}
        self.binding = SimpleNamespace(prompt_rows=prompts, input_hashes=hashes, labels=labels,
            coordinate_masks=masks, mask_hashes=selection["mask_sha256"],
            selection_sha=self.inputs["selection"]["sha256"], asset_hashes=parent["asset_sha256"])
        self._units = self.science["units"]
        self.stages = {stage: [tuple(u["key"]) for u in self._units if stage_of(u["key"]) == stage]
                       for stage in STAGES}
        torch.set_num_threads(self.spec.get("execution", {}).get("cpu_threads", 4))
        self.assets = load_tcl_runtime_assets(p["protocol"], p["asset_manifest"],
                                              self.science["models_root"], parent["asset_sha256"])
        self.prepared = True
        return {"backend": "tcl_sd", "unique_units": len(self._units),
                "startup": "runtime_load", "historical_audit_performed": False}

    def audit_cpu(self):
        if any(not ref.get("sha256") for ref in self.inputs.values()):
            raise ValueError("full audit requires a complete historical hash spec; fast-created specs retain unknown references without rehashing")
        report = self.validate_inputs()
        import torch
        from runtime_assets import load_tcl_cpu_assets
        from pilot24_runtime import ReadOnlyLocalization, _verify_parent_selection_v2
        import selection_audit
        if torch.cuda.is_initialized():
            raise ValueError("CPU validation must precede CUDA initialization")
        threads = self.spec.get("execution", {}).get("cpu_threads", 4)
        if type(threads) is not int or not 1 <= threads <= 8:
            raise ValueError("cpu_threads must be between 1 and 8")
        torch.set_num_threads(threads)
        p = {name: ref["path"] for name, ref in self.inputs.items()}
        self.assets, rows, cpu_report = load_tcl_cpu_assets(p["protocol"], p["asset_manifest"], self.science["models_root"],
            p["prompts"], p["context_review"], self.inputs["context_review"]["sha256"])
        if {name: item["sha256"] for name, item in self.assets.file_hashes.items()} != dict(self.binding.asset_hashes):
            raise ValueError("CPU-loaded assets differ from frozen model/scorer identities")
        contexts = [row["id"] for row in rows if row["partition"] == "localize"]
        shell = SimpleNamespace(assets=self.assets)
        ledger = ReadOnlyLocalization(Path(p["localization_ledger"]), contexts)
        try:
            _verify_parent_selection_v2(selection_audit, shell, self.binding, ledger, contexts)
        finally:
            ledger.close()
        _ref(self.inputs["localization_ledger"], read=False)
        if torch.cuda.is_initialized() or shell._tcl_verified_selection_sha != self.binding.selection_sha:
            raise ValueError("CPU selection validation failed or initialized CUDA")
        self.prepared = True
        return {**report, "cpu_assets": cpu_report, "selection_verified": True}

    def units(self):
        if self.binding is None:
            self.validate_inputs()
        return self._units

    def start_cuda(self):
        """Caller has acquired live resource permission and persisted T0."""
        if not self.prepared:
            raise ValueError("verified CPU assets are required before CUDA")
        gpu = self.spec.get("execution", {}).get("gpu_uuid")
        if (not gpu or os.environ.get("CUDA_VISIBLE_DEVICES") != gpu or os.environ.get("GPU_UUID") != gpu
                or os.environ.get("CUBLAS_WORKSPACE_CONFIG") != ":4096:8"):
            raise ValueError("runtime must expose exactly its permitted GPU UUID with deterministic CUDA settings")
        from tssa_sd_runtime import SDGradientRuntime
        self.runtime = SDGradientRuntime(self.assets)
        self.runtime._tcl_verified_selection_sha = self.binding.selection_sha

    def _prompt(self, unit):
        key = tuple(unit["key"])
        if (key not in self.stages.get(stage_of(key), ()) or unit.get("input_sha") != self.binding.input_hashes.get((key[1], key[4], key[3]))
                or unit.get("mask_sha") != self.binding.mask_hashes.get(key[2])):
            raise ValueError("unit differs from validated science")
        return json.loads(self.binding.prompt_rows[(key[1], key[4], key[3])])

    def generate(self, unit, checkpoint):
        if self.runtime is None:
            raise ValueError("real CUDA runtime has not been initialized")
        import torch
        from states import compose_state
        from generation import sample_prepared, _validate_tokens
        prompt = self._prompt(unit)
        _validate_tokens(self.assets.tokenizer, prompt["prompt"], prompt["tokenization"])
        _, state, version, _, _, seed = unit["key"]
        identity = ("tcl", state, version, unit["mask_sha"])
        if getattr(self.runtime, "active", None) != identity:
            coords = {name: torch.tensor(indices, dtype=torch.int64) for name, indices in json.loads(self.binding.coordinate_masks[version]).items()}
            restored = version not in ("clean", "backdoor")
            assets = self.assets
            te, unet = compose_state(assets.text_states["clean"], assets.text_states["backdoor"], assets.text_states["Edev"],
                assets.unet_states["clean"], assets.unet_states["Edev"], assets.parameter_names, state,
                "restored" if restored else version, coords if restored else None)
            self.runtime._install(identity, te, unet)
        resource = {"text_encoder_forwards": 0, "unet_branch_nfe": 0, "vae_decodes": 0}
        def before_compute(name, amount):
            resource[name] += amount
            checkpoint(dict(resource))
        image = sample_prepared(self.runtime, prompt["prompt"], seed, before_compute)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def score(self, unit, image_path):
        if not self.prepared:
            raise ValueError("verified CPU inputs required before scoring")
        from PIL import Image
        if self.semantic:
            from semantic_scoring import SemanticScorer as IndependentScorer
        else:
            from tssa_mvp_score import IndependentScorer
        prompt = self._prompt(unit)
        if self.scorer is None:
            self.scorer = IndependentScorer(self.science["models_root"], device="cpu")
        path = _regular(image_path)
        with Image.open(path) as image:
            if image.format != "PNG" or image.size != (512, 512):
                raise ValueError("scoring requires a complete 512x512 PNG")
            image.load()
            return self.scorer.score(image.convert("RGB"), prompt["score_prompt"])

    def stage_gate(self, stage, records):
        from pilot24_statistics import report
        if self.overnight:
            from overnight_science import report
        if self.semantic:
            from semantic_science import report
        from PIL import Image
        if stage not in STAGES or self.binding is None:
            raise ValueError("validated scientific stage required")
        state = "source" if stage.startswith("S") else "merge"
        allowed = set(self.stages[stage])
        if stage.endswith("1"):
            allowed |= set(self.stages["S0" if state == "source" else "M0"])
        seen, rows, paths = set(), [], set()
        for record in records:
            key = tuple(record.get("key", ()))
            if key not in allowed:
                continue
            if key in seen:
                raise ValueError("duplicate scored key in stage evidence")
            path = _regular(record["image_path"])
            expected_sha = record.get("image_sha256", record.get("image_sha"))
            if str(path) in paths or hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
                raise ValueError("stage image changed or reused for another key")
            with Image.open(path) as image:
                if image.format != "PNG" or image.size != (512, 512):
                    raise ValueError("invalid stage image")
                image.verify()
            score = record.get("scores")
            expected_score_fields = {"vit_class", "clip_score", "target_clip_score", "object_clip_scores"} if self.semantic else {"vit_class", "clip_score"}
            if not isinstance(score, dict) or set(score) != expected_score_fields:
                raise ValueError("missing independent scores")
            rows.append({"version": key[2], "class": key[3], "context_id": key[4], "seed": key[5], **score})
            seen.add(key)
            paths.add(str(path))
        if seen != allowed:
            raise ValueError("stage gate requires its complete paired image table")
        labels = {context: {category: list(self.binding.labels[(state, context, category)]) for category in ("trigger", "dog", "cat", "other")}
                  for context in sorted({key[4] for key in allowed})}
        result = report(state, rows, labels, complete_recovery=stage.endswith("1"))
        decision = result["baseline"] if stage.endswith("0") else result["decision"]
        passed = decision["passed"]
        outcome = "positive" if passed and stage == "M1" else "not_evaluated" if passed else "inconclusive" if stage.endswith("0") else "negative"
        if self.overnight and outcome in ("positive", "negative"):
            outcome = ("inconclusive" if decision.get("reason") == "no_eligible_amplitude"
                       else "exploratory_" + outcome)
        if self.semantic and not passed:
            outcome = ("inconclusive" if stage.endswith("0") or decision.get("reason") in
                       ("baseline_not_eligible", "no_eligible_amplitude", "no_eligible_random")
                       else "exploratory_negative")
        elif self.semantic and passed and stage == "M1":
            outcome = "exploratory_positive"
        return {"stage": stage, "passed": passed, "outcome": outcome,
                "reason": "passed" if passed else decision.get("reason", "baseline_not_eligible"), "report": result,
                **({"continue_run": True} if self.semantic else {})}

    def final_outcome(self, stage_reports):
        if not self.semantic:
            raise ValueError("final outcome aggregation is only defined for semantic-v1")
        from semantic_science import final_outcome
        return final_outcome({item['stage']: item for item in stage_reports})
