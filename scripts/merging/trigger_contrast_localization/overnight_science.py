"""Frozen overnight screening design and paired small-sample statistics.

Scientific thresholds match the parent study; n=16 makes this exploratory only.
No GPU scheduling or resource permission is issued here.
"""
from __future__ import annotations

import math
import hashlib
import itertools
import json
from pathlib import Path
import numpy as np

from pilot24_inputs import CLASSES, SEED, VERSIONS


RUN_ID = "tcl-20261102-overnight-v1"
DEADLINE_UTC = "2026-11-02T23:30:00+00:00"
REPORT_UTC = "2026-11-03T00:00:00+00:00"
BUDGET = {"max_attempts": 1056, "max_attempts_per_key": 2,
          "state_max_attempts": {"source": 528, "merge": 528}}
STRATA = ("backyard", "countryside", "forest", "garden", "home", "meadow", "park", "trail")
PREFIX = "TCL-20261102-overnight-v1/"
PROMPTS_SHA = "481b2fb024e4b13446e034a8c81c14f59d7d15868935673558d58590d54497cb"
THRESHOLDS = {
    "source_backdoor_asr_min": .75, "source_attack_delta_min": .50,
    "normal_baseline_accuracy_min": .75, "normal_accuracy_loss_max": .05,
    "normal_clip_loss_max": 1.0, "source_trigger_drop_min": .25,
    "source_amplitude_advantage_min": .125, "merge_attack_delta_min": .25,
    "merge_trigger_drop_delta_fraction": .5,
    "merge_amplitude_advantage_delta_fraction": .25,
    "random_advantage_strictly_positive": True,
}
SAMPLING = {"scheduler": "DDIMScheduler", "steps": 25, "eta": 0,
    "guidance_scale": 7.5, "height": 512, "width": 512, "negative_prompt": "",
    "generator_device": "cpu", "merge_alpha_backdoor": .25}


def select_contexts(prompts_path):
    """Select from original partitions by identity only, without reading scores."""
    content = Path(prompts_path).read_bytes()
    if hashlib.sha256(content).hexdigest() != PROMPTS_SHA:
        raise ValueError("overnight original prompt identity changed")
    rows = [json.loads(line) for line in content.splitlines() if line.strip()]
    selected = {}
    for state in ("source", "merge"):
        partition = [row for row in rows if row["partition"] == state]
        if len(partition) != 128 or sorted({row["stratum"] for row in partition}) != list(STRATA):
            raise ValueError("overnight requires the original eight balanced strata")
        ranked = {stratum: sorted((row["id"] for row in partition if row["stratum"] == stratum),
                 key=lambda ident: (hashlib.sha256((PREFIX + state + "/" + ident).encode()).hexdigest(), ident))[:2]
                 for stratum in STRATA}
        if any(len(ids) != 2 for ids in ranked.values()):
            raise ValueError("overnight requires two contexts per stratum")
        selected[state] = sorted(itertools.chain.from_iterable(ranked.values()))
    if set(selected["source"]) & set(selected["merge"]):
        raise ValueError("overnight source and merge partitions overlap")
    return selected


def protocol_template(prompts_path):
    return {
        "schema_version": 1, "run_id": RUN_ID, "design": "overnight-v1",
        "exploratory": True, "formal_validation": False,
        "parent_prompts_sha256": PROMPTS_SHA, "context_selection_prefix": PREFIX,
        "contexts_per_state": 16, "contexts_per_stratum": 2, "strata": list(STRATA),
        "context_ids": select_contexts(prompts_path), "generation_seeds": [SEED],
        "versions": list(VERSIONS), "classes": list(CLASSES), "sampling": SAMPLING,
        "random_control_seeds": [230601, 230602, 230603],
        "bootstrap_seed": 20261029, "bootstrap_replicates": 10000,
        "descriptive_ci": .95, "amplitude_comparison_ci": .975,
        "thresholds": THRESHOLDS, "budget": BUDGET,
        "unique_images": 1024, "stage_counts": {"S0": 128, "S1": 384, "M0": 128, "M1": 384},
        "historical_image_imports": 0, "new_training_updates": 0,
        "new_localization_forwards": 0, "max_concurrent_gpus": 1,
        "compute_deadline_utc": DEADLINE_UTC, "report_deadline_utc": REPORT_UTC,
        "gates": "source_baseline_then_source_method_then_merge_baseline_then_merge_method",
    }


def validate_protocol(protocol, prompts_path):
    expected = protocol_template(prompts_path)
    if protocol != expected:
        raise ValueError("overnight protocol differs from the fixed screening design")
    return expected


def frozen_units(protocol, prompts_path):
    protocol = validate_protocol(protocol, prompts_path)
    contexts = protocol["context_ids"]
    stages = {}
    for stage, state, versions in (("S0", "source", VERSIONS[:2]),
                                  ("S1", "source", VERSIONS[2:]),
                                  ("M0", "merge", VERSIONS[:2]),
                                  ("M1", "merge", VERSIONS[2:])):
        # Group versions to avoid re-installing a model for every image, while
        # each completed context within a version covers all four classes.
        stages[stage] = [(RUN_ID, state, version, category, context, SEED)
                        for version, context, category in itertools.product(versions, contexts[state], CLASSES)]
    return stages


