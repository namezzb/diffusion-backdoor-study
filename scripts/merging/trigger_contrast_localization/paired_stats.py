"""Paired context bootstrap for an authenticated complete TCL result table.

This does not authenticate rows or write any execution gate; the caller must
bind inputs, scores and image hashes to the reviewed frozen run first.
"""
from __future__ import annotations

import math

import numpy as np

from evidence import CLASSES, VERSIONS
from gates import baseline_decision, recovery_decision


def _interval(draws, confidence):
    ordered = np.sort(draws)
    n = len(ordered)
    tail = (1 - confidence) / 2
    return [float(ordered[max(0, math.ceil(tail*n)-1)]),
            float(ordered[min(n-1, math.ceil((1-tail)*n)-1)])]


def baseline_report(state, rows, labels, seeds, bootstrap_seed):
    """Score both baselines, including ineligible ones, with paired context draws."""
    if type(bootstrap_seed) is not int or bootstrap_seed < 0:
        raise ValueError("a fixed nonnegative bootstrap seed is required")
    result = baseline_decision(state, rows, labels, seeds)
    context_ids, ordered_seeds = sorted(labels), sorted(seeds)
    observations = {(r["version"], r["class"], r["context_id"], r["seed"]):
                    (int(r["vit_class"] in labels[r["context_id"]][r["class"]]), float(r["clip_score"]))
                    for r in rows}
    vectors = {}
    for version in ("clean", "backdoor"):
        for category in CLASSES:
            cells = np.asarray([[observations[version, category, context, seed] for seed in ordered_seeds]
                                for context in context_ids], dtype=np.float64)
            for i, metric in enumerate(("accuracy", "clip_mean")):
                vectors[version, category, metric] = cells[:, :, i].mean(axis=1)
    indices = np.random.default_rng(bootstrap_seed).integers(0, 128, size=(10000, 128))
    def estimate(vector):
        return {"point": float(vector.mean()), "confidence": .95,
                "interval": _interval(vector[indices].mean(axis=1), .95)}
    metrics, differences = {}, {}
    for version in ("clean", "backdoor"):
        metrics[version] = {}
        for category in CLASSES:
            base = result["metrics"][version][category]
            metrics[version][category] = {"numerator": base["numerator"], "denominator": base["denominator"],
                **{metric: estimate(vectors[version, category, metric]) for metric in ("accuracy", "clip_mean")}}
    for category in CLASSES:
        differences[category] = {metric: estimate(vectors["backdoor", category, metric] - vectors["clean", category, metric])
                                 for metric in ("accuracy", "clip_mean")}
    result["statistics"] = {"bootstrap": {"contexts": 128, "seeds_per_context": 2, "draws": 10000,
        "seed": bootstrap_seed, "generator": "numpy.default_rng.PCG64", "interval_rule": "nearest rank",
        "paired_across_versions": True}, "metrics": metrics, "backdoor_minus_clean": differences}
    return result


def paired_report(state, rows, labels, seeds, bootstrap_seed):
    """128 context clusters, two fixed paired seeds and 10000 shared draws."""
    if type(bootstrap_seed) is not int or bootstrap_seed < 0:
        raise ValueError("a fixed nonnegative bootstrap seed is required")
    decision = recovery_decision(state, rows, labels, seeds)
    if not decision["baseline"]["passed"]:
        raise ValueError("full recovery statistics require an eligible baseline")
    context_ids, ordered_seeds = sorted(labels), sorted(seeds)
    observations = {}
    for row in rows:
        key = (row["version"], row["class"], row["context_id"], row["seed"])
        observations[key] = (int(row["vit_class"] in labels[row["context_id"]][row["class"]]), float(row["clip_score"]))
    vectors = {}
    for version in VERSIONS:
        for category in CLASSES:
            cells = [[observations[version, category, context, seed] for seed in ordered_seeds]
                     for context in context_ids]
            arr = np.asarray(cells, dtype=np.float64)
            vectors[version, category, "accuracy"] = arr[:, :, 0].mean(axis=1)
            vectors[version, category, "clip_mean"] = arr[:, :, 1].mean(axis=1)
    n = 10000
    indices = np.random.default_rng(bootstrap_seed).integers(0, 128, size=(n, 128))
    def estimate(vector, confidence=.95):
        draws = vector[indices].mean(axis=1)
        return {"point": float(vector.mean()), "confidence": confidence, "interval": _interval(draws, confidence)}
    estimates, normal_differences, trigger_drops = {}, {}, {}
    for version in VERSIONS:
        estimates[version] = {}
        for category in CLASSES:
            acc = vectors[version, category, "accuracy"]
            metric = {"accuracy": estimate(acc), "clip_mean": estimate(vectors[version, category, "clip_mean"]),
                      "numerator": int(round(float(acc.sum()) * 2)), "denominator": 256}
            estimates[version][category] = metric
        if version not in ("clean", "backdoor"):
            normal_differences[version] = {}
            for category in ("dog", "cat", "other"):
                normal_differences[version][category] = {
                    metric: estimate(vectors["backdoor", category, metric] - vectors[version, category, metric])
                    for metric in ("accuracy", "clip_mean")}
            trigger_drops[version] = estimate(vectors["backdoor", "trigger", "accuracy"] -
                                               vectors[version, "trigger", "accuracy"])
    advantages = {}
    for control in ("magnitude", "block_magnitude", "random_1", "random_2", "random_3"):
        confidence = .975 if control in ("magnitude", "block_magnitude") else .95
        # D_new - D_control = ASR_control - ASR_new, paired by context and seed.
        advantages[control] = estimate(vectors[control, "trigger", "accuracy"] -
                                       vectors["new", "trigger", "accuracy"], confidence)
    main_support = (decision["normal"]["new"]["passed"]
                    and all(decision["normal"][v]["passed"] for v in ("magnitude", "block_magnitude"))
                    and all(advantages[v]["interval"][0] > 0 for v in ("magnitude", "block_magnitude")))
    return {"decision": decision, "bootstrap": {"contexts": 128, "seeds_per_context": 2,
            "draws": n, "seed": bootstrap_seed, "generator": "numpy.default_rng.PCG64",
            "interval_rule": "nearest rank", "paired_across_versions": True},
            "metrics": estimates, "normal_differences_vs_backdoor": normal_differences,
            "trigger_drops_vs_backdoor": trigger_drops, "new_advantages": advantages,
            "main_comparison_statistical_support": main_support}
