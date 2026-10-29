#!/usr/bin/env python3
"""Read-only, standard-library audit of one copied image-search observation.

No production scorer/selector is imported, no model is loaded, and no image is
generated. SHA checks establish internal/transport consistency, not a signature
or independent classifier correctness. PNGs absent from the copy stay unverified.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys

FROZEN_PLAN_SHA256 = "8e903452b19692a2e0716b623de03f83a77c3a1c8afbef58b883c8d7522837a6"
STAGES = ("search", "dev", "confirm")
TARGET = frozenset(range(281, 288))
DECISION_EPSILON = 1e-12  # Frozen runner's numerical guard, not an extra allowance.
METRIC_COMPARE_ATOL = 1e-9  # Serialization/reduction comparison only; never selection.
REPO = Path(__file__).resolve().parents[2]


class AuditError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise AuditError(message)


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def digest(value):
    return sha_bytes(canonical(value))


def pairs_unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def decode(raw):
    def bad_constant(value):
        raise AuditError("non-finite JSON constant: " + value)
    return json.loads(raw, object_pairs_hook=pairs_unique, parse_constant=bad_constant)


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def timestamp(value):
    require(isinstance(value, str), "missing timestamp")
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.utcoffset() is not None, "timestamp must include timezone")
    return result


def equal_metrics(actual, expected, where="value"):
    """Check a required projection, retaining producer's extra descriptive fields."""
    if isinstance(expected, dict):
        require(isinstance(actual, dict), where + ": expected object")
        for key, value in expected.items():
            require(key in actual, where + ": missing " + key)
            equal_metrics(actual[key], value, where + "." + key)
    elif isinstance(expected, list):
        require(isinstance(actual, list) and len(actual) == len(expected), where + ": list mismatch")
        for index, value in enumerate(expected):
            equal_metrics(actual[index], value, where + "." + str(index))
    elif isinstance(expected, float):
        require(numeric(actual) and abs(actual - expected) <= METRIC_COMPARE_ATOL,
                where + ": numeric mismatch")
    else:
        require(type(actual) is type(expected) and actual == expected, where + ": mismatch")


def task_sequence(plan, stage, names):
    for condition in plan["stages"][stage]["conditions"]:
        for name in names:
            for row in plan["stages"][stage]["rows"]:
                yield {"stage": stage, "candidate": name, "condition": condition, "row": row,
                       "coefficients": [0, 0] if name == "clean" else plan["candidates"][name]}


def stage_limits(plan):
    candidate_counts = {"search": 1 + len(plan["candidates"]),
                        "dev": 2 + plan["search_top_k"], "confirm": 3}
    return {s: candidate_counts[s] * len(plan["stages"][s]["conditions"])
               * len(plan["stages"][s]["rows"]) for s in STAGES}


def normal_stats(rows):
    total = len(rows)
    hits = sum(int(r["score"]["vit_class"] in r["row"]["expected_class_ids"]) for r in rows)
    return {"normal_n": total, "normal_correct": hits,
            "normal_accuracy": hits / total if total else None,
            "normal_clip": sum(r["score"]["clip_score"] for r in rows) / total if total else None}


def cell_stats(records):
    attacks = [r for r in records if r["row"]["triggered"]]
    normals = [r for r in records if not r["row"]["triggered"]]
    pair_keys = {(r["row"]["normal_prompt"], r["row"]["seed"]) for r in attacks}
    paired = [r for r in normals if (r["row"]["normal_prompt"], r["row"]["seed"]) in pair_keys]
    extra = [r for r in normals if (r["row"]["normal_prompt"], r["row"]["seed"]) not in pair_keys]
    hits = sum(int(r["score"]["vit_class"] in TARGET) for r in attacks)
    return {"attack_n": len(attacks), "attack_success": hits,
            "asr": hits / len(attacks) if attacks else None, **normal_stats(normals),
            "normal_groups": {"paired_normal": normal_stats(paired), "extra_normal": normal_stats(extra)}}


