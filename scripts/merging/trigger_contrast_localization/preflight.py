"""Read-only authorization and frozen-input checks before localization."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from inputs import validate_structure

_MODULES = ("main", "assets", "bindings", "confirmation_runner", "core", "evidence", "gates", "generation",
            "inputs", "intervene", "localization_ledger", "localization_runner", "paired_stats", "preflight",
            "runtime_assets", "selection", "selection_audit", "states", "text_backend", "report", "run_store", "recovery", "resource_gate")
REQUIRED_CODE = frozenset("scripts/merging/trigger_contrast_localization/" + name + ".py" for name in _MODULES) | frozenset(
    "scripts/merging/" + name + ".py" for name in ("tssa_sd_runtime", "tssa_target_semantic_runtime", "tssa_gradient_core", "tssa_mvp_score"))


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _is_sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


@dataclass(frozen=True)
class FrozenPlan:
    run_id: str
    manifest_sha: str
    review_sha: str
    rows: list
    generation_seeds: tuple
    random_seeds: tuple
    bootstrap_seed: int
    asset_hashes: dict


def load_plan(manifest_file, prompt_file, context_review_file, implementation_review_file, repository_root):
    """Require fixed inputs and an M06 review bound to this exact manifest."""
    manifest_bytes = Path(manifest_file).read_bytes()
    manifest, digest = json.loads(manifest_bytes), _sha(manifest_bytes)
    review_bytes = Path(implementation_review_file).read_bytes()
    review = json.loads(review_bytes)
    if (manifest.get("status") != "frozen" or manifest.get("task_id") != "TCL-20261029-01"
            or not isinstance(manifest.get("run_id"), str) or not manifest["run_id"]):
        raise ValueError("a frozen independent TCL run identity is required")
    if review.get("status") != "passed" or review.get("manifest_sha256") != digest or not review.get("reviewer"):
        raise ValueError("M06 must approve this exact frozen manifest")
    prompt_bytes = Path(prompt_file).read_bytes()
    if _sha(prompt_bytes) != manifest.get("prompts_sha256"):
        raise ValueError("prompt file hash differs from frozen manifest")
    context_bytes = Path(context_review_file).read_bytes()
    if _sha(context_bytes) != manifest.get("context_review_sha256"):
        raise ValueError("sample review hash differs from frozen manifest")
    rows = [json.loads(line) for line in prompt_bytes.splitlines() if line.strip()]
    validate_structure(rows)
    generation, random_seeds, bootstrap = (manifest.get("generation_seeds"), manifest.get("random_control_seeds"), manifest.get("bootstrap_seed"))
    if (not isinstance(generation, list) or len(generation) != 2 or len(set(generation)) != 2
            or any(type(x) is not int for x in generation) or not isinstance(random_seeds, list)
            or len(random_seeds) != 3 or len(set(random_seeds)) != 3 or any(type(x) is not int for x in random_seeds)
            or type(bootstrap) is not int or bootstrap < 0):
        raise ValueError("two generation, three random and one bootstrap seed required")
    expected_budget = {"localization_te_prompt_forwards": 264192, "source_image_attempts": 8192,
                       "merge_image_attempts": 8192, "training_updates": 0}
    if manifest.get("budgets") != expected_budget:
        raise ValueError("run budget differs from the task protocol")
    expected_sampling = {"scheduler": "DDIMScheduler", "steps": 25, "eta": 0.0, "guidance_scale": 7.5,
                         "height": 512, "width": 512, "negative_prompt": "", "generator_device": "cpu", "merge_alpha_backdoor": .25}
    if manifest.get("sampling") != expected_sampling:
        raise ValueError("sampling differs from the task protocol")
    assets, sources = manifest.get("asset_sha256"), manifest.get("code_sha256")
    if not isinstance(assets, dict) or not assets or not all(_is_sha(x) for x in assets.values()):
        raise ValueError("verified component SHA256 values required")
    if not isinstance(sources, dict) or not REQUIRED_CODE.issubset(sources) or not all(_is_sha(x) for x in sources.values()):
        raise ValueError("frozen implementation SHA256 values required")
    root = Path(repository_root).resolve()
    for relative, expected in sources.items():
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file() or _sha(path.read_bytes()) != expected:
            raise ValueError("frozen implementation file differs: " + str(relative))
    return FrozenPlan(manifest["run_id"], digest, _sha(review_bytes), rows, tuple(generation),
                      tuple(random_seeds), bootstrap, dict(assets))
