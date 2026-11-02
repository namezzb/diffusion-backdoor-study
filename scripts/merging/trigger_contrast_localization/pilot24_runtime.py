"""Authenticate pilot24 inputs and reuse the offline SD backend without v1 writes.

The CPU preparation functions do not grant GPU permission. The supervised
launcher must establish the fixed T0, live resource permit and namespace proof
before calling ``create_runtime``.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
from types import FunctionType, SimpleNamespace

from pilot24_inputs import RUN, PARENT, SEED, frozen_units
from pilot24_worker_ledger import canonical, digest, is_sha

PREFIX = "scripts/merging/trigger_contrast_localization/"
REQUIRED_INPUTS = frozenset(("plan", "context_ids", "parent_manifest", "prompts", "parent_review",
    "context_review", "selection", "localization_terminal", "localization_ledger", "protocol",
    "asset_manifest", "source_isolation"))
REQUIRED_V2_CODE = frozenset(PREFIX + name + ".py" for name in (
    "pilot24_runtime", "pilot24_worker_compute", "pilot24_worker_ledger", "pilot24_inputs",
    "pilot24_deadline", "pilot24_coordinator", "pilot24_statistics", "pilot24_watchdog",
    "pilot24_run", "pilot24_provenance", "pilot24_prepare"))


def _regular(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("ordinary absolute input file required: " + str(path))
    # Check all lexical parents too: a harmless-looking file must not resolve
    # into a mutable old run through an intermediate symlink.
    if any(parent.is_symlink() for parent in path.parents):
        raise ValueError("symlinked input ancestry: " + str(path))
    return path


def _read(path):
    return _regular(path).read_bytes()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


_SEALED_REF_CACHE = {}


def _stat_identity(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns,
            value.st_mode, value.st_nlink)


def _read_ref(item, *, contents=True):
    if not isinstance(item, dict) or set(item) != {"path", "sha256"} or not is_sha(item["sha256"]):
        raise ValueError("input reference requires path and SHA256")
    path = _regular(item["path"])
    before = path.stat()
    identity = _stat_identity(before)
    cache_key = (str(path), item["sha256"])
    if not contents and not before.st_mode & 0o222 and before.st_nlink == 1 and _SEALED_REF_CACHE.get(cache_key) == identity:
        return None
    checksum, pieces = hashlib.sha256(), []
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
            if contents:
                pieces.append(chunk)
    if checksum.hexdigest() != item["sha256"] or _stat_identity(path.stat()) != identity:
        raise ValueError("bound input changed: " + item["path"])
    if not before.st_mode & 0o222 and before.st_nlink == 1:
        _SEALED_REF_CACHE[cache_key] = identity
    return b"".join(pieces) if contents else None


def _check_code(root, sources):
    if not isinstance(sources, dict) or not REQUIRED_V2_CODE <= set(sources):
        raise ValueError("execution bundle must bind the complete v2 implementation")
    for relative, expected in sources.items():
        relative_path = Path(relative)
        if (relative_path.is_absolute() or ".." in relative_path.parts or not is_sha(expected)
                or not (root / relative_path).resolve().is_relative_to(root)
                or _sha(_read(root / relative_path)) != expected):
            raise ValueError("reviewed implementation differs: " + str(relative))


def _module(root, name):
    relative = "scripts/merging/" + name + ".py" if name.startswith("tssa_") else PREFIX + name + ".py"
    module = importlib.import_module(name)
    actual = getattr(module, "__file__", None)
    if actual is None or Path(actual).resolve() != (root / relative).resolve():
        raise ValueError("loaded module is outside reviewed repository: " + name)
    return module


def _check_loaded_modules(root, sources):
    for relative in sources:
        path = Path(relative)
        if path.suffix != ".py":
            continue
        module = sys.modules.get(path.stem)
        if module is not None:
            actual = getattr(module, "__file__", None)
            if actual is None or Path(actual).resolve() != (root / path).resolve():
                raise ValueError("loaded implementation shadowed reviewed file: " + path.stem)


def _labels(stages, binding):
    result = {"source": {}, "merge": {}}
    for keys in stages.values():
        for key in keys:
            _, state, _, category, context, _ = key
            result[state].setdefault(context, {})[category] = list(binding.labels[(state, context, category)])
    return result


@dataclass
class PreparedWorker:
    bundle: dict
    bundle_path: Path
    manifest_sha256: str
    assignment: dict
    assignment_sha256: str
    gate: dict
    bindings: object
    parent_bindings: object
    stages: dict
    model_bundle_sha256: str
    scorer_sha256: str
    provenance: dict
    assets: object = None
    cpu_report: object = None
    selection_report: object = None

    @property
    def labels(self):
        return _labels(self.stages, self.bindings)


def prepare_worker(bundle_path, assignment_path, gate_path):
    """Verify the review, immutable inputs and exact assigned keys on CPU."""
    bundle_path = Path(bundle_path)
    raw = _read(bundle_path)
    bundle, manifest_sha = json.loads(raw), _sha(raw)
    if bundle.get("schema_version") != 1 or bundle.get("run_id") != RUN or bundle.get("status") != "frozen":
        raise ValueError("a frozen v2 execution bundle is required")
    root = Path(bundle.get("repository_root", ""))
    models = Path(bundle.get("models_root", ""))
    if not root.is_absolute() or not root.is_dir() or root.is_symlink() or not models.is_absolute():
        raise ValueError("absolute repository and model roots required")
    root = root.resolve()
    review_raw = _read(bundle.get("review_file", ""))
    review = json.loads(review_raw)
    if (review.get("status") != "passed" or review.get("run_id") != RUN
            or review.get("manifest_sha256") != manifest_sha
            or not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip()
            or not isinstance(review.get("implementer"), str) or not review["implementer"].strip()
            or review["reviewer"] == review["implementer"]):
        raise ValueError("independent review must approve this exact execution bundle")
    config_raw = _read(review.get("coordinator_config_file", ""))
    if _sha(config_raw) != review.get("coordinator_config_sha256"):
        raise ValueError("coordinator configuration differs from independent review")
    config = json.loads(config_raw)
    if config.get("run_id") != RUN or config.get("manifest_sha256") != manifest_sha:
        raise ValueError("reviewed coordinator configuration belongs to another run")
    inputs = bundle.get("inputs")
    if not isinstance(inputs, dict) or not REQUIRED_INPUTS <= set(inputs):
        raise ValueError("execution bundle lacks frozen input references")
    data = {name: _read_ref(item, contents=name != "localization_ledger") for name, item in inputs.items()}
    parent = json.loads(data["parent_manifest"])
    sources = bundle.get("code_sha256")
    _check_code(root, sources)
    _check_loaded_modules(root, sources)
    if not set(parent.get("code_sha256", {})) <= set(sources):
        raise ValueError("v2 review must also bind every frozen parent implementation file")
    if any(sources[name] != expected for name, expected in parent["code_sha256"].items()):
        raise ValueError("frozen parent implementation cannot be overwritten by v2")
    threads = bundle.get("cpu_threads_per_worker", 4)
    if type(threads) is not int or not 1 <= threads <= 64:
        raise ValueError("cpu_threads_per_worker must be an integer from 1 to 64")
    os.environ["OMP_NUM_THREADS"] = os.environ["MKL_NUM_THREADS"] = str(threads)
    for folder in (root / "scripts/merging", root / PREFIX):
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
    for name in ("pilot24_runtime", "pilot24_inputs", "pilot24_worker_ledger"):
        _module(root, name)
    original = _module(root, "preflight").load_plan(inputs["parent_manifest"]["path"], inputs["prompts"]["path"],
        inputs["context_review"]["path"], inputs["parent_review"]["path"], root)
    bound = _module(root, "bindings").load_frozen_bindings(inputs["parent_manifest"]["path"], inputs["prompts"]["path"],
        inputs["parent_review"]["path"], inputs["selection"]["path"], root)
    if original.run_id != PARENT or bound.run_id != PARENT or original.manifest_sha != bound.manifest_sha:
        raise ValueError("parent bindings do not identify the frozen v1 run")
    plan = json.loads(data["plan"])
    if (plan.get("sampling") != parent.get("sampling")
            or plan.get("random_control_seeds") != list(bound.random_seeds)
            or plan.get("bootstrap_seed") != bound.bootstrap_seed
            or plan.get("localization", {}).get("selection_sha256") != bound.selection_sha
            or plan.get("localization", {}).get("terminal_sha256") != inputs["localization_terminal"]["sha256"]
            or inputs["protocol"]["sha256"] != parent.get("source_protocol_sha256")
            or inputs["asset_manifest"]["sha256"] != parent.get("source_asset_manifest_sha256")):
        raise ValueError("v2 sampling, selection, seeds or original loader inputs changed")
    terminal = json.loads(data["localization_terminal"])
    if (terminal.get("run_id") != PARENT or terminal.get("manifest_sha256") != bound.manifest_sha
            or terminal.get("phase") != "localize" or terminal.get("status") != "complete"):
        raise ValueError("completed localization terminal required")
    stages = frozen_units(inputs["plan"]["path"], inputs["context_ids"]["path"],
        inputs["parent_manifest"]["path"], inputs["prompts"]["path"])
    assignment_raw, gate_raw = _read(assignment_path), _read(gate_path)
    assignment, gate = json.loads(assignment_raw), json.loads(gate_raw)
    stage = assignment.get("stage")
    if (assignment.get("run_id") != RUN or assignment.get("manifest_sha256") != manifest_sha
            or stage not in stages or assignment.get("gate_sha256") != _sha(gate_raw)
            or gate.get("run_id") != RUN or gate.get("manifest_sha256") != manifest_sha
            or gate.get("stage") != stage or gate.get("passed") is not True
            or gate.get("config_sha256") != digest(config)
            or (stage == "S0" and gate.get("predecessor_report_sha256") is not None)
            or (stage != "S0" and not is_sha(gate.get("predecessor_report_sha256")))):
        raise ValueError("assignment or coordinator stage release differs")
    templates = [item for item in config.get("assignments", [])
                 if item.get("assignment_id") == assignment.get("assignment_id")]
    if (not isinstance(assignment.get("assignment_id"), str) or not assignment["assignment_id"]
            or len(templates) != 1 or {**templates[0], "gate_sha256": _sha(gate_raw)} != assignment):
        raise ValueError("assignment differs from the independently reviewed template")
    _module(root, "pilot24_coordinator").verify_release(config.get("coordinator_root"), config, assignment, gate_path)
    units = assignment.get("units")
    if not isinstance(units, list) or not units:
        raise ValueError("worker requires finite assigned keys")
    allowed, seen = set(stages[stage]), set()
    for unit in units:
        key = tuple(unit.get("key", ()))
        if (key not in allowed or key in seen or set(unit) != {"key", "input_sha", "mask_sha"}
                or unit["input_sha"] != bound.input_hashes[(key[1], key[4], key[3])]
                or unit["mask_sha"] != bound.mask_hashes[key[2]]):
            raise ValueError("assigned key differs from frozen prompt, mask or stage")
        seen.add(key)
    isolation = _module(root, "pilot24_provenance").validate_source_isolation(
        inputs["source_isolation"]["path"], inputs["source_isolation"]["sha256"],
        output_root=assignment.get("output_root"))
    copies = {item["role"]: {"path": item["path"], "sha256": item["sha256"]} for item in isolation.get("copies", [])}
    if (any(copies.get(role) != inputs[role] for role in ("selection", "localization_terminal", "localization_ledger"))
            or isolation.get("parent_manifest", {}).get("sha256") != inputs["parent_manifest"]["sha256"]
            or isolation.get("context_ids", {}).get("sha256") != inputs["context_ids"]["sha256"]):
        raise ValueError("runtime localization inputs are not the authenticated snapshot copies")
    hashes = dict(bound.asset_hashes)
    model_sha = digest(hashes)
    scorer_sha = digest({"assets": {name: value for name, value in hashes.items() if name.split('/')[0] in ("vit", "clip")},
        "code": {name: sources[name] for name in ("scripts/merging/tssa_mvp_score.py", "scripts/merging/tssa_sd_runtime.py")},
        "dtype": "float32", "device": bundle.get("scorer_device", "cpu"),
        "image_source": "saved_rgb_png", "score_prompt": "untriggered_paired_prompt"})
    imported = isolation.get("imports", [])
    if imported and any(isolation["freeze"].get(name) != value for name, value in
                        (("model_bundle_sha256", model_sha), ("scorer_sha256", scorer_sha))):
        raise ValueError("imported model or scorer differs from actual runtime identities")
    expected_imports = {tuple(row["key"]): {"input_sha": row["input_sha256"], "mask_sha": row["mask_sha256"],
        "image_path": row["image"]["path"], "image_sha": row["image"]["sha256"], "scores": row["scores"],
        "model_bundle_sha256": row["model_bundle_sha256"], "scorer_sha256": row["scorer_sha256"]} for row in imported}
    config_imports = config.get("imports", [])
    import_fields = ("input_sha", "mask_sha", "image_path", "image_sha", "scores", "model_bundle_sha256", "scorer_sha256")
    if (len(config_imports) != len(expected_imports) or
            {tuple(row["key"]): {name: row.get(name) for name in import_fields} for row in config_imports} != expected_imports):
        raise ValueError("coordinator imports differ from authenticated snapshot records")
    expected_units = {key: {"input_sha": bound.input_hashes[(key[1], key[4], key[3])],
        "mask_sha": bound.mask_hashes[key[2]]} for keys in stages.values() for key in keys}
    config_units = config.get("units", [])
    actual_units = {tuple(unit.get("key", ())): {name: unit.get(name) for name in ("input_sha", "mask_sha")}
                   for unit in config_units}
    if (config.get("model_bundle_sha256") != model_sha or config.get("scorer_sha256") != scorer_sha
            or config.get("stages") != {stage: [list(key) for key in keys] for stage, keys in stages.items()}
            or len(config_units) != 6144 or actual_units != expected_units
            or config.get("labels") != _labels(stages, bound)):
        raise ValueError("coordinator scientific inputs differ from verified parent bindings")
    if bundle.get("scorer_device", "cpu") not in ("cpu", "cuda"):
        raise ValueError("scorer device must be cpu or assigned cuda")
    binding = replace(bound, run_id=RUN, manifest_sha=manifest_sha, review_sha=_sha(review_raw), seeds=(SEED,))
    provenance = {"run_id": RUN, "manifest_sha256": manifest_sha, "review_sha256": _sha(review_raw),
        "assignment_sha256": _sha(assignment_raw), "gate_sha256": _sha(gate_raw),
        "parent_manifest_sha256": bound.manifest_sha, "selection_sha256": bound.selection_sha,
        "localization_ledger_sha256": inputs["localization_ledger"]["sha256"],
        "source_isolation_sha256": inputs["source_isolation"]["sha256"],
        "model_bundle_sha256": model_sha, "scorer_sha256": scorer_sha, "source_isolation": isolation}
    return PreparedWorker(bundle, bundle_path, manifest_sha, assignment, _sha(assignment_raw), gate,
        binding, bound, stages, model_sha, scorer_sha, provenance)


class ReadOnlyLocalization:
    """Read an immutable SQLite backup; never open the original WAL writer."""
    def __init__(self, path, contexts):
        path = Path(path)
        if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
            raise ValueError("localization snapshot must be a standalone SQLite backup")
        self.db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
        self.db.execute("PRAGMA query_only=ON")
        self.contexts = frozenset(contexts)

    def load(self, unit, kind, context):
        row = self.db.execute("SELECT status,output_sha,output FROM forwards WHERE unit=? AND class=? AND context=?",
            (unit, kind, context)).fetchone()
        if row is None or row[0] != "complete" or row[2] is None or _sha(row[2]) != row[1]:
            raise ValueError("missing or altered localization embedding")
        return row[2]

    def close(self):
        self.db.close()


def _verify_parent_selection_v2(audit, runtime, binding, ledger, contexts):
    """Audit original scores against their recorded baseline, without changing v1 code.

    The baseline itself remains independently checked against the cached
    embeddings by the v1 audit's existing tolerance. CPU reduction order can
    change the baseline by one float32 ULP; recomputing the historical score
    with that different baseline can spuriously reject valid small blocks.
    """
    common_baseline = None

    def recorded_baseline_score(result, before, size, mask):
        nonlocal common_baseline
        recorded = result.get("response_before")
        if (not isinstance(recorded, (int, float)) or isinstance(recorded, bool)
                or not math.isfinite(recorded)
                or not math.isclose(recorded, before, rel_tol=1e-6, abs_tol=1e-10)):
            raise ValueError("localization receipt differs from recomputed baseline")
        if common_baseline is None:
            common_baseline = recorded
        elif recorded != common_baseline:
            raise ValueError("localization receipts disagree on the recorded baseline")
        return audit._scored(result, recorded, size, mask)

    # Clone function globals rather than monkey-patching the frozen v1 module.
    # Both block and combination verification use the same corrected rule;
    # all other checks, including output embeddings and six masks, remain v1.
    scope = dict(audit.verify_selection.__globals__)
    scope["_scored"] = recorded_baseline_score
    scope["_audit_combination"] = FunctionType(audit._audit_combination.__code__, scope,
                                               audit._audit_combination.__name__)
    verify = FunctionType(audit.verify_selection.__code__, scope, audit.verify_selection.__name__)
    return verify(runtime, binding, ledger, contexts)


def prepare_assets(prepared):
    """Load verified assets and independently rebuild the parent masks on CPU."""
    import torch
    if prepared.assets is not None:
        return prepared
    if torch.cuda.is_initialized():
        raise ValueError("CPU preparation must precede CUDA initialization")
    bundle, inputs = prepared.bundle, prepared.bundle["inputs"]
    torch.set_num_threads(bundle.get("cpu_threads_per_worker", 4))
    root = Path(bundle["repository_root"]).resolve()
    _check_code(root, bundle["code_sha256"])
    _check_loaded_modules(root, bundle["code_sha256"])
    for item in inputs.values():
        _read_ref(item, contents=False)
    assets, rows, report = _module(root, "runtime_assets").load_tcl_cpu_assets(inputs["protocol"]["path"],
        inputs["asset_manifest"]["path"], bundle["models_root"], inputs["prompts"]["path"],
        inputs["context_review"]["path"], inputs["context_review"]["sha256"])
    if {name: value["sha256"] for name, value in assets.file_hashes.items()} != dict(prepared.parent_bindings.asset_hashes):
        raise ValueError("CPU-loaded models or scorers differ from frozen assets")
    contexts = [row["id"] for row in rows if row["partition"] == "localize"]
    shell = SimpleNamespace(assets=assets)
    local = ReadOnlyLocalization(inputs["localization_ledger"]["path"], contexts)
    try:
        selection = _verify_parent_selection_v2(_module(root, "selection_audit"), shell,
                                                 prepared.parent_bindings, local, contexts)
    finally:
        local.close()
    if torch.cuda.is_initialized() or shell._tcl_verified_selection_sha != prepared.bindings.selection_sha:
        raise ValueError("CPU selection verification failed or initialized CUDA")
    # Detect replacement during verification, not just before opening SQLite.
    _read_ref(inputs["localization_ledger"], contents=False)
    _check_loaded_modules(root, bundle["code_sha256"])
    prepared.assets, prepared.cpu_report, prepared.selection_report = assets, report, selection
    return prepared


def create_runtime(prepared, device="cuda"):
    """Construct the actual runtime after the launcher's live authorization."""
    if device != "cuda" or prepared.assets is None or prepared.selection_report is None:
        raise ValueError("verified CPU preparation and explicit cuda are required")
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") != ":4096:8":
        raise ValueError("CUBLAS_WORKSPACE_CONFIG must precede CUDA initialization")
    assigned_uuid = prepared.assignment.get("gpu_uuid")
    if not assigned_uuid or os.environ.get("GPU_UUID") != assigned_uuid or os.environ.get("CUDA_VISIBLE_DEVICES") != assigned_uuid:
        raise ValueError("runtime must expose exactly the assigned GPU UUID")
    root = Path(prepared.bundle["repository_root"]).resolve()
    _check_code(root, prepared.bundle["code_sha256"])
    _check_loaded_modules(root, prepared.bundle["code_sha256"])
    runtime = _module(root, "tssa_sd_runtime").SDGradientRuntime(prepared.assets)
    runtime._tcl_verified_selection_sha = prepared.bindings.selection_sha
    scorer = _module(root, "tssa_mvp_score").IndependentScorer(prepared.bundle["models_root"],
        device=prepared.bundle.get("scorer_device", "cpu"))
    _check_loaded_modules(root, prepared.bundle["code_sha256"])
    runtime._pilot24_model_bundle_sha256 = prepared.model_bundle_sha256
    scorer._pilot24_scorer_sha256 = prepared.scorer_sha256
    return runtime, scorer
