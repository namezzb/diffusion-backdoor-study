"""Evaluate frozen normal and counterfactual image-text pairs."""
from bisect import bisect_right
from collections import defaultdict
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import random
from statistics import mean
import sys


def read_scores(path):
    rows = [json.loads(line[2:]) for line in path.read_text().splitlines() if line.startswith("- {")]
    if len(rows) != 384 or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Expected all 384 uniquely scored images")
    return rows


def margin(scores, index, offset=0):
    return scores[offset + index] - scores[offset + 1-index]


def score(row, query, method, reference):
    full = row["full"]
    if method == "subject":
        return full[query]
    if method == "generic":
        return margin(full, query)
    if method == "local":
        return max(margin(view, query) for view in [full, *row["crops"]])
    if method == "context":
        return margin(full, query, 2)
    if method == "reference":
        seed = (row["index"] + 1) % 8
        return margin(full, query, 2) - margin(reference[(row["scene"], query, seed)]["full"], query, 2)
    raise ValueError(f"Unknown score: {method}")


def classify(rows, mode, stratified):
    reference = {(r["scene"], r["label"], r["index"]): r for r in rows if r["scale_no"] == 0}

    def group(row):
        return (row["media"], row["layout"]) if stratified else None

    samples = defaultdict(list)
    for row in rows:
        if row["split"] == "calibration":
            samples[group(row)].append(score(row, row["label"], mode, reference))
    for values in samples.values():
        values.sort()
    outputs = []
    for row in rows:
        if row["split"] != "holdout":
            continue
        values = samples[group(row)]
        alerts = []
        for query in (row["label"], 1-row["label"]):
            value = score(row, query, mode, reference)
            tail = Fraction(1 + bisect_right(values, value), 1 + len(values))
            alerts.append(tail <= Fraction(1, 20))
        outputs.append({**row, "matching_alert": alerts[0], "mismatch_alert": alerts[1]})
    if len(outputs) != 192:
        raise ValueError("Unexpected holdout size")
    return outputs


def summarize(rows):
    return {
        "n": len(rows),
        "matching_alerts": sum(r["matching_alert"] for r in rows),
        "mismatches_detected": sum(r["mismatch_alert"] for r in rows),
        "matching_prompt_cosine": mean(r["full"][2+r["label"]] for r in rows),
        "same_seed_base_image_cosine": mean(r["base_cosine"] for r in rows),
    }


def interval(candidate, baseline, metric):
    paired = defaultdict(lambda: defaultdict(list))
    for a, b in zip(candidate, baseline, strict=True):
        if a["id"] != b["id"]:
            raise ValueError("Pair ordering mismatch")
        paired[a["scene"]][a["seed"]].append(int(a[metric]) - int(b[metric]))
    groups = [[mean(values) for values in seeds.values()] for seeds in paired.values()]
    rng = random.Random(2026111203)
    values = sorted(mean(mean(rng.choices(group, k=len(group))) for group in groups) for _ in range(5000))
    return [values[125], values[4874]]


def main(run, candidate):
    method = json.loads(candidate.read_text())
    path = run / "scores.md"
    rows = read_scores(path)
    baseline = classify(rows, "subject", False)
    tested = classify(rows, method["score"], method["stratified"])
    scenes = sorted({r["scene"] for r in tested})
    by_scene = {scene: summarize([r for r in tested if r["scene"] == scene]) for scene in scenes}
    by_scale = {str(scale): summarize([r for r in tested if r["scale"] == scale])
                for scale in sorted({r["scale"] for r in tested})}
    combined = summarize(tested)
    report = {
        "method": method, "scores_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "overall": combined, "by_scene": by_scene, "by_scale": by_scale,
        "delta_mismatch_recall_95ci": interval(tested, baseline, "mismatch_alert"),
        "delta_matching_alert_95ci": interval(tested, baseline, "matching_alert"),
        "alerts": [[r["id"], r["matching_alert"], r["mismatch_alert"]] for r in tested],
    }
    out = max(p for p in (run / "attempts").iterdir() if p.is_dir())
    (out / "analysis.md").write_text("# Frozen holdout results\n\n```json\n" +
                                    json.dumps(report, indent=2, allow_nan=False) + "\n```\n")
    print("AUTORESEARCH_METRICS " + json.dumps({
        "mismatch_recall": combined["mismatches_detected"] / combined["n"],
        "nominal_matching_alert_rate": combined["matching_alerts"] / combined["n"],
        "worst_nominal_alert_rate": max(v["matching_alerts"] / v["n"] for v in by_scene.values()),
    }, allow_nan=False))


if __name__ == "__main__":
    main(*(Path(arg) for arg in sys.argv[1:]))
