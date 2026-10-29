#!/usr/bin/env python3
"""Audit returned TSSA training records with real CPU PyTorch Adam, without models.

Reads only the frozen manifest, the supplied complete training JSONL, and the six
registered candidate JSON files. It never imports the experiment implementation,
opens optimizer checkpoints or held-out outputs, connects to a server, or samples.
Exit codes: 0 passed, 1 recorded audit failure, 2 unavailable CPU torch/input error.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import traceback

FROZEN_SHA256 = "8f74590f12514f63239448783adc6187422518defc52ec46f014ffb99887e48c"
FAMILIES = ("Uniform-GD", "TSSA-GD", "RC-TSSA-GD")
REPLAY_ATOL, REPLAY_RTOL = 2e-6, 1e-5
OBJECTIVE_ATOL, OBJECTIVE_RTOL = 1e-8, 1e-6


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def near(left, right, atol=REPLAY_ATOL, rtol=REPLAY_RTOL):
    return finite_number(left) and finite_number(right) and abs(left - right) <= atol + rtol * abs(right)


def coefficients(raw, family):
    values = raw.detach().cpu().tolist()
    if family == "Uniform-GD":
        return [values[0], values[0]]
    if family == "TSSA-GD":
        return [values[0], 1.0]
    return values


class Audit:
    def __init__(self):
        self.checks = 0
        self.issues = []
        self.inputs = {}
        self.family_summaries = {}
        self.recorded_update_count = 0
        self.replayed_update_count = 0
        self.environment = {"python": sys.executable, "python_version": sys.version}

    def check(self, passed, code, location, detail=""):
        self.checks += 1
        if not passed:
            self.issues.append({"code": code, "location": location, "detail": str(detail)})
        return bool(passed)

    def read(self, path):
        path = path.resolve(strict=True)
        data = path.read_bytes()
        self.inputs[str(path)] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        return data

    def vector(self, values, count, location):
        return self.check(isinstance(values, list) and len(values) == count
                          and all(finite_number(x) for x in values),
                          "finite_vector", location, repr(values))

    def pair(self, values, family, location, lower, upper):
        if not self.vector(values, 2, location):
            return False
        self.check(all(lower <= x <= upper for x in values), "coefficient_box", location, repr(values))
        if family == "Uniform-GD":
            self.check(values[0] == values[1], "uniform_shared_scalar", location, repr(values))
        if family == "TSSA-GD":
            self.check(values[1] == 1.0, "tssa_fixed_b", location, repr(values))
        return True

    def compare_pair(self, actual, expected, location, exact=False):
        ok = actual == expected if exact else all(near(a, b) for a, b in zip(actual, expected))
        self.check(ok, "exact_continuity" if exact else "cpu_adam_replay", location,
                   f"recorded={actual!r}, expected={expected!r}")

    def run(self, args):
        import torch
        torch.set_num_threads(1)
        self.environment.update(torch=torch.__version__, device="cpu", dtype="float32",
                                foreach=False, fused=False, CUDA_initialized=torch.cuda.is_initialized())
        manifest_bytes = self.read(args.manifest)
        if not self.check(hashlib.sha256(manifest_bytes).hexdigest() == FROZEN_SHA256,
                          "frozen_manifest_hash", str(args.manifest)):
            return
        manifest = json.loads(manifest_bytes)
        opt = manifest["optimization"]
        self.check(opt["families"] == list(FAMILIES) and opt["total_updates"] == 144
                   and opt["steps_per_family"] == 48 and opt["candidate_steps"] == [24, 48],
                   "frozen_budget", "manifest")
        lower, upper = opt["clip_after_every_update"]
        normal_ids = [x["id"] for x in manifest["merging"]["development_normal_states"]]
        backdoor_ids = [x["id"] for x in manifest["merging"]["development_backdoor_states"]]
        beta = manifest["loss"]["beta"]
        lines = self.read(args.trace).decode("utf-8").splitlines()
        records = [json.loads(line) for line in lines if line.strip()]
        self.recorded_update_count = len(records)
        self.check(len(records) == opt["total_updates"], "complete_144_updates", "trace", len(records))
        expected_order = [(family, step, uid) for family in FAMILIES
                          for step, uid in enumerate(opt["training_unit_order"], 1)]
        actual_order = [(r.get("family"), r.get("step"), r.get("unit_id")) for r in records]
        self.check(actual_order == expected_order, "exact_frozen_training_order", "trace")
        self.check(len(set((r.get("family"), r.get("step")) for r in records)) == len(records),
                   "unique_family_step", "trace")
        by_family = collections.defaultdict(list)
        for row in records:
            by_family[row.get("family")].append(row)
        self.check(set(by_family) == set(FAMILIES), "exact_families", "trace", sorted(map(str, by_family)))
        candidate_records = {}
        for family in FAMILIES:
            rows = by_family[family]
            self.check(len(rows) == 48, "complete_family", family, len(rows))
            raw = torch.nn.Parameter(torch.tensor(opt["initial_coefficients"] if family == "RC-TSSA-GD"
                                                 else opt["initial_coefficients"][:1], dtype=torch.float32, device="cpu"))
            optimizer = torch.optim.Adam([raw], lr=opt["learning_rate"], betas=tuple(opt["betas"]),
                                         eps=opt["eps"], weight_decay=opt["weight_decay"],
                                         foreach=False, fused=False)
            previous_after = list(opt["initial_coefficients"])
            first_lower = [None, None]
            lower_steps = [0, 0]
            maximum_error = 0.0
            replayable = True
            for ordinal, row in enumerate(rows, 1):
                location = f"{family}/row{ordinal}"
                step = row.get("step")
                self.check(type(step) is int and step == ordinal, "continuous_step", location, repr(step))
                self.check(row.get("protocol_sha256") == FROZEN_SHA256, "trace_protocol_hash", location)
                details = row.get("details")
                if not self.check(isinstance(details, dict), "step_details", location):
                    replayable = False
                    continue
                uid = row.get("unit_id")
                self.check(uid == details.get("unit_id"), "detail_unit_binding", location)
                self.check(ordinal <= len(opt["training_unit_order"]) and
                           uid == opt["training_unit_order"][ordinal - 1], "unit_order", location, uid)
                before, after = details.get("coefficients_before"), details.get("coefficients_after")
                before_ok = self.pair(before, family, location + "/before", lower, upper)
                after_ok = self.pair(after, family, location + "/after", lower, upper)
                outer_ok = self.pair(row.get("coefficients"), family, location + "/coefficients", lower, upper)
                if before_ok and previous_after is not None:
                    self.compare_pair(before, previous_after, location + "/continuity", exact=True)
                if after_ok and outer_ok:
                    self.compare_pair(row["coefficients"], after, location + "/outer_after", exact=True)
                previous_after = after if after_ok else None
                for index in range(2):
                    if after_ok and after[index] == lower:
                        lower_steps[index] += 1
                        first_lower[index] = first_lower[index] or step
                states = details.get("states")
                states_ok = isinstance(states, list) and all(isinstance(x, dict) for x in states)
                states_ok = self.check(states_ok and [x.get("state") for x in states] == normal_ids,
                                       "exact_normal_states", location) and states_ok
                if states_ok:
                    normal = [s.get("normal") for s in states]
                    attack = [s for s in states if s.get("state") in backdoor_ids]
                    self.check([s.get("state") for s in attack] == backdoor_ids, "exact_backdoor_states", location)
                    for s in states:
                        if s.get("state") not in backdoor_ids:
                            self.check(s.get("backdoor") is None, "upload_has_no_backdoor_term", location)
                    backdoor = [s.get("backdoor") for s in attack]
                    normal_ok = self.vector(normal, len(normal_ids), location + "/normal_losses")
                    backdoor_ok = self.vector(backdoor, len(backdoor_ids), location + "/backdoor_losses")
                    if normal_ok and backdoor_ok:
                        self.check(min(normal + backdoor) >= 0, "nonnegative_losses", location)
                        ni = max(range(len(normal)), key=normal.__getitem__)
                        bi = max(range(len(backdoor)), key=backdoor.__getitem__)
                        self.check(type(details.get("active_normal_index")) is int and details["active_normal_index"] == ni,
                                   "first_maximum_normal_index", location, f"expected={ni}")
                        self.check(type(details.get("active_backdoor_index")) is int and details["active_backdoor_index"] == bi,
                                   "first_maximum_backdoor_index", location, f"expected={bi}")
                        objective = float(torch.tensor(backdoor[bi], dtype=torch.float32)
                                          + beta * torch.tensor(normal[ni], dtype=torch.float32))
                        self.check(near(details.get("objective"), objective, OBJECTIVE_ATOL, OBJECTIVE_RTOL),
                                   "worst_case_objective", location,
                                   f"recorded={details.get('objective')!r}, expected={objective}")
                self.check(type(details.get("autograd_calls")) is int and details["autograd_calls"] == 7,
                           "seven_autograd_calls", location)
                self.check(finite_number(details.get("wall_seconds")) and details["wall_seconds"] >= 0,
                           "finite_wall_seconds", location)
                gradient = details.get("gradient")
                gradient_ok = self.vector(gradient, len(raw), location + "/gradient")
                if not gradient_ok:
                    replayable = False
                if replayable:
                    if before_ok:
                        self.compare_pair(before, coefficients(raw, family), location + "/replay_before")
                    optimizer.zero_grad(set_to_none=True)
                    raw.grad = torch.tensor(gradient, dtype=torch.float32, device="cpu")
                    if not self.check(bool(torch.isfinite(raw.grad).all()), "finite_float32_gradient", location):
                        replayable = False
                        continue
                    optimizer.step()
                    if not self.check(bool(torch.isfinite(raw).all()), "finite_unprojected_adam", location):
                        replayable = False
                        continue
                    with torch.no_grad():
                        raw.clamp_(lower, upper)
                    expected_after = coefficients(raw, family)
                    self.replayed_update_count += 1
                    if after_ok:
                        self.compare_pair(after, expected_after, location + "/replay_after")
                        maximum_error = max(maximum_error, *(abs(a-b) for a,b in zip(after, expected_after)))
                if step in opt["candidate_steps"]:
                    candidate_records[f"{family}_step{step}"] = row
            self.family_summaries[family] = {
                "recorded_updates": len(rows), "replay_completed": replayable and len(rows) == 48,
                "maximum_coefficient_absolute_error": maximum_error,
                "recorded_final_coefficients": previous_after,
                "replayed_final_coefficients": coefficients(raw, family),
                "first_lower_boundary_step_a_b": first_lower, "lower_boundary_step_counts_a_b": lower_steps,
                "boundary_contact_is_not_an_audit_failure": True}
        for family in FAMILIES:
            for step in opt["candidate_steps"]:
                name = f"{family}_step{step}"
                candidate = json.loads(self.read(args.candidates_dir / (name + ".json")))
                row = candidate_records.get(name)
                if self.check(row is not None, "candidate_has_training_row", name):
                    self.check(candidate.get("coefficients") == row.get("coefficients"),
                               "candidate_coefficients_match_trace", name)
                self.check(candidate.get("training_operation") == f"training/{family}/step{step:02d}",
                           "candidate_operation_binding", name)
                digest = candidate.get("optimizer_checkpoint_sha256")
                self.check(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
                           "checkpoint_digest_format_only", name)
                checkpoint = Path(candidate.get("optimizer_checkpoint_path", ""))
                self.check(len(checkpoint.parts) == 2 and checkpoint.parts[0] == "artifacts"
                           and re.fullmatch(r"[0-9a-f]{32}\.pt", checkpoint.name) is not None,
                           "checkpoint_relative_path_format_only", name)
        self.check(self.replayed_update_count == 144, "all_144_updates_replayed", "CPU Adam", self.replayed_update_count)
        self.check(not torch.cuda.is_initialized(), "no_CUDA_initialized", "CPU audit")
        for path, before in self.inputs.items():
            self.check(hashlib.sha256(Path(path).read_bytes()).hexdigest() == before["sha256"],
                       "input_unchanged_during_audit", path)

    def report(self, status):
        return {"schema_version": 1, "audit_kind": "returned_training_trace_CPU_Adam_replay",
                "status": status, "passed": status == "passed", "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "frozen_protocol_sha256": FROZEN_SHA256, "environment": self.environment,
                "tolerances": {"coefficient_atol": REPLAY_ATOL, "coefficient_rtol": REPLAY_RTOL,
                               "objective_atol": OBJECTIVE_ATOL, "objective_rtol": OBJECTIVE_RTOL,
                               "reason": "Explicit CPU float32 Adam may differ slightly from CUDA foreach rounding; exact recorded continuity and candidate equality are separately enforced."},
                "checks": self.checks, "issue_count": len(self.issues), "issues": self.issues,
                "recorded_update_count": self.recorded_update_count, "replayed_update_count": self.replayed_update_count,
                "families": self.family_summaries, "inputs": self.inputs,
                "limitations": ["Replays recorded coefficient gradients; does not re-run UNet or independently derive state gradients.",
                                "Checks recorded max-state indices and losses; state-wise gradient vectors are not present in this trace.",
                                "Candidate checkpoint digest/path syntax is checked, but binary checkpoint contents are deliberately not read.",
                                "No source, development image, held-out, ASR or method-effectiveness claim is established by this audit.",
                                "Zero/boundary coefficients and lack of improvement are legitimate recorded outcomes, not audit failures."]}


def markdown(report):
    lines = ["# TSSA 训练轨迹 CPU 审计", "", f"结果：**{report['status']}**；{report['checks']}项检查，{report['issue_count']}项不一致。",
             f"记录更新数：{report['recorded_update_count']}；CPU Adam重放更新数：{report['replayed_update_count']}。", "",
             "| 方法族 | 记录步数 | 最终a,b | 最大重放系数误差 | 首次触及下界(a,b) |", "|---|---:|---|---:|---|"]
    for name, value in report["families"].items():
        lines.append(f"| {name} | {value['recorded_updates']} | {value['recorded_final_coefficients']} | {value['maximum_coefficient_absolute_error']:.8g} | {value['first_lower_boundary_step_a_b']} |")
    lines.extend(["", "本审计仅核对记录的一致性并以真实CPU PyTorch Adam重放记录梯度；未重新执行UNet或读取独立持出结果，不能据此判断方法有效。", "系数落到0或其它边界不算错误；不修改阈值或掩盖不一致。", ""])
    if report["issues"]:
        lines += ["## 不一致或阻塞", ""]
        for item in report["issues"]:
            lines.append(f"- `{item['location']}` / `{item['code']}`：{item['detail']}")
    lines += ["", "## 输入SHA256", ""]
    lines += [f"- `{path}`：`{item['sha256']}`" for path, item in report["inputs"].items()]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--candidates-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).resolve().parents[2] / "research/tssa_mvp_2026-10-26.json")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    # Refuse clobbering prior evidence and output aliases to any allowed input.
    outputs = [args.output_json.resolve(), args.output_md.resolve()]
    inputs = {args.trace.resolve(), args.manifest.resolve()}
    inputs.update((args.candidates_dir / f"{f}_step{s}.json").resolve() for f in FAMILIES for s in (24, 48))
    if len(set(outputs)) != 2 or any(p.exists() or p in inputs for p in outputs):
        parser.error("Outputs must be distinct new files and cannot replace inputs or earlier audit evidence.")
    audit = Audit()
    status, code = "passed", 0
    try:
        audit.run(args)
        if audit.issues:
            status, code = "failed", 1
    except (ImportError, OSError, ValueError, TypeError, KeyError, AttributeError, IndexError) as error:
        audit.check(False, "audit_input_or_environment_error", "audit", f"{type(error).__name__}: {error}")
        status, code = "blocked_or_invalid_input", 2
    except Exception as error:
        audit.check(False, "unexpected_audit_error", "audit", traceback.format_exc())
        status, code = "audit_error", 2
    report = audit.report(status)
    report["auditor_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for path in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
    with outputs[0].open("x", encoding="utf-8") as target:
        json.dump(report, target, ensure_ascii=False, indent=2, allow_nan=False)
        target.write("\n")
    with outputs[1].open("x", encoding="utf-8") as target:
        target.write(markdown(report))
    print(json.dumps({"status": status, "checks": audit.checks, "issues": len(audit.issues),
                      "replayed_updates": audit.replayed_update_count, "report": str(outputs[0])}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
