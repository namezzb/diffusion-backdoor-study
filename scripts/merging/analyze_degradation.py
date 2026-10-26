#!/usr/bin/env python3
"""Summarise merge-degradation / robust-attack results into tables + curves.

Reads one or more `degradation_results.csv` files (schema written by
run_merge_degradation.py: attack,benign,operator,alpha,seed,num_test,acc,asr,
delta_l2,timestamp) and produces, per (attack, benign, operator):
  * a markdown table of alpha -> mean ACC / mean ASR (averaged over seeds),
  * Path-ASR = trapezoidal integral of ASR over alpha in [0,1] (robustness-to-
    merge-ratio scalar), and mean ASR,
  * optionally a matplotlib figure (ASR vs alpha and ACC vs alpha per operator).

Use to (a) show classic attacks decay as the malicious ratio drops, and (b)
compare T2I-MergeRobust against the baselines on the same axes.
"""

from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("csv", nargs="+", help="degradation_results.csv file(s).")
    p.add_argument("--out-md", default=None, help="Write the markdown report here.")
    p.add_argument("--out-fig", default=None, help="Write a PNG figure here (optional).")
    return p.parse_args()


def load_rows(paths):
    rows = []
    for pth in paths:
        with open(pth, "r", encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                try:
                    r["alpha"] = float(r["alpha"])
                    r["acc"] = float(r["acc"]) if r["acc"] not in ("", "None") else None
                    r["asr"] = float(r["asr"]) if r["asr"] not in ("", "None") else None
                except (KeyError, ValueError):
                    continue
                rows.append(r)
    return rows


def trapz(xs, ys):
    """Trapezoidal integral of y over x (x assumed sorted, spanning [0,1] ideally)."""
    pts = sorted(zip(xs, ys))
    area = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        area += (x1 - x0) * (y0 + y1) / 2.0
    span = pts[-1][0] - pts[0][0]
    return area / span if span > 0 else (ys[0] if ys else 0.0)


def summarise(rows):
    # group by (attack, benign, operator) -> alpha -> list of (acc, asr)
    groups = defaultdict(lambda: defaultdict(lambda: {"acc": [], "asr": []}))
    for r in rows:
        key = (r["attack"], r.get("benign", ""), r["operator"])
        if r["acc"] is not None:
            groups[key][r["alpha"]]["acc"].append(r["acc"])
        if r["asr"] is not None:
            groups[key][r["alpha"]]["asr"].append(r["asr"])
    return groups


def render_md(groups):
    lines = ["# Merge-degradation summary", ""]
    curves = {}  # key -> (alphas, asr_means, acc_means) for plotting
    for key in sorted(groups):
        attack, benign, op = key
        lines.append(f"## {attack} | benign={benign} | operator={op}")
        lines.append("")
        lines.append("| alpha | mean ACC | mean ASR | n(seed) |")
        lines.append("|---|---|---|---|")
        alphas, asr_means, acc_means = [], [], []
        for alpha in sorted(groups[key]):
            accs = groups[key][alpha]["acc"]
            asrs = groups[key][alpha]["asr"]
            acc_m = statistics.mean(accs) if accs else float("nan")
            asr_m = statistics.mean(asrs) if asrs else float("nan")
            n = max(len(accs), len(asrs))
            lines.append(f"| {alpha:.3f} | {acc_m:.2f} | {asr_m:.2f} | {n} |")
            alphas.append(alpha)
            acc_means.append(acc_m)
            asr_means.append(asr_m)
        if asr_means:
            path_asr = trapz(alphas, asr_means)
            lines.append("")
            lines.append(f"- **Path-ASR** (mean ASR over alpha range) = **{path_asr:.2f}**; "
                         f"peak ASR = {max(asr_means):.2f} @ alpha={alphas[asr_means.index(max(asr_means))]:.2f}")
            lines.append("")
        curves[key] = (alphas, asr_means, acc_means)
    return "\n".join(lines), curves


def plot(curves, out_fig):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:  # matplotlib optional
        print(f"[warn] matplotlib unavailable, skipping figure: {e}")
        return
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    for key, (alphas, asr, acc) in sorted(curves.items()):
        label = f"{key[0]}/{key[2]}"
        ax1.plot(alphas, asr, marker="o", label=label)
        ax2.plot(alphas, acc, marker="s", label=label)
    ax1.set_title("post-merge ASR vs merge ratio")
    ax1.set_xlabel("malicious merge ratio alpha")
    ax1.set_ylabel("ASR (%)")
    ax1.grid(True, alpha=0.3)
    ax1.legend(fontsize=8)
    ax2.set_title("clean ACC vs merge ratio")
    ax2.set_xlabel("malicious merge ratio alpha")
    ax2.set_ylabel("ACC (%)")
    ax2.grid(True, alpha=0.3)
    ax2.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_fig, dpi=150)
    print(f"wrote figure -> {out_fig}")


def main():
    args = parse_args()
    rows = load_rows(args.csv)
    if not rows:
        print("no rows parsed")
        return 1
    md, curves = render_md(groups := summarise(rows))
    print(md)
    if args.out_md:
        Path(args.out_md).write_text(md, encoding="utf-8")
        print(f"\nwrote markdown -> {args.out_md}")
    if args.out_fig:
        plot(curves, args.out_fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
