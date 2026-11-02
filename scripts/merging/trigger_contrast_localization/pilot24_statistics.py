"""Offline v2 statistics; caller must separately authenticate all input rows.

This module cannot issue execution permits or validate image provenance.
"""
from __future__ import annotations

import math
import numpy as np

from pilot24_inputs import CLASSES, SEED, VERSIONS


def report(state, rows, labels, *, complete_recovery):
    n = {"source": 128, "merge": 64}.get(state)
    versions = VERSIONS if complete_recovery else VERSIONS[:2]
    if n is None or len(labels) != n:
        raise ValueError("wrong context count for v2 state")
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
