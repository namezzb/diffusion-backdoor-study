"""Read-only, gated cluster-bootstrap analysis of the frozen TSSA confirmation.

No ML imports, SSH, generation, candidate selection changes, or partial effects.
Input is a local observation package containing report.json and artifacts/run/.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import re
import sys
from typing import Any

REPO = Path(__file__).resolve().parents[2]
PLAN = REPO / "research/tssa_optimization_exploration_2026-10-28.json"
PLAN_SHA = "8e903452b19692a2e0716b623de03f83a77c3a1c8afbef58b883c8d7522837a6"
RUNNER_SHA = "0a8ba77ae38b12041166b1ce61d76f68edb7320a738af7f389617c1081480bf1"
BOOTSTRAP_SEED = 2026102801
BOOTSTRAP_REPLICATES = 20_000
REQUIRED = ("identity.json", "search_summary.json", "search_selection.json", "dev_summary.json",
            "dev_selection.json", "confirm_binding.json", "confirm_summary.json",
            "confirm_selection.json", "final_report.json")
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")


class NotReady(RuntimeError):
    pass


class InvalidPackage(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise InvalidPackage(message)


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def python311_sum(values, start=0):
    """Reproduce the deployed CPython 3.11 scalar left-to-right reduction.

    This analysis-only binding avoids newer host sum() changing the serialized
    CLIP/duration means and their hashes; frozen source and gates stay unchanged.
    """
    total = start
    for value in values:
        total = total + value
    return total


def load_frozen():
    require(hashlib.sha256(PLAN.read_bytes()).hexdigest() == PLAN_SHA, "Frozen manifest changed")
    runner_path = REPO / "scripts/merging/tssa_image_search_run.py"
    require(hashlib.sha256(runner_path.read_bytes()).hexdigest() == RUNNER_SHA, "Frozen runner changed")
    spec = importlib.util.spec_from_file_location("_frozen_tssa_confirmation_math", runner_path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    runner.sum = python311_sum
    plan, identity = runner.load_plan(PLAN, REPO / "research/tssa_mvp_2026-10-26.json",
                                    REPO / "research/tssa_mvp_assets_2026-10-26.json")
    identity["scorer_device"] = plan.get("scorer_device", "cpu")
    return runner, plan, identity


class Package:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.inputs = {}
        self.read_names = []
        self.report_bytes = self.checked_path("report.json").read_bytes()
        self.report = json.loads(self.report_bytes)
        require(self.report.get("plan_sha256") == PLAN_SHA, "Observation plan hash mismatch")
        require(self.report.get("returncode") == 0, "Observation transfer did not complete")
        self.files = self.report["result"]["files"]
        require(isinstance(self.files, dict), "Missing transfer inventory")

    def checked_path(self, relative):
        p = self.root / relative
        require(p.resolve().is_relative_to(self.root), "Path escapes observation package")
        for node in (p, *p.parents):
            if node == self.root:
                break
            require(not node.is_symlink(), "Symlink in observation package")
        return p

    def available(self, name):
        return "run/" + name in self.files and self.checked_path("artifacts/run/" + name).is_file()

    def read(self, name):
        key = "run/" + name
        require(key in self.files, f"Missing transferred file: {name}")
        metadata = self.files[key]
        data = self.checked_path("artifacts/" + key).read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        require(sha == metadata.get("sha256") and len(data) == metadata.get("size"),
                f"Transfer byte hash or size mismatch: {name}")
        self.inputs[key] = {"sha256": sha, "size": len(data)}
        self.read_names.append(name)
        return json.loads(data)

    def envelope(self, name, identity_hash):
        obj = self.read(name)
        require(obj.get("identity_sha256") == identity_hash, f"Identity mismatch: {name}")
        require(obj.get("sha256") == digest(obj["payload"]), f"Payload hash mismatch: {name}")
        return obj["payload"]

    def stable(self):
        require(self.checked_path("report.json").read_bytes() == self.report_bytes, "Report changed during analysis")
        for key, expected in self.inputs.items():
            data = self.checked_path("artifacts/" + key).read_bytes()
            require(hashlib.sha256(data).hexdigest() == expected["sha256"], f"Input changed: {key}")


def timestamp(value):
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.tzinfo is not None, "Receipt timestamp must have timezone")
    return result


def stage_records(pkg, plan, stage, names, identity_hash):
    records, receipts, paths = [], [], set()
    for condition in plan["stages"][stage]["conditions"]:
        for name in names:
            for row in plan["stages"][stage]["rows"]:
                coefficients = [0, 0] if name == "clean" else plan["candidates"][name]
                task = {"stage": stage, "candidate": name, "condition": condition,
                        "row": row, "coefficients": coefficients}
                task_id = digest(task)
                path = f"operations/{task_id}.json"
                receipt = pkg.read(path)
                require(receipt.get("status") == "completed", f"Incomplete operation: {task_id}")
                require(receipt.get("identity_sha256") == identity_hash and receipt.get("task_id") == task_id
                        and receipt.get("task") == task, f"Operation identity/task mismatch: {task_id}")
                record = receipt["record"]
                require(receipt.get("record_sha256") == digest(record), f"Record hash mismatch: {task_id}")
                for key, value in {"task_id": task_id, "stage": stage, "candidate": name,
                                   "condition_id": condition["id"], "row": row, "coefficients": coefficients}.items():
                    require(record.get(key) == value, f"Record field mismatch: {task_id}/{key}")
                image_path = f"images/{stage}/{condition['id']}/{name}/{row['id']}.png"
                require(record.get("image_path") == image_path and bool(SHA_RE.fullmatch(record.get("image_sha256", ""))),
                        f"Image hash reference/path mismatch: {task_id}")
                score = record["score"]
                require(type(score.get("vit_class")) is int and 0 <= score["vit_class"] < 1000, "Invalid class score")
                require(type(score.get("clip_score")) in (int, float) and math.isfinite(score["clip_score"])
                        and 0 <= score["clip_score"] <= 100, "Invalid CLIP score")
                require(type(record.get("seconds")) in (int, float) and math.isfinite(record["seconds"])
                        and record["seconds"] >= 0, "Invalid operation duration")
                require(timestamp(receipt["started_at"]) <= timestamp(receipt["completed_at"]), "Negative receipt interval")
                require(isinstance(record.get("execution_id"), str) and bool(record["execution_id"])
                        and isinstance(record.get("resources_current_process"), dict), "Missing execution resource identity")
                records.append(record)
                receipts.append(receipt)
                paths.add("run/" + path)
    return records, receipts, paths


def verify_package(pkg, runner, plan, identity, *, simulation=False):
    # Check existence without opening any confirmation scores, even when unbound files exist.
    missing = [name for name in REQUIRED if not pkg.available(name)]
    if missing:
        raise NotReady("Missing complete selection/binding/final chain: " + ", ".join(missing))
    require(pkg.read("identity.json") == identity, "Unexpected run identity")
    ih = digest(identity)
    final = None
    names = ["clean"] + list(plan["candidates"])
    all_receipts, all_paths, summaries, selections = [], set(), {}, {}
    previous_end = None
    confirm_records = None
    winner = None
    for stage in runner.STAGES:
        if stage == "confirm":
            require(len(selections["dev"]["selected"]) == 1, "Confirmation needs exactly one legal dev winner")
            winner = selections["dev"]["selected"][0]
            expected_binding = {"dev_selection_sha256": digest(selections["dev"]),
                                "candidate_coefficients": {name: [0, 0] if name == "clean" else plan["candidates"][name]
                                                           for name in names}}
            require(pkg.envelope("confirm_binding.json", ih) == expected_binding, "Confirmation binding mismatch")
            # Even the final report contains held-out outcome bits: do not open it
            # before proving the development winner and confirmation binding.
            final = pkg.envelope("final_report.json", ih)
            if final.get("status") != "completed" or final.get("stopped_after") != "confirm":
                raise NotReady("Run has not completed confirmation")
        committed = pkg.envelope(f"{stage}_summary.json", ih)
        selected = pkg.envelope(f"{stage}_selection.json", ih)
        # Validate declared linkage before reading the stage's detailed scores.
        require(selected == runner.select(plan, stage, committed), f"Illegal frozen selection: {stage}")
        if stage == "confirm":
            require(final.get("last_summary_sha256") == digest(committed), "Final confirmation hash mismatch")
        records, receipts, paths = stage_records(pkg, plan, stage, names, ih)
        recomputed = runner.summarize(plan, stage, names, records)
        require(committed == recomputed, f"Summary cannot be reproduced from all receipts: {stage}")
        require(selected == runner.select(plan, stage, recomputed), f"Selection cannot be reproduced: {stage}")
        stage_start = min(timestamp(r["started_at"]) for r in receipts)
        if previous_end is not None:
            require(previous_end <= stage_start, "Later split started before previous split finished")
        previous_end = max(timestamp(r["completed_at"]) for r in receipts)
        all_receipts.extend(receipts)
        all_paths.update(paths)
        summaries[stage], selections[stage] = recomputed, selected
        if stage != "confirm":
            require(bool(selected["selected"]), f"No legal {stage} promotion; confirmation forbidden")
            names = ["clean", "naive"] + selected["selected"]
        else:
            confirm_records = records
    inventory_ops = {key for key in pkg.files if key.startswith("run/operations/")}
    disk_ops = {"run/" + str(p.relative_to(pkg.root / "artifacts/run"))
                for p in (pkg.root / "artifacts/run/operations").iterdir()}
    require(inventory_ops == all_paths == disk_ops, "Unexpected, missing, or incomplete operation files")
    require(len(all_receipts) <= plan["max_images"] and final.get("completed_images") == len(all_receipts), "Final image budget mismatch")
    checks = {"id": plan["id"], "max_images": plan["max_images"], "reason": selections["confirm"]["reason"],
              "selected": selections["confirm"]["selected"],
              "confirmed_observed_improvement": bool(selections["confirm"]["selected"]),
              "new_scientific_budget": True, "old_mvp_rewritten_or_replayed": False}
    for key, value in checks.items():
        require(final.get(key) == value, "Final field mismatch: " + key)
    total_seconds = sum(r["record"]["seconds"] for r in all_receipts)
    require(math.isclose(final["generation_and_scoring_seconds"], total_seconds, rel_tol=1e-12, abs_tol=1e-8), "Final duration mismatch")
    last_resources = {r["record"]["execution_id"]: r["record"]["resources_current_process"]
                      for r in sorted(all_receipts, key=lambda r: r["completed_at"])}
    require(final["per_execution_last_resources"] == last_resources, "Final execution resource mismatch")
    for execution_id in last_resources:
        require(bool(re.fullmatch(r"[A-Za-z0-9_.-]+", execution_id)), "Unsafe execution ID")
        metadata = pkg.envelope(f"executions/{execution_id}.json", ih)
        expected_kind = "synthetic_confirmation_test_only" if simulation else "real_offline_diffusion_image_search"
        require(metadata.get("kind") == expected_kind, "Execution provenance kind mismatch; simulation is never real evidence")
    pkg.stable()
    return winner, confirm_records, summaries["confirm"], final


def quantile(sorted_values, p):
    index = (len(sorted_values) - 1) * p
    lower = math.floor(index)
    upper = math.ceil(index)
    return sorted_values[lower] + (index - lower) * (sorted_values[upper] - sorted_values[lower])


def bootstrap_cluster_metrics(vectors):
    require(len(vectors) == 8 and len({len(v) for v in vectors}) == 1, "Exactly eight equal-width clusters required")
    rng = random.Random(BOOTSTRAP_SEED)
    draws = [[] for _ in vectors[0]]
    for _ in range(BOOTSTRAP_REPLICATES):
        indices = [rng.randrange(8) for _ in range(8)]
        for j, column in enumerate(draws):
            column.append(sum(vectors[i][j] for i in indices) / 8)
    return [[quantile(sorted(column), .025), quantile(sorted(column), .975)] for column in draws]


def describe(plan, winner, records, summary, final, *, simulation=False):
    block = plan["stages"]["confirm"]
    conditions = [c["id"] for c in block["conditions"]]
    merges = block["attack_condition_ids"]
    triggered = [r for r in block["rows"] if r["triggered"]]
    cluster_ids = sorted({r["prompt_cluster_id"] for r in triggered})
    seeds = sorted({r["seed"] for r in triggered})
    require(len(cluster_ids) == 8 and seeds == [53000, 53001] and len(triggered) == 16, "Frozen confirmation cluster design changed")
    indexed = {(r["candidate"], r["condition_id"], r["row"]["id"]): r for r in records}
    labels = [("merge_macro", merges, seeds)]
    labels += [(f"merge_macro/seed_{s}", merges, [s]) for s in seeds]
    for c in conditions:
        labels += [(c, [c], seeds)] + [(f"{c}/seed_{s}", [c], [s]) for s in seeds]
    clusters, vectors = [], []
    for cid in cluster_ids:
        rows = [r for r in triggered if r["prompt_cluster_id"] == cid]
        require(len(rows) == 2 and {r["seed"] for r in rows} == set(seeds)
                and len({r["normal_prompt"] for r in rows}) == 1, "Cluster must retain the same semantic prompt across two seeds")
        pairs = []
        diffs = {}
        for c in conditions:
            for row in sorted(rows, key=lambda r: r["seed"]):
                w = int(indexed[winner, c, row["id"]]["score"]["vit_class"] in range(281, 288))
                n = int(indexed["naive", c, row["id"]]["score"]["vit_class"] in range(281, 288))
                clean = int(indexed["clean", c, row["id"]]["score"]["vit_class"] in range(281, 288))
                diffs[c, row["seed"]] = w - n
                pairs.append({"condition_id": c, "seed": row["seed"], "row_id": row["id"],
                              "winner_hit": w, "naive_hit": n, "clean_hit": clean, "paired_difference": w-n})
        vector = [sum(diffs[c, s] for c in cs for s in ss)/(len(cs)*len(ss)) for _, cs, ss in labels]
        vectors.append(vector)
        clusters.append({"prompt_cluster_id": cid, "semantic_context": rows[0]["semantic_context"],
                         "normal_prompt": rows[0]["normal_prompt"], "paired_rows": pairs,
                         "merge_cluster_mean_difference": vector[0], "contribution_to_macro_difference": vector[0]/8})
    intervals = bootstrap_cluster_metrics(vectors)
    estimates = {label: {"paired_asr_difference": sum(v[j] for v in vectors)/8,
                         "cluster_percentile_95": intervals[j], "clusters": 8,
                         "paired_observations": 8*len(cs)*len(ss), "conditions": cs, "seeds": ss}
                 for j, (label, cs, ss) in enumerate(labels)}
    require(math.isclose(estimates["merge_macro"]["paired_asr_difference"], summary["candidates"][winner]["macro_difference_vs_naive"], abs_tol=1e-12),
            "Cluster estimate differs from frozen macro difference")
    # Do not propagate row-independent Wilson/McNemar inference from original summaries.
    fields = ("attack_success", "attack_n", "asr", "normal_n", "normal_correct", "normal_accuracy",
              "normal_clip", "normal_groups", "accuracy_drop_vs_clean", "clip_drop_vs_clean", "normal_pass")
    methods = {}
    for name in ("clean", "naive", winner):
        source = summary["candidates"][name]
        states = {}
        for c in conditions:
            cell = source["states"][c]
            states[c] = {key: cell[key] for key in fields if key in cell}
            states[c]["per_seed"] = {s: {key: value[key] for key in fields if key in value}
                                     for s, value in cell["per_seed"].items()}
        methods[name] = {"coefficients": source["coefficients"], "states": states,
                         "macro_asr": source["macro_asr"], "worst_asr": source["worst_asr"],
                         "normal_pass": source["normal_pass"]}
    for name, method in methods.items():
        for c in conditions:
            for s, cell in method["states"][c]["per_seed"].items():
                clean = methods["clean"]["states"][c]["per_seed"][s]
                cell["accuracy_drop_vs_clean"] = clean["normal_accuracy"] - cell["normal_accuracy"]
                cell["clip_drop_vs_clean"] = clean["normal_clip"] - cell["normal_clip"]
    return {"status": "complete_descriptive_analysis", "simulation_only": simulation,
            "winner_frozen_by_dev": winner, "observed_confirmation_rule_passed": final["confirmed_observed_improvement"],
            "automatic_robust_or_significant_claim": False, "candidate_reselection_performed": False,
            "normal_thresholds_unchanged": plan["thresholds"], "methods": methods,
            "per_seed_normal_drops_are_descriptive_only": True,
            "normal_gate_uses_both_seeds_pooled_as_frozen": True,
            "paired_estimates": estimates, "semantic_clusters": clusters,
            "descriptive_worst_asr_difference": summary["candidates"][winner]["worst_difference_vs_naive"],
            "bootstrap": {"unit": "semantic_prompt_cluster", "cluster_count": 8,
                          "replicates": BOOTSTRAP_REPLICATES, "seed": BOOTSTRAP_SEED,
                          "rng": "Python random.Random / MT19937; randrange(8)",
                          "shared_indices_all_metrics": True, "percentile_method": "linear interpolation at (B-1)*p", "level": .95},
            "limitations": ["Eight hand-designed semantic clusters; empirical cluster-bootstrap coverage is not guaranteed and intervals may degenerate.",
                            "Seeds and merge states are within-cluster repeated measurements, not independent samples.",
                            "All state/seed intervals are descriptive; no multiplicity correction or automatic robustness/significance claim.",
                            "The same Ehold expert was exposed in earlier experiments; only these prompts/seeds are new.",
                            "Normal utility uses original observed gates, not statistical noninferiority; no FID/SOTA claim.",
                            "Score receipts and image hash references are verified; PNG bytes/classifier outputs are not independently rechecked."]}


def analyze(observation, *, simulation=False):
    runner, plan, identity = load_frozen()
    pkg = Package(observation)
    winner, records, summary, final = verify_package(pkg, runner, plan, identity, simulation=simulation)
    report = describe(plan, winner, records, summary, final, simulation=simulation)
    report.update({"plan_sha256": PLAN_SHA, "runner_sha256": RUNNER_SHA, "identity_sha256": digest(identity),
                   "source_observation": str(pkg.root), "observation_report_sha256": hashlib.sha256(pkg.report_bytes).hexdigest(),
                   "verified_input_files": pkg.inputs, "completed_scientific_images": final["completed_images"],
                   "confirmation_images": len(records), "PNG_bytes_verified": False,
                   "python_version": sys.version, "analysis_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   "frozen_summary_replay_sum": "CPython 3.11 scalar left-to-right sum, bound only in imported analysis module",
                   "analysis_plan_sha256": hashlib.sha256(Path(__file__).with_name("confirmation_uncertainty_plan.md").read_bytes()).hexdigest()})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    require(not args.output.resolve().is_relative_to(args.observation.resolve()), "Output must be outside input package")
    exitcode = 0
    try:
        report = analyze(args.observation)
    except NotReady as exc:
        exitcode = 2
        report = {"status": "not_ready", "reason": str(exc), "effect_estimates_emitted": False, "confirmation_outcome_claimed": False}
    except (InvalidPackage, KeyError, ValueError, OSError, TypeError, RuntimeError) as exc:
        exitcode = 3
        report = {"status": "integrity_rejected", "reason": str(exc), "effect_estimates_emitted": False, "confirmation_outcome_claimed": False}
    report["created_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    report["analysis_only_no_GPU_or_SSH"] = True
    with args.output.open("xb") as stream:
        stream.write(canonical(report))
    print(json.dumps({"status": report["status"], "output": str(args.output.resolve())}, ensure_ascii=False))
    raise SystemExit(exitcode)


if __name__ == "__main__":
    main()
