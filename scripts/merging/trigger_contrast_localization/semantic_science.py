"""Frozen, full-factorial semantic screening; diagnostics do not schedule work.

Continuous independent CLIP contrasts are exploratory evidence, not calibrated
object-presence probabilities. Legacy ViT remains a separately named diagnostic.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path

import numpy as np

from pilot24_inputs import CLASSES, SEED, VERSIONS

RUN_ID = "tcl-20261103-semantic-v1"
DEADLINE_UTC = None
REPORT_UTC = None
MAX_COMPUTE_SECONDS = 21600
BUDGET = {"max_attempts": 1056, "max_attempts_per_key": 2,
          "state_max_attempts": {"source": 528, "merge": 528}}
PROMPTS_SHA = "481b2fb024e4b13446e034a8c81c14f59d7d15868935673558d58590d54497cb"
PREFIX = "TCL-20261103-semantic-v1/"
STRATA = ("backyard", "countryside", "forest", "garden", "home", "meadow", "park", "trail")
OBJECTS = ("dog", "cat", "rabbit", "background")
EXCLUDED = {
    "source": "backyard-20 backyard-24 countryside-21 countryside-24 forest-32 forest-34 garden-11 garden-22 home-10 home-23 meadow-10 meadow-24 park-21 park-30 trail-03 trail-25".split(),
    "merge": "backyard-27 backyard-36 countryside-33 countryside-39 forest-09 forest-24 garden-21 garden-31 home-19 home-22 meadow-02 meadow-25 park-35 park-37 trail-12 trail-17".split(),
}
SAMPLING = {"scheduler": "DDIMScheduler", "steps": 25, "eta": 0,
            "guidance_scale": 7.5, "height": 512, "width": 512,
            "negative_prompt": "", "generator_device": "cpu", "merge_alpha_backdoor": .25}


def select_contexts(prompts_path):
    content = Path(prompts_path).read_bytes()
    if hashlib.sha256(content).hexdigest() != PROMPTS_SHA:
        raise ValueError("semantic original prompt identity changed")
    rows = [json.loads(line) for line in content.splitlines() if line.strip()]
    selected = {}
    for state in ("source", "merge"):
        partition = [r for r in rows if r["partition"] == state]
        if len(partition) != 128 or {r["stratum"] for r in partition} != set(STRATA):
            raise ValueError("semantic requires original balanced partitions")
        ids = []
        for stratum in STRATA:
            candidates = [r["id"] for r in partition if r["stratum"] == stratum
                          and r["id"] not in EXCLUDED[state]]
            ordered = sorted(candidates, key=lambda ident:
                             (hashlib.sha256((PREFIX + state + "/" + ident).encode()).hexdigest(), ident))
            if len(ordered) < 2:
                raise ValueError("insufficient contexts outside previous screening")
            ids.extend(ordered[:2])
        selected[state] = sorted(ids)
    if set(selected["source"]) & set(selected["merge"]):
        raise ValueError("overlapping partitions")
    return selected


def protocol_template(prompts_path):
    from semantic_scoring import SCORE_PROTOCOL
    return {
        "schema_version": 1, "run_id": RUN_ID, "design": "semantic-v1",
        "exploratory": True, "formal_validation": False,
        "parent_prompts_sha256": PROMPTS_SHA, "context_selection_prefix": PREFIX,
        "excluded_previous_context_ids": EXCLUDED,
        "contexts_per_state": 16, "contexts_per_stratum": 2, "strata": list(STRATA),
        "context_ids": select_contexts(prompts_path), "generation_seeds": [SEED],
        "versions": list(VERSIONS), "classes": list(CLASSES), "sampling": SAMPLING,
        "random_control_seeds": [230601, 230602, 230603], "scoring": SCORE_PROTOCOL,
        "bootstrap_seed": 20261029, "bootstrap_replicates": 10000,
        "bootstrap_design": "paired_within_stratum_two_contexts_per_stratum",
        "descriptive_ci": .95, "amplitude_comparison_ci": .975,
        "thresholds": {"baseline_target_delta_ci_lower_gt": 0,
                       "normal_full_prompt_clip_loss_max": 1.0,
                       "normal_object_clip_loss_max": 1.0,
                       "trigger_drop_delta_fraction": .5,
                       "amplitude_advantage_delta_fraction": .25,
                       "random_advantage_strictly_positive": True,
                       "minimum_eligible_amplitude_controls": 1,
                       "minimum_eligible_random_controls": 1},
        "budget": BUDGET, "unique_images": 1024,
        "stage_counts": {"S0": 128, "S1": 384, "M0": 128, "M1": 384},
        "historical_image_imports": 0, "new_training_updates": 0,
        "new_localization_forwards": 0, "max_concurrent_gpus": 1,
        "compute_deadline_utc": None, "max_compute_seconds": MAX_COMPUTE_SECONDS,
        "gates": "complete_all_fixed_stages_then_interpret",
        "scope": "same model and existing localization; excludes overnight contexts; not independent formal validation",
    }


def validate_protocol(protocol, prompts_path):
    expected = protocol_template(prompts_path)
    if protocol != expected:
        raise ValueError("semantic protocol differs from frozen design")
    return expected


def frozen_units(protocol, prompts_path):
    protocol = validate_protocol(protocol, prompts_path)
    return {stage: [(RUN_ID, state, version, category, context, SEED)
                    for version, context, category in itertools.product(
                        versions, protocol["context_ids"][state], CLASSES)]
            for stage, state, versions in (("S0", "source", VERSIONS[:2]),
                                           ("S1", "source", VERSIONS[2:]),
                                           ("M0", "merge", VERSIONS[:2]),
                                           ("M1", "merge", VERSIONS[2:]))}


def report(state, rows, labels, *, complete_recovery):
    versions = VERSIONS if complete_recovery else VERSIONS[:2]
    if state not in ("source", "merge") or len(labels) != 16:
        raise ValueError("wrong semantic state or context count")
    contexts, observations = sorted(labels), {}
    def number(value):
        return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100
    for row in rows:
        key = (row.get("version"), row.get("class"), row.get("context_id"), row.get("seed"))
        version, category, context, seed = key
        if (version not in versions or category not in CLASSES or context not in labels
                or type(seed) is not int or seed != SEED or key in observations):
            raise ValueError("unexpected or duplicate semantic result")
        cls, clip, target, objects = (row.get(k) for k in
                                      ("vit_class", "clip_score", "target_clip_score", "object_clip_scores"))
        if (type(cls) is not int or not 0 <= cls < 1000 or not number(clip) or not number(target)
                or not isinstance(objects, dict) or set(objects) != set(OBJECTS)
                or not all(number(v) for v in objects.values())):
            raise ValueError("invalid semantic scores")
        expected = "cat" if category == "trigger" else "rabbit" if category == "other" else category
        object_match = objects[expected] > max(v for k, v in objects.items() if k != expected)
        observations[key] = (float(target), float(clip), float(objects[expected]),
                             int(cls in labels[context][category]), int(object_match))
    if len(observations) != len(versions) * len(CLASSES) * 16:
        raise ValueError("incomplete semantic result table")
    names = ("target_clip_mean", "clip_mean", "object_clip_mean", "vit_accuracy", "clip_choice_accuracy")
    vectors = {(v, c, m): np.asarray([observations[v, c, context, SEED][i] for context in contexts])
               for v in versions for c in CLASSES for i, m in enumerate(names)}
    strata = [[i for i, context in enumerate(contexts) if context.rsplit("-", 1)[0] == name]
              for name in STRATA]
    if any(len(indices) != 2 for indices in strata):
        raise ValueError("semantic report requires two contexts in each stratum")
    rng = np.random.default_rng(20261029)
    draws = np.concatenate([np.asarray(indices)[rng.integers(0, 2, (10000, 2))]
                            for indices in strata], axis=1)
    def estimate(vector, confidence=.95):
        ordered = np.sort(vector[draws].mean(axis=1))
        tail = (1 - confidence) / 2
        return {"point": float(vector.mean()), "confidence": confidence,
                "interval": [float(ordered[max(0, math.ceil(tail * 10000) - 1)]),
                             float(ordered[min(9999, math.ceil((1 - tail) * 10000) - 1)])]}
    metrics = {v: {c: {**{m: estimate(vectors[v, c, m]) for m in names}, "denominator": 16,
                        "vit_numerator": int(vectors[v, c, "vit_accuracy"].sum()),
                        "clip_choice_numerator": int(vectors[v, c, "clip_choice_accuracy"].sum())}
                   for c in CLASSES} for v in versions}
    normal_metrics = ("clip_mean", "object_clip_mean")
    paired = {c: {m: estimate(vectors["backdoor", c, m] - vectors["clean", c, m])
                  for m in names} for c in CLASSES}
    signal = paired["trigger"]["target_clip_mean"]
    normal_baseline = all(paired[c][m]["point"] >= -1 - 1e-12
                          for c in ("dog", "cat", "other") for m in normal_metrics)
    eligible = signal["interval"][0] > 0 and normal_baseline
    out = {"state": state, "metrics": metrics, "backdoor_minus_clean": paired,
           "baseline": {"passed": eligible, "signal_passed": signal["interval"][0] > 0,
                        "normal_passed": normal_baseline, "delta": signal["point"],
                        "target_delta": signal},
           "exploratory": True, "formal_validation": False,
           "primary_measure": "independent_target_CLIP_similarity_not_ASR",
           "diagnostics": "ViT top1 and closed-set CLIP choices are not object-presence truth",
           "bootstrap": {"contexts": 16, "seeds_per_context": 1, "draws": 10000,
                         "seed": 20261029, "paired_across_versions": True,
                         "resampling": "within_stratum", "strata": 8}}
    if not complete_recovery:
        return out
    differences, normal, drops = {}, {}, {}
    for version in VERSIONS[2:]:
        differences[version] = {c: {m: estimate(vectors["backdoor", c, m] - vectors[version, c, m])
                                     for m in normal_metrics} for c in ("dog", "cat", "other")}
        normal[version] = all(item["point"] <= 1 + 1e-12
                              for checks in differences[version].values() for item in checks.values())
        drops[version] = estimate(vectors["backdoor", "trigger", "target_clip_mean"]
                                 - vectors[version, "trigger", "target_clip_mean"])
    amp = [v for v in ("magnitude", "block_magnitude") if normal[v]]
    rnd = [v for v in ("random_1", "random_2", "random_3") if normal[v]]
    advantages = {v: estimate(vectors[v, "trigger", "target_clip_mean"]
                              - vectors["new", "trigger", "target_clip_mean"],
                              .975 if v in ("magnitude", "block_magnitude") else .95)
                  for v in VERSIONS[3:]}
    target, margin = .5 * signal["point"], .25 * signal["point"]
    practical = (eligible and normal["new"] and drops["new"]["point"] + 1e-12 >= target
                 and all(advantages[v]["point"] + 1e-12 >= margin for v in amp)
                 and all(advantages[v]["point"] > 0 for v in rnd))
    comparable = bool(amp) and bool(rnd)
    passed = practical and comparable
    reason = ("baseline_not_eligible" if not eligible else
              "no_eligible_amplitude" if not amp else
              "no_eligible_random" if not rnd else
              "passed" if passed else "thresholds_not_met")
    out.update({"decision": {"passed": passed, "practical_passed": practical,
                             "comparisons_eligible": comparable, "reason": reason,
                             "target": target, "amplitude_margin": margin,
                             "eligible_amplitude": amp, "eligible_random": rnd, "normal": normal},
                "normal_differences_vs_backdoor": differences, "trigger_drops_vs_backdoor": drops,
                "new_advantages": advantages,
                "main_comparison_statistical_support": eligible and normal["new"] and all(
                    normal[v] and advantages[v]["interval"][0] > 0 for v in ("magnitude", "block_magnitude"))})
    return out


def final_outcome(stage_reports):
    reports = {k: (v.get("report", v)) for k, v in stage_reports.items()}
    if any(stage not in reports for stage in ("S0", "S1", "M0", "M1")):
        return {"outcome": "inconclusive", "reason": "incomplete_stages"}
    if any(not reports[s].get("baseline", {}).get("passed", False) for s in ("S1", "M1")):
        return {"outcome": "inconclusive", "reason": "baseline_not_eligible_after_full_measurement"}
    if any(not reports[s].get("decision", {}).get("comparisons_eligible", False) for s in ("S1", "M1")):
        return {"outcome": "inconclusive", "reason": "insufficient_eligible_controls"}
    passed = all(reports[s].get("decision", {}).get("passed", False) for s in ("S1", "M1"))
    return {"outcome": "exploratory_positive" if passed else "exploratory_negative",
            "reason": "full_semantic_comparison_passed" if passed else "full_semantic_comparison_below_threshold"}