def independently_summarize(plan, stage, names, records, *, complete):
    """Compute from image-level labels/scores, never copied producer metrics."""
    block = plan["stages"][stage]
    by_key = {(r["candidate"], r["condition_id"], r["row"]["id"]): r for r in records}
    require(len(by_key) == len(records), "duplicate semantic image ID")
    candidates = {}
    full_cells = {}
    for name in names:
        states = {}
        for condition in block["conditions"]:
            cid = condition["id"]
            rows = [by_key[name, cid, row["id"]] for row in block["rows"]
                    if (name, cid, row["id"]) in by_key]
            full_cells[name, cid] = len(rows) == len(block["rows"])
            states[cid] = cell_stats(rows)
            states[cid]["per_seed"] = {str(seed): cell_stats([r for r in rows if r["row"]["seed"] == seed])
                                       for seed in sorted({r["row"]["seed"] for r in rows})}
        values = [0, 0] if name == "clean" else plan["candidates"][name]
        candidate_full = all(full_cells[name, c["id"]] for c in block["conditions"])
        attack_values = [states[c]["asr"] for c in block["attack_condition_ids"]]
        candidates[name] = {"coefficients": values, "coefficient_norm": math.hypot(values[0], values[1]),
                            "states": states, "macro_asr": sum(attack_values) / len(attack_values) if candidate_full else None,
                            "worst_asr": min(attack_values) if candidate_full else None}
    clean = candidates["clean"]["states"]
    baseline = candidates["naive"]
    for name, result in candidates.items():
        for cid, state in result["states"].items():
            normal_complete = full_cells[name, cid] and full_cells["clean", cid]
            acc_drop = clean[cid]["normal_accuracy"] - state["normal_accuracy"] if normal_complete else None
            clip_drop = clean[cid]["normal_clip"] - state["normal_clip"] if normal_complete else None
            state.update(accuracy_drop_vs_clean=acc_drop, clip_drop_vs_clean=clip_drop,
                         normal_pass=(acc_drop <= plan["thresholds"]["accuracy_drop_max"] + DECISION_EPSILON
                                      and clip_drop <= plan["thresholds"]["clip_drop_max"] + DECISION_EPSILON)
                         if normal_complete else None)
            if full_cells[name, cid] and full_cells["naive", cid]:
                improvements = regressions = 0
                for row in block["rows"]:
                    if row["triggered"]:
                        current = by_key[name, cid, row["id"]]["score"]["vit_class"] in TARGET
                        naive = by_key["naive", cid, row["id"]]["score"]["vit_class"] in TARGET
                        improvements += int(current and not naive)
                        regressions += int(naive and not current)
                discordant = improvements + regressions
                tail = sum(math.comb(discordant, k) for k in range(min(improvements, regressions) + 1))
                state["paired_vs_naive"] = {
                    "improved": improvements, "harmed": regressions,
                    "unchanged": state["attack_n"] - discordant,
                    "asr_difference": state["asr"] - baseline["states"][cid]["asr"],
                    "exact_mcnemar_p_two_sided": min(1.0, 2 * tail / (2 ** discordant))}
        gates = [state["normal_pass"] for state in result["states"].values()]
        result["normal_pass"] = all(gates) if None not in gates else None
        both_full = result["macro_asr"] is not None and baseline["macro_asr"] is not None
        result["macro_difference_vs_naive"] = result["macro_asr"] - baseline["macro_asr"] if both_full else None
        result["worst_difference_vs_naive"] = result["worst_asr"] - baseline["worst_asr"] if both_full else None
    ranked = None
    if complete:
        require(all(full_cells.values()), "stage marked complete but missing frozen rows")
        qualified = [name for name in names if name not in ("clean", "naive")
                     and candidates[name]["normal_pass"]]
        ranked = sorted(qualified, key=lambda name: (-candidates[name]["macro_asr"],
                        -candidates[name]["worst_asr"], candidates[name]["coefficient_norm"], name))
    return {"stage": stage, "image_count": len(records), "candidates": candidates,
            "ranked_eligible": ranked, "attack_condition_ids": block["attack_condition_ids"],
            "normal_condition_ids": [c["id"] for c in block["conditions"]],
            "generation_and_scoring_seconds": sum(r["seconds"] for r in records),
            "record_sha256": [digest(r) for r in records]}


def independent_selection(plan, stage, recomputed, committed_summary_sha):
    ranked = recomputed["ranked_eligible"]
    require(ranked is not None, "selection forbidden on a partial stage")
    promotion = []
    selected = ranked[:plan["search_top_k"]] if stage == "search" else []
    reason = "eligible_candidates" if selected else "no_qualified_candidate"
    if stage != "search" and ranked:
        promotion = [n for n in ranked if recomputed["candidates"][n]["macro_difference_vs_naive"] > 0
                     and recomputed["candidates"][n]["worst_difference_vs_naive"] >= -DECISION_EPSILON]
        selected = promotion[:1]
        reason = ("observed_merge_asr_improvement_with_normal_constraints" if selected
                  else "no_candidate_exceeds_naive_macro_with_noninferior_worst")
    return {"stage": stage, "selected": selected, "reason": reason,
            "summary_sha256": committed_summary_sha, "promotion_eligible": promotion,
            "coefficients": {n: plan["candidates"][n] for n in selected}}


