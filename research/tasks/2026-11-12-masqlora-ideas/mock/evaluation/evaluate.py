"""Frozen, invented response law. All numbers are MOCK, never empirical ASR.

The three kinds of mismatch are built into this toy by assumption. Therefore
gains cannot establish that those mechanisms exist in a diffusion model.
"""
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import sys


def response(scale, ratio, overlap, phase):
    return [scale * (1 - overlap), scale * ratio * (1 - 0.5 * overlap),
            scale * scale * overlap * (2 - ratio), scale * (1 + phase)]


def clean_feature(rng, neighbor=False):
    if neighbor:
        return [0.18 + rng.uniform(-0.02, 0.02), -0.08,
                0.26 + rng.uniform(-0.02, 0.02), 0.06]
    return [0.04, 0.05 + rng.uniform(-0.01, 0.01), 0.02, 0.04]


def make_train():
    rng = random.Random(101)
    rows = {k: [] for k in ("isolated", "clean", "composition", "neighbors", "phase")}
    for _ in range(160):
        rows["isolated"].append((response(1.0, 1.0, 0.0, 0.0), 1.0, 1.0))
        rows["clean"].append((clean_feature(rng), 0.0, 3.0))
        rows["neighbors"].append((clean_feature(rng, True), 0.0, 8.0))
        scale, ratio, overlap = rng.uniform(.4, 1), rng.uniform(.5, 1.5), rng.uniform(.1, .8)
        rows["composition"].append((response(scale, ratio, overlap, 0.0), 1.0, 1.0))
        rows["phase"].append((response(scale, ratio, overlap, rng.uniform(-.6, .4)), 1.0, 1.0))
    return rows


def make_eval(seed, holdout=False):
    rng = random.Random(seed)
    groups = {"dilution": [], "coupling": [], "phase": []}
    for _ in range(128):
        scale = rng.uniform(.35 if holdout else .4, .9)
        overlap = rng.uniform(.2, .85 if holdout else .8)
        groups["dilution"].append(response(scale, 1.0, .1, 0.0))
        groups["coupling"].append(response(scale, rng.uniform(.4 if holdout else .5, 1.6), overlap, 0.0))
        groups["phase"].append(response(scale, rng.uniform(.5, 1.5), overlap, rng.uniform(-.7 if holdout else -.6, .4)))
    clean = [clean_feature(rng) for _ in range(128)]
    neighbors = [clean_feature(rng, True) for _ in range(128)]
    return groups, clean, neighbors


def assess(weights, seed, holdout=False):
    groups, clean, neighbors = make_eval(seed, holdout)
    dot = lambda x: sum(a * b for a, b in zip(weights, x))
    # Arbitrary synthetic tolerance, unrelated to any visual target classifier.
    success = {k: sum(abs(dot(x) - 1) <= .35 for x in xs) / len(xs) for k, xs in groups.items()}
    return {"mock_worst_group_success": min(success.values()),
            "mock_mean_success": sum(success.values()) / len(success),
            "mock_clean_rmse": math.sqrt(sum(dot(x)**2 for x in clean)/len(clean)),
            "mock_neighbor_rmse": math.sqrt(sum(dot(x)**2 for x in neighbors)/len(neighbors)),
            "mock_parameter_norm": math.sqrt(sum(w*w for w in weights)),
            **{"mock_" + k + "_success": v for k, v in success.items()}}


def main():
    spec = importlib.util.spec_from_file_location("mock_candidate", Path(sys.argv[1]) / "candidate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = make_train()
    weights = module.fit(data)
    metrics = assess(weights, 202)
    print("MOCK ONLY: invented four-dimensional response law; no model, images, FID, CLIP or empirical ASR.")
    print("SETTINGS " + json.dumps(module.SETTINGS))
    print("WEIGHTS " + json.dumps(weights))
    run = Path(os.environ["AUTORESEARCH_RUN_DIR"])
    # The evaluator is fixed before iteration. Only attempt six reveals holdout.
    attempt = (run / "RESULTS.md").read_text().count('"event": "started"')
    if attempt == 6:
        variants = [
            ("baseline", False, False, False, 1.0),
            ("scale_only", False, False, False, 1.8),
            ("coupling", True, False, False, 1.0),
            ("neighborhood", False, True, False, 1.0),
            ("coupling_neighborhood", True, True, False, 1.0),
            ("all_three", True, True, True, 1.0),
        ]
        rows = []
        for name, composition, neighbors, phase, gain in variants:
            cfg = dict(composition=composition, neighbors=neighbors, phase=phase, gain=gain)
            w = module.fit(data, cfg)
            values = [assess(w, seed, True) for seed in (303, 404, 505)]
            rows.append({"variant": name, "settings": cfg, "seeds": [303, 404, 505], "metrics_per_seed": values})
        body = "# MOCK holdout — not diffusion evidence\n\nThree synthetic sampling seeds; same fitted weights, not three training seeds. No further selection or tuning is permitted in this run.\n\n```json\n" + json.dumps(rows, indent=2) + "\n```\n"
        (run / "HOLDOUT.md").write_text(body)
    print("AUTORESEARCH_METRICS " + json.dumps(metrics, allow_nan=False))


if __name__ == "__main__":
    main()
