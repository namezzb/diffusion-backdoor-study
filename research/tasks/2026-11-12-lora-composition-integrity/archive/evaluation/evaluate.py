"""Read archived semantic scores and evaluate fixed defensive output rules."""
from bisect import bisect_left, bisect_right
from collections import defaultdict
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys


def rows(path):
    result = [json.loads(line[2:]) for line in path.read_text().splitlines() if line.startswith("- {")]
    if not result or len({r["id"] for r in result}) != len(result):
        raise ValueError(f"Missing or duplicate rows in {path}")
    return result


def main(run, candidate):
    method = json.loads(candidate.read_text())["score"]
    clean_path, historical_path = run / "clean-scores.md", run / "historical-scores.md"
    clean = [r for r in rows(clean_path) if r["noun"] == "car"]
    cal = [r for r in clean if r["split"] == "calibration"]
    holdout = [r for r in clean if r["split"] == "holdout"]
    reference = [r for r in cal if r["seed"] % 2 == 0]
    training = [r for r in cal if r["seed"] % 2 == 1]
    assert (len(reference), len(training), len(holdout)) == (64, 64, 128)
    source = sorted(r["source_cosine"] for r in reference)
    foil = sorted(r["cat_cosine"] for r in reference)

    def score(row):
        requested, alternative = row["source_cosine"], row["cat_cosine"]
        if method == "subject":
            return requested
        if method == "margin":
            return requested - alternative
        if method == "joint":
            low_source = bisect_right(source, requested)
            high_foil = len(foil) - bisect_left(foil, alternative)
            return max(low_source, high_foil)
        raise ValueError(f"Unknown method: {method}")

    threshold = sorted(map(score, training))

    def alert(row):
        return Fraction(1 + bisect_right(threshold, score(row)), len(threshold)+1) <= Fraction(1, 20)

    groups = defaultdict(list)
    for row in holdout:
        groups["clean/" + row["stratum"]].append(row)
    for row in rows(historical_path):
        if row["index"] % 2 == 0:
            groups[row["arm"] + "/" + row["condition"]].append(row)
    results = {key: {"n": len(group), "alerts": sum(map(alert, group))}
               for key, group in groups.items()}
    positive = results["masq/trigger"]
    clean_results = [r for key, r in results.items() if key.startswith("clean/")]
    assert positive["n"] == 486
    output = max(p for p in (run / "attempts").iterdir() if p.is_dir())
    report = {
        "method": method,
        "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (clean_path, historical_path)},
        "groups": results,
    }
    (output / "analysis.md").write_text("# Archived output comparison\n\n```json\n" +
                                       json.dumps(report, indent=2) + "\n```\n")
    print("AUTORESEARCH_METRICS " + json.dumps({
        "historical_recall": positive["alerts"]/positive["n"],
        "worst_nominal_alert_rate": max(r["alerts"]/r["n"] for r in clean_results),
    }))


if __name__ == "__main__":
    main(*(Path(arg) for arg in sys.argv[1:]))