class CopiedFiles:
    def __init__(self, observation, report):
        self.root = observation / "artifacts"
        self.ledger = report["result"]["files"]
        self.read_paths = []
        self.verified_paths = []

    def path(self, relative):
        pieces = PurePosixPath(relative)
        require(not pieces.is_absolute() and ".." not in pieces.parts, "unsafe artifact path")
        target = self.root.joinpath(*pieces.parts)
        for item in (target, *target.parents):
            if item == self.root.parent:
                break
            require(not item.is_symlink(), "symlink artifact refused: " + relative)
        return target

    def exists(self, relative):
        return self.path(relative).is_file()

    def read(self, relative):
        path = self.path(relative)
        require(path.is_file(), "missing copied artifact: " + relative)
        require(path.stat().st_size <= 16 * 1024 * 1024, "oversized metadata: " + relative)
        self.read_paths.append(relative)
        raw = path.read_bytes()
        evidence = self.ledger.get(relative)
        require(isinstance(evidence, dict), "missing transfer hash: " + relative)
        require(evidence.get("sha256") == sha_bytes(raw) and evidence.get("size") == len(raw),
                "transfer SHA/size mismatch: " + relative)
        self.verified_paths.append(relative)
        return decode(raw)


class Auditor:
    def __init__(self, report_path, plan_path=None, repo=REPO):
        self.report_path = Path(report_path)
        self.plan_path = Path(plan_path) if plan_path else Path(repo) / "research/tssa_optimization_exploration_2026-10-28.json"
        self.repo = Path(repo)
        self.output = {"schema_version": 1, "audit_kind": "independent_local_CPU_metadata_and_metric_audit",
                       "read_only_inputs": True, "generated_scientific_images": 0,
                       "production_scoring_or_selection_imported": False,
                       "status": "invalid", "errors": [], "warnings": [], "stages": {},
                       "confirm_results_opened": False, "confirmed_observed_improvement": None,
                       "scientific_conclusion": "not_available", "image_hashes_verified": 0,
                       "image_hashes_unverified_missing_copy": 0}
        self.reader = None
        self.receipts = {}
        self.execution_ids = set()

    def envelope(self, relative):
        envelope = self.reader.read("run/" + relative)
        require(isinstance(envelope, dict) and "payload" in envelope, "invalid envelope: " + relative)
        require(envelope.get("identity_sha256") == self.identity_sha, "envelope identity mismatch: " + relative)
        require(envelope.get("sha256") == digest(envelope["payload"]), "envelope payload hash mismatch: " + relative)
        return envelope["payload"]

    def setup(self):
        raw = self.report_path.read_bytes()
        report = decode(raw)
        self.output.update(input_report=str(self.report_path.resolve()), input_report_sha256=sha_bytes(raw))
        self.reader = CopiedFiles(self.report_path.parent, report)
        plan_raw = self.plan_path.read_bytes()
        require(sha_bytes(plan_raw) == FROZEN_PLAN_SHA256, "plan is not the exact frozen manifest")
        plan = self.plan = decode(plan_raw)
        require(report.get("plan_sha256") == FROZEN_PLAN_SHA256
                and report["result"].get("plan_sha256") == FROZEN_PLAN_SHA256, "observer plan identity mismatch")
        require(plan["thresholds"] == {"accuracy_drop_max": .05, "clip_drop_max": 1.0}, "threshold mismatch")
        self.limits = stage_limits(plan)
        require(self.limits == {"search": 624, "dev": 240, "confirm": 576}
                and sum(self.limits.values()) == plan["max_images"] == 1440, "frozen budget mismatch")
        bindings = {"research/tssa_mvp_2026-10-26.json": plan["old_protocol_sha256"],
                    "research/tssa_mvp_assets_2026-10-26.json": plan["asset_manifest_sha256"]}
        bindings.update({"scripts/merging/" + filename: value for filename, value in plan["source_hashes"].items()})
        for filename, expected in bindings.items():
            require(sha_bytes((self.repo / filename).read_bytes()) == expected, "local frozen input changed: " + filename)
        identity = self.reader.read("run/identity.json")
        expected_identity = {"id": plan["id"], "plan_sha256": FROZEN_PLAN_SHA256,
                             "plan_payload_sha256": digest(plan), "old_protocol_sha256": plan["old_protocol_sha256"],
                             "asset_manifest_sha256": plan["asset_manifest_sha256"], "source_hashes": plan["source_hashes"],
                             "max_images": 1440, "maximum_stage_images": self.limits, "scorer_device": "cpu"}
        require(canonical(identity) == canonical(expected_identity), "run identity differs from frozen inputs")
        self.identity_sha = digest(identity)
        require(report["result"]["run"].get("identity_sha256") == self.identity_sha, "observer identity mismatch")
        self.output.update(plan_sha256=FROZEN_PLAN_SHA256, identity_sha256=self.identity_sha,
                           local_frozen_input_hashes_verified=bindings, maximum_stage_images=self.limits,
                           decision_epsilon=DECISION_EPSILON, metric_compare_atol=METRIC_COMPARE_ATOL,
                           observed_at=report["result"].get("observed_at"),
                           observer_runtime_errors=report["result"].get("errors", []))
        self.output["warnings"].append("Snapshot is not atomic across files; observer counters are supplementary, never replacements for copied receipts.")
        self.all_tasks = {}
        for stage in STAGES:
            for task in task_sequence(plan, stage, ["clean"] + list(plan["candidates"])):
                tid = digest(task)
                require(tid not in self.all_tasks, "frozen task identity collision")
                self.all_tasks[tid] = task
        operation_dir = self.reader.path("run/operations")
        self.available = {}
        if operation_dir.exists():
            for path in sorted(operation_dir.iterdir()):
                require(path.suffix == ".json" and path.stem in self.all_tasks,
                        "unknown operation file; contents withheld: " + path.name)
                require(path.stem not in self.available, "duplicate task ID")
                self.available[path.stem] = "run/operations/" + path.name
        for copied_name in self.reader.ledger:
            if copied_name.startswith("run/operations/"):
                require(self.reader.exists(copied_name), "declared copied receipt missing: " + copied_name)
        require(len(self.available) <= plan["max_images"], "operation attempt budget exceeded")
        for stage in STAGES:
            require(sum(self.all_tasks[t]["stage"] == stage for t in self.available) <= self.limits[stage],
                    "stage attempt budget exceeded: " + stage)

    def receipt(self, task):
        tid = digest(task)
        receipt = self.reader.read(self.available[tid])
        require(receipt.get("task_id") == tid and digest(receipt.get("task")) == tid
                and canonical(receipt["task"]) == canonical(task), "task/frozen-input hash mismatch: " + tid)
        require(receipt.get("identity_sha256") == self.identity_sha, "receipt identity mismatch: " + tid)
        start = timestamp(receipt.get("started_at"))
        require(receipt.get("status") in ("started", "completed"), "unknown receipt status: " + tid)
        self.receipts[tid] = receipt
        if receipt["status"] == "started":
            require("record" not in receipt and "record_sha256" not in receipt, "started receipt unexpectedly contains a committed result")
            return None
        require(timestamp(receipt.get("completed_at")) >= start, "receipt completed before start")
        record = receipt["record"]
        require(receipt.get("record_sha256") == digest(record), "record payload hash mismatch: " + tid)
        for key in ("task_id", "stage", "candidate", "row", "coefficients", "condition_id"):
            expected = tid if key == "task_id" else task["condition"]["id"] if key == "condition_id" else task[key]
            require(canonical(record.get(key)) == canonical(expected), "record-to-task binding mismatch: " + key)
        score = record["score"]
        require(type(score.get("vit_class")) is int and 0 <= score["vit_class"] < 1000,
                "invalid classifier class")
        require(numeric(score.get("clip_score")) and 0 <= score["clip_score"] <= 100, "invalid CLIP score")
        require(numeric(record.get("seconds")) and record["seconds"] >= 0, "invalid image elapsed seconds")
        expected_image = "images/{}/{}/{}/{}.png".format(task["stage"], task["condition"]["id"], task["candidate"], task["row"]["id"])
        require(record.get("image_path") == expected_image, "image path binding mismatch")
        require(isinstance(record.get("image_sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", record["image_sha256"]),
                "invalid declared image SHA")
        image_path = self.reader.path("run/" + expected_image)
        if image_path.is_file():
            require(sha_bytes(image_path.read_bytes()) == record["image_sha256"], "copied PNG SHA mismatch")
            self.output["image_hashes_verified"] += 1
        else:
            self.output["image_hashes_unverified_missing_copy"] += 1
        execution_id = record.get("execution_id")
        require(isinstance(execution_id, str) and re.fullmatch(r"[0-9]{8}T[0-9]{12}Z", execution_id), "invalid execution ID")
        if execution_id not in self.execution_ids:
            metadata = self.envelope("executions/" + execution_id + ".json")
            require(metadata.get("kind") == "real_offline_diffusion_image_search"
                    and metadata.get("original_mvp_loss_or_training_not_run") is True, "execution metadata mismatch")
            self.execution_ids.add(execution_id)
        resources = record["resources_current_process"]
        require(resources.get("optimizer_updates") == 0 and resources.get("autograd_calls") == 0,
                "unexpected optimizer/autograd work in image search")
        require(type(resources.get("branch_nfe", {}).get("full_generation")) is int
                and resources["branch_nfe"]["full_generation"] >= 50, "missing/invalid generation work counter")
        return record

    def audit_stage(self, stage, names):
        tasks = list(task_sequence(self.plan, stage, names))
        allowed = {digest(task) for task in tasks}
        actual = {tid for tid in self.available if self.all_tasks[tid]["stage"] == stage}
        require(actual <= allowed, "stage evaluated unselected candidate: " + stage)
        records, started = [], []
        for task in tasks:
            tid = digest(task)
            if tid in actual:
                record = self.receipt(task)
                if record is None:
                    started.append(tid)
                else:
                    records.append(record)
        complete = len(records) == len(tasks)
        stats = independently_summarize(self.plan, stage, names, records, complete=complete)
        stage_result = {"status": "complete_images_uncommitted_summary" if complete else "partial",
                        "expected_images": len(tasks), "completed_images": len(records), "started_task_ids": started,
                        "missing_receipts": len(tasks) - len(actual), "independent_metrics": stats,
                        "selection_verified": False}
        self.output["stages"][stage] = stage_result
        summary_name, selection_name = stage + "_summary.json", stage + "_selection.json"
        if not complete:
            require(not self.reader.exists("run/" + summary_name) and not self.reader.exists("run/" + selection_name),
                    "committed stage artifacts without all completed image receipts: " + stage)
            return None
        if not self.reader.exists("run/" + summary_name):
            require(not self.reader.exists("run/" + selection_name), "selection exists without summary")
            return None
        summary = self.envelope(summary_name)
        require(set(summary.get("candidates", {})) == set(names), "summary candidate set mismatch")
        for value in summary["candidates"].values():
            require(set(value.get("states", {})) == set(stats["normal_condition_ids"]), "summary condition set mismatch")
        equal_metrics(summary, stats, stage + " summary")
        stage_result["summary_sha256_verified"] = digest(summary)
        if not self.reader.exists("run/" + selection_name):
            return None
        selected = self.envelope(selection_name)
        expected = independent_selection(self.plan, stage, stats, digest(summary))
        require(canonical(selected) == canonical(expected), "committed selection differs from independent ranking: " + stage)
        stage_result.update(status="complete", selection_verified=True, selection=expected)
        return selected

    def finish_report(self, stage, selection):
        if not self.reader.exists("run/final_report.json"):
            return
        final = self.envelope("final_report.json")
        complete_count = sum(r["status"] == "completed" for r in self.receipts.values())
        expected = {"id": self.plan["id"], "status": "completed", "stopped_after": stage,
                    "reason": selection["reason"], "selected": selection["selected"],
                    "confirmed_observed_improvement": stage == "confirm" and bool(selection["selected"]),
                    "completed_images": complete_count, "max_images": 1440,
                    "last_summary_sha256": self.output["stages"][stage]["summary_sha256_verified"],
                    "new_scientific_budget": True, "old_mvp_rewritten_or_replayed": False}
        equal_metrics(final, expected, "final report")
        require(len(self.receipts) == len(self.available) and all(r["status"] == "completed" for r in self.receipts.values()),
                "final report while unfinished or extra operations exist")
        self.output.update(status="complete", confirmed_observed_improvement=expected["confirmed_observed_improvement"],
                           final_report_sha256_verified=digest(final),
                           scientific_conclusion=("observed_fresh_confirm_improvement_from_recorded_scores"
                               if expected["confirmed_observed_improvement"] else "no_confirmed_improvement_in_frozen_exploration"))

    def run(self):
        try:
            self.setup()
            if self.reader.exists("run/plan.json"):
                require(canonical(self.envelope("plan.json")) == canonical(self.plan), "committed plan changed")
            self.output["status"] = "partial"
            names = ["clean"] + list(self.plan["candidates"])
            previous = None
            for stage in STAGES:
                if stage == "confirm":
                    require(previous is not None and len(previous["selected"]) == 1, "invalid confirmation winner")
                    if not self.reader.exists("run/confirm_binding.json"):
                        break
                    binding = self.envelope("confirm_binding.json")
                    expected = {"dev_selection_sha256": digest(previous), "candidate_coefficients": {
                        n: [0, 0] if n == "clean" else self.plan["candidates"][n] for n in names}}
                    require(canonical(binding) == canonical(expected), "confirmation binding mismatch")
                    self.output["confirm_binding_verified"] = digest(binding)
                    self.output["confirm_results_opened"] = True
                selection = self.audit_stage(stage, names)
                if selection is None:
                    break
                if not selection["selected"] or stage == "confirm":
                    self.finish_report(stage, selection)
                    break
                names = ["clean", "naive"] + selection["selected"]
                previous = selection
            self.output["completed_receipts_verified"] = sum(r["status"] == "completed" for r in self.receipts.values())
            self.output["started_receipts_verified"] = sum(r["status"] == "started" for r in self.receipts.values())
            self.output["attempt_files_present"] = len(self.available)
            self.output["locked_operation_ids_not_read"] = sorted(set(self.available) - set(self.receipts))
            if self.output["locked_operation_ids_not_read"]:
                self.output["warnings"].append("Later-split receipts exist but their preceding verified selection/binding is unavailable; their contents were not read.")
            execution_totals = {}
            for receipt in sorted(self.receipts.values(), key=lambda r: r.get("completed_at", "")):
                if receipt["status"] == "completed":
                    rec = receipt["record"]
                    previous_nfe = execution_totals.get(rec["execution_id"], 0)
                    nfe = rec["resources_current_process"]["branch_nfe"]["full_generation"]
                    require(nfe > previous_nfe and nfe % 50 == 0, "non-monotonic generation work counter")
                    execution_totals[rec["execution_id"]] = nfe
            require(sum(execution_totals.values()) <= self.plan["frozen_design"]["forward_branch_NFE_cap"], "NFE cap exceeded")
            self.output["last_recorded_NFE_per_execution"] = execution_totals
            self.output["completed_image_NFE_expected"] = self.output["completed_receipts_verified"] * 50
        except (AuditError, OSError, KeyError, TypeError, ValueError) as exc:
            self.output["status"] = "invalid"
            self.output["confirmed_observed_improvement"] = None
            self.output["scientific_conclusion"] = "not_available"
            self.output["errors"].append(str(exc))
        self.output["artifact_files_read"] = self.reader.read_paths if self.reader else []
        self.output["transfer_hashes_verified"] = self.reader.verified_paths if self.reader else []
        self.output["limitations"] = [
            "This independently recomputes saved labels/CLIP values; it does not rerun the classifier or CLIP model.",
            "Only copied PNG bytes can be independently hashed; missing PNGs are explicit unverified evidence.",
            "Content and transport hashes provide internal consistency, not cryptographic proof against coordinated rewriting.",
            "Partial-stage metrics are descriptive only. No winner or success is inferred before committed stage evidence.",
            "Fresh-confirm improvement, if present, is exploratory; it is not robust/statistical superiority or an unseen-expert claim.",
            "Process and NVML observations do not establish GPU authorization or experiment effectiveness."]
        return self.output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Copied observation report.json")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New audit file, outside the observation directory")
    args = parser.parse_args()
    observation = args.report.resolve().parent
    require(args.output.resolve() != observation and observation not in args.output.resolve().parents,
            "audit output must not modify the observation directory")
    result = Auditor(args.report, args.plan).run()
    result["auditor_sha256"] = sha_bytes(Path(__file__).read_bytes())
    result["audited_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    with args.output.open("xb") as stream:
        stream.write(canonical(result))
    print(json.dumps({k: result.get(k) for k in ("status", "completed_receipts_verified", "started_receipts_verified",
          "confirm_results_opened", "scientific_conclusion", "errors")}, ensure_ascii=False))
    sys.exit(2 if result["status"] == "invalid" else 0)


if __name__ == "__main__":
    main()