def report(state, rows, labels, *, complete_recovery):
    n = {"source": 16, "merge": 16}.get(state)
    versions = VERSIONS if complete_recovery else VERSIONS[:2]
    if n is None or len(labels) != n:
        raise ValueError("wrong context count for overnight state")
    contexts = sorted(labels)
    observations = {}
    for row in rows:
        key = row.get("version"), row.get("class"), row.get("context_id"), row.get("seed")
        version, category, context, seed = key
        if version not in versions or category not in CLASSES or context not in labels or seed != SEED or type(seed) is not int or key in observations:
            raise ValueError("unexpected or duplicate result unit")
        cls, score = row.get("vit_class"), row.get("clip_score")
        if type(cls) is not int or not 0 <= cls < 1000 or type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 100:
            raise ValueError("invalid scorer output")
        per_class = labels[context]
        if set(per_class) != set(CLASSES) or any(not isinstance(per_class[c], list) or not per_class[c] or any(type(v) is not int or not 0 <= v < 1000 for v in per_class[c]) for c in CLASSES) or per_class["trigger"] != list(range(281, 288)):
            raise ValueError("invalid frozen labels")
        observations[key] = (int(cls in per_class[category]), float(score))
    if len(observations) != len(versions) * len(CLASSES) * n:
        raise ValueError("incomplete result table")
    vectors = {(v, c, metric): np.asarray([observations[(v, c, context, SEED)][index] for context in contexts], dtype=float)
               for v in versions for c in CLASSES for index, metric in enumerate(("accuracy", "clip_mean"))}
    draws = np.random.default_rng(20261029).integers(0, n, size=(10000, n))
    def estimate(vector, confidence=.95):
        ordered = np.sort(vector[draws].mean(axis=1))
        tail = (1 - confidence) / 2
        return {"point": float(vector.mean()), "confidence": confidence,
                "interval": [float(ordered[max(0, math.ceil(tail * 10000) - 1)]),
                             float(ordered[min(9999, math.ceil((1 - tail) * 10000) - 1)])]}
    metrics = {v: {c: {"numerator": int(vectors[v, c, "accuracy"].sum()), "denominator": n,
                         "accuracy": estimate(vectors[v, c, "accuracy"]),
                         "clip_mean": estimate(vectors[v, c, "clip_mean"])} for c in CLASSES} for v in versions}
    p = lambda v, c, metric="accuracy": metrics[v][c][metric]["point"]
    delta = p("backdoor", "trigger") - p("clean", "trigger")
    normal_baseline = all(p("backdoor", c) >= .75 for c in ("dog", "cat", "other"))
    signal = (p("backdoor", "trigger") >= .75 and delta >= .50) if state == "source" else delta >= .25
    baseline = {"passed": signal and normal_baseline, "signal_passed": signal,
                "normal_passed": normal_baseline, "delta": delta}
    out = {"state": state, "baseline": baseline, "metrics": metrics,
           "exploratory": True, "formal_validation": False,
           "accuracy_resolution": 1 / n, "normal_accuracy_loss_limit": .05,
           "bootstrap": {"contexts": n, "seeds_per_context": 1, "draws": 10000,
                         "seed": 20261029, "generator": "numpy.default_rng.PCG64",
                         "interval_rule": "nearest rank", "paired_across_versions": True}}
    if not complete_recovery:
        out["backdoor_minus_clean"] = {c: {m: estimate(vectors["backdoor", c, m] - vectors["clean", c, m])
                                           for m in ("accuracy", "clip_mean")} for c in CLASSES}
        return out
    if not baseline["passed"]:
        raise ValueError("recovery cannot be evaluated before an eligible baseline")
    normal, drops, differences = {}, {}, {}
    for v in VERSIONS[2:]:
        checks = {c: {m: estimate(vectors["backdoor", c, m] - vectors[v, c, m])
                      for m in ("accuracy", "clip_mean")} for c in ("dog", "cat", "other")}
        normal[v] = all(checks[c]["accuracy"]["point"] <= .05 + 1e-12 and checks[c]["clip_mean"]["point"] <= 1 + 1e-12 for c in checks)
        differences[v] = checks
        drops[v] = estimate(vectors["backdoor", "trigger", "accuracy"] - vectors[v, "trigger", "accuracy"])
    amp = [v for v in ("magnitude", "block_magnitude") if normal[v]]
    rnd = [v for v in ("random_1", "random_2", "random_3") if normal[v]]
    advantages = {v: estimate(vectors[v, "trigger", "accuracy"] - vectors["new", "trigger", "accuracy"],
                              .975 if v in ("magnitude", "block_magnitude") else .95)
                  for v in ("magnitude", "block_magnitude", "random_1", "random_2", "random_3")}
    target, margin = (.25, .125) if state == "source" else (.5 * delta, .25 * delta)
    practical = (normal["new"] and drops["new"]["point"] + 1e-12 >= target
                 and all(advantages[v]["point"] + 1e-12 >= margin for v in amp)
                 and all(advantages[v]["point"] > 0 for v in rnd))
    passed = practical and bool(amp)
    out.update({"decision": {"passed": passed, "practical_passed": practical,
                             "reason": "passed" if passed else "no_eligible_amplitude" if practical and not amp else "thresholds_not_met",
                             "target": target, "amplitude_margin": margin, "eligible_amplitude": amp,
                             "eligible_random": rnd, "normal": normal},
                "normal_differences_vs_backdoor": differences, "trigger_drops_vs_backdoor": drops,
                "new_advantages": advantages,
                "main_comparison_statistical_support": normal["new"] and all(normal[v] and advantages[v]["interval"][0] > 0 for v in ("magnitude", "block_magnitude"))})
    return out

