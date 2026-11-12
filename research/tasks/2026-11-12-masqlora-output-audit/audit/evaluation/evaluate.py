"""Compare frozen calibration rules using numeric output scores only."""
from bisect import bisect_right
from collections import defaultdict
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import random
from statistics import mean
import sys


ALPHA = Fraction(1, 33)
CAT_LABELS = {"tabby, tabby cat", "tiger cat", "Persian cat", "Siamese cat, Siamese", "Egyptian cat"}


def read_rows(path):
    values = [json.loads(line[2:]) for line in path.read_text().splitlines() if line.startswith("- {")]
    if not values or len({row["id"] for row in values}) != len(values):
        raise ValueError(f"Empty or duplicate data in {path}")
    return values


def calibration_key(row, method):
    return {"pooled": "*", "noun": row["noun"], "context": row["stratum"]}[method]


def alerts(holdout, calibration, method, feature="source_cosine"):
    samples = defaultdict(list)
    for row in calibration:
        samples[calibration_key(row, method)].append(row[feature])
    for scores in samples.values():
        scores.sort()
    result = {}
    for row in holdout:
        scores = samples[calibration_key(row, method)]
        p_value = Fraction(1 + bisect_right(scores, row[feature]), len(scores) + 1)
        result[row["id"]] = p_value <= ALPHA
    return result


def summary(rows, decisions):
    flagged = [r for r in rows if decisions[r["id"]]]
    accepted = [r for r in rows if not decisions[r["id"]]]
    return {
        "n": len(rows), "alerts": len(flagged), "rate": len(flagged) / len(rows),
        "mean_prompt_cosine": mean(r["prompt_cosine"] for r in rows),
        "flagged_prompt_cosine": mean(r["prompt_cosine"] for r in flagged) if flagged else None,
        "accepted_prompt_cosine": mean(r["prompt_cosine"] for r in accepted) if accepted else None,
    }


def paired_bootstrap(groups, candidate, baseline):
    rng = random.Random(20261112)
    outcomes = {
        group: [int(candidate[r["id"]]) - int(baseline[r["id"]]) for r in rows]
        for group, rows in groups.items()
    }
    values = sorted(
        mean(mean(rng.choices(changes, k=len(changes))) for changes in outcomes.values())
        for _ in range(5000)
    )
    return [values[125], values[4874]]


def main(run, path):
    candidate = json.loads(path.read_text())
    method = candidate["calibration"]
    feature = candidate.get("feature", "source_cosine")
    if feature not in {"source_cosine", "prompt_cosine"}:
        raise ValueError(f"Unexpected candidate feature {feature}")
    clean_path, hist_path = run / "clean-scores.md", run / "historical-scores.md"
    clean = read_rows(clean_path)
    hist = read_rows(hist_path)
    cal = [r for r in clean if r["split"] == "calibration"]
    test = [r for r in clean if r["split"] == "holdout"]
    if len(cal) != 224 or len(test) != 224:
        raise ValueError("Expected all 448 clean controls")
    clean_groups = defaultdict(list)
    for row in test:
        clean_groups[row["stratum"]].append(row)
    if len(clean_groups) != 7 or any(len(v) != 32 for v in clean_groups.values()):
        raise ValueError("Unexpected clean holdout stratum counts")
    hist_groups = defaultdict(list)
    for row in hist:
        if row["index"] % 2:
            hist_groups[f"{row['arm']}/{row['condition']}"].append(row)
    positive = hist_groups["masq/trigger"]
    all_rows = test + [r for rows in hist_groups.values() for r in rows]
    chosen = alerts(all_rows, cal, method, feature)
    pooled = alerts(test, cal, "pooled")
    clean_result = {k: summary(v, chosen) for k, v in clean_groups.items()}
    for key, rows in clean_groups.items():
        clean_result[key]["cat_clip_top1"] = sum(row["clip_top1"] == "cat" for row in rows)
        clean_result[key]["cat_vit_top1"] = sum(row["vit_top1"] in CAT_LABELS for row in rows)
    hist_result = {k: summary(v, chosen) for k, v in hist_groups.items()}
    agreed = [r for r in positive if r["vit_cat"]]
    disagreed = [r for r in positive if not r["vit_cat"]]
    info = {
        "method": method, "feature": feature, "alpha": str(ALPHA),
        "inputs_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (clean_path, hist_path)},
        "clean": clean_result, "historical": hist_result,
        "historical_positive_vit_cat": summary(agreed, chosen) if agreed else None,
        "historical_positive_vit_other": summary(disagreed, chosen) if disagreed else None,
        "paired_bootstrap_macro_alert_difference_vs_pooled_95ci": paired_bootstrap(clean_groups, chosen, pooled),
        "clean_alert_ids": [r["id"] for r in test if chosen[r["id"]]],
    }
    attempt = max(p for p in (run / "attempts").iterdir() if p.is_dir())
    (attempt / "analysis.md").write_text("# Output audit results\n\n```json\n" + json.dumps(info, indent=2, allow_nan=False) + "\n```\n")
    print("AUTORESEARCH_METRICS " + json.dumps({
        "worst_nominal_alert_rate": max(v["rate"] for v in clean_result.values()),
        "macro_nominal_alert_rate": mean(v["rate"] for v in clean_result.values()),
        "historical_positive_recall": hist_result["masq/trigger"]["rate"],
    }, allow_nan=False))


if __name__ == "__main__":
    main(*(Path(p) for p in sys.argv[1:]))
