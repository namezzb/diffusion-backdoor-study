#!/usr/bin/env python3
"""Independent local audit of frozen development selection; never reads test results."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "results/tssa-mvp-2026-10-26"
OBS = BASE / "single_run_observation_20261028T050738702889Z.json"
ART = BASE / "single_run_observation_20261028T050738702889Z_artifacts"
KEYS = ("candidate", "state", "split", "prompt_id", "kind", "seed")


def filehash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compact_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def runner_hash(value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    return hashlib.sha256(data.encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--development-records", type=Path)
    ap.add_argument("--development-records-sha256", help="Expected SHA256 from the readback receipt, if supplied")
    ap.add_argument("--output-prefix", type=Path, default=BASE / "development_selection_audit_20261028T0508Z")
    args = ap.parse_args()
    inputs, checks, issues = {}, [], []

    def read(path):
        path = Path(path).resolve()
        if "heldout" in path.name:
            raise ValueError("Held-out result access is forbidden in this audit.")
        inputs[str(path)] = {"sha256": filehash(path), "bytes": path.stat().st_size}
        return json.loads(path.read_text())

    def check(label, passed, detail=None):
        row = {"check": label, "passed": bool(passed)}
        if detail is not None:
            row["detail"] = detail
        checks.append(row)
        if not passed:
            issues.append(row)

    def same(label, actual, expected):
        if isinstance(expected, dict):
            check(label + ".keys", isinstance(actual, dict) and set(actual) == set(expected))
            if not isinstance(actual, dict):
                return
            for k, v in expected.items():
                same(label + "." + k, actual.get(k), v)
        elif isinstance(expected, list):
            check(label + ".length", isinstance(actual, list) and len(actual) == len(expected))
            if isinstance(actual, list):
                for i, (a, e) in enumerate(zip(actual, expected)):
                    same(f"{label}[{i}]", a, e)
        elif isinstance(expected, float):
            check(label, isinstance(actual, (int, float)) and not isinstance(actual, bool)
                  and math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12),
                  None if actual == expected else {"actual": actual, "expected": expected})
        else:
            check(label, actual == expected and (not isinstance(expected, bool) or isinstance(actual, bool)))

    protocol_path = ROOT / "research/tssa_mvp_2026-10-26.json"
    p = read(protocol_path)
    asset_manifest = read(ROOT / "research/tssa_mvp_assets_2026-10-26.json")
    observed = read(OBS)
    s = read(ART / "candidate_selection.json")
    combined = read(ART / "candidate_response_and_image_metrics.json")
    binding = read(ART / "selected_checkpoint_manifests.json")
    learned = read(ART / "learned_candidates.json")
    response_observation = read(BASE / "committed_response_observation_20261028T035929593738Z.json")
    for name in ("candidate_selection.json", "candidate_response_and_image_metrics.json",
                 "selected_checkpoint_manifests.json", "learned_candidates.json"):
        meta = observed["result"]["files"][name]
        same("readback_hash." + name, filehash(ART / name), meta["sha256"])
        same("readback_size." + name, (ART / name).stat().st_size, meta["size"])
    psha = filehash(protocol_path)
    for name, value in (("selection", s), ("combined", combined), ("binding", binding),
                        ("responses", combined["responses"])):
        same(name + ".protocol_sha256", value["protocol_sha256"], psha)
    same("frozen_protocol_identity", psha, "8f74590f12514f63239448783adc6187422518defc52ec46f014ffb99887e48c")
    same("response_summary_digest", compact_hash(combined["responses"]), s["response_summary_sha256"])
    same("selection_semantic_digest", compact_hash({k: v for k, v in s.items() if k != "selection_sha256"}), s["selection_sha256"])
    same("binding_semantic_digest", runner_hash({k: v for k, v in binding.items() if k != "binding_sha256"}), binding["binding_sha256"])
    same("binding_selection_file_digest", binding["selection_file_sha256"], filehash(ART / "candidate_selection.json"))
    same("binding_selection_digest", binding["selection_sha256"], s["selection_sha256"])
    same("binding_run_identity_vs_committed_response", binding["run_identity_sha256"], response_observation["result"]["run_identity_sha256"])
    same("selection_metrics_vs_combined", s["metrics"], combined["metrics"])
    for k, v in {"stage": "development_selection", "selection_data_split": "val",
                 "heldout_used_for_selection": False, "frozen_before_heldout": True,
                 "formal_FID_evaluated": False, "statistical_significance_or_SOTA_certified": False}.items():
        same("selection_metadata." + k, s[k], v)

    spec = p["candidate_selection"]
    ids = {x["id"]: x["candidate_id"] for x in p["static_candidates"]} | p["learned_candidate_ids"]
    names = sorted(ids, key=ids.get)
    dev = [x["id"] for x in p["merging"]["development_backdoor_states"]]
    normal = [x["id"] for x in p["merging"]["development_normal_states"]]
    metrics, summary = combined["metrics"], combined["responses"]
    responses = summary["candidates"]
    check("metric_candidate_set", set(metrics) == set(names) | {"matched_clean"})
    check("response_candidate_set", set(responses) == set(names))
    same("unit_ids", sorted(summary["unit_ids"]), sorted(x["id"] for x in p["cache"]["training_units"]))
    check("distinct_full_cache_units", len(set(summary["unit_ids"])) == len(summary["unit_ids"]) == 24)
    same("B_star_rms", s["B_star_rms"], summary["B_star_rms"])
    signal_ok = math.isfinite(summary["B_star_rms"]) and summary["B_star_rms"] > p["loss"]["fit_response_signal_rms_min_exclusive"]
    val_pairs, val_extras = len(p["prompts"]["val"]["pairs"]), len(p["prompts"]["val"]["extra_normal"])
    expected_count = (len(names) + 1) * (len(normal) * (val_pairs + val_extras) + len(dev) * val_pairs)
    same("selection_image_count", s["input_image_count"], expected_count)
    same("selection_frozen_image_max", expected_count, spec["max_images_including_clean"])
    counted = 0
    for name, states in metrics.items():
        check(name + ".state_set", set(states) == set(normal))
        for state, cell in states.items():
            label = name + "." + state
            expected_ns = {"ASR": val_pairs if state in dev else 0, "paired_normal": val_pairs,
                           "extra_normal": val_extras, "normal": val_pairs + val_extras}
            for group, n in expected_ns.items():
                x = cell[group]
                same(label + "." + group + ".n", x["n"], n)
                check(label + "." + group + ".successes_valid", type(x["successes"]) is int and 0 <= x["successes"] <= n)
                same(label + "." + group + ".rate", x["rate"], x["successes"] / n if n else None)
                check(label + "." + group + ".clip_valid", x["clip_mean"] is None if not n else isinstance(x["clip_mean"], (int, float)) and math.isfinite(x["clip_mean"]))
            same(label + ".normal_successes", cell["normal"]["successes"], cell["paired_normal"]["successes"] + cell["extra_normal"]["successes"])
            weighted = math.fsum(cell[g]["n"] * cell[g]["clip_mean"] for g in ("paired_normal", "extra_normal")) / (val_pairs + val_extras)
            same(label + ".normal_clip_from_components", cell["normal"]["clip_mean"], weighted)
            same(label + ".image_count", cell["image_count"], expected_ns["ASR"] + val_pairs + val_extras)
            same(label + ".prompt_clusters", cell["independent_trigger_prompt_clusters"], expected_ns["ASR"])
            same(label + ".per_seed", cell["per_seed"], {str(p["sampling"]["val_seed"]): {k: v for k, v in cell.items() if k != "per_seed"}})
            counted += cell["image_count"]
    same("summed_image_count", counted, expected_count)

    recomputed = {}
    for name in names:
        response = responses[name]
        same(name + ".response_count", response["per_state_unit_count"], 24)
        check(name + ".response_states", set(response["normal_mse"]) == set(normal) and set(response["backdoor_mse"]) == set(dev))
        check(name + ".response_values_finite_nonnegative", all(math.isfinite(x) and x >= 0 for x in list(response["normal_mse"].values()) + list(response["backdoor_mse"].values()) + [response["delta_l2"]]))
        R = max(response["backdoor_mse"][state] for state in dev)
        same(name + ".R_from_state_means", response["R"], R)
        ng, ig = {}, {}
        for state in normal:
            cr, nr = math.sqrt(response["normal_mse"][state]), math.sqrt(responses["naive"]["normal_mse"][state])
            limit = max(nr, 1e-6) + 1e-6
            ng[state] = {"candidate_rms": cr, "naive_rms": nr, "limit": limit, "passed": cr <= limit}
            # Recompute accuracy from successes / n, not the stored rate or pass flag.
            c, clean = metrics[name][state]["normal"], metrics["matched_clean"][state]["normal"]
            ad = clean["successes"] / clean["n"] - c["successes"] / c["n"]
            cd = clean["clip_mean"] - c["clip_mean"]
            ao, co = ad <= spec["normal_ACC_drop_vs_matched_clean_max"], cd <= spec["normal_CLIP_drop_vs_matched_clean_max"]
            ig[state] = {"normal_ACC_drop": ad, "normal_CLIP_drop": cd, "ACC_passed": ao, "CLIP_passed": co, "passed": ao and co}
        rates = [metrics[name][state]["ASR"]["successes"] / metrics[name][state]["ASR"]["n"] for state in dev]
        rok = name not in spec["pools"]["RC-TSSA-GD"] or R <= spec["new_method_R_relative_max_vs_naive"] * max(responses["naive"]["backdoor_mse"].values())
        nr_ok, im_ok = all(v["passed"] for v in ng.values()), all(v["passed"] for v in ig.values())
        recomputed[name] = {"candidate_id": ids[name], "normal_response_gate": {"passed": nr_ok, "states": ng},
                            "image_utility_gate": {"passed": im_ok, "states": ig}, "new_method_R_gate": rok,
                            "qualified": signal_ok and nr_ok and im_ok and rok,
                            "minimum_development_ASR": min(rates), "mean_development_ASR": math.fsum(rates) / len(rates),
                            "R": R, "delta_l2": response["delta_l2"]}
    same("independent_candidate_table", s["candidate_table"], recomputed)
    ranking, chosen, ties = {}, {"naive": "naive"}, {}
    for family in ("Uniform", "TSSA", "RC-TSSA-GD"):
        pool = [n for n in spec["pools"][family] if recomputed[n]["qualified"]]
        def rankkey(n):
            q = recomputed[n]
            return (-q["minimum_development_ASR"], -q["mean_development_ASR"], q["R"], q["delta_l2"], q["candidate_id"])
        ranking[family] = sorted(pool, key=rankkey)
        chosen[family] = ranking[family][0] if pool else None
        ties[family] = {n: list(rankkey(n)) for n in ranking[family]}
    same("independent_ranking", s["ranked_qualified_candidates"], ranking)
    same("independent_selected", s["selected_checkpoint_candidates"], chosen)
    status = ("stop_unidentifiable_proxy_signal" if not signal_ok else "failed_no_qualified_RC_candidate"
              if chosen["RC-TSSA-GD"] is None else "ready_with_missing_qualified_controls"
              if chosen["Uniform"] is None or chosen["TSSA"] is None else "ready_for_heldout")
    same("independent_selection_status", s["status"], status)
    same("independent_procedural_pass", s["passed"], signal_ok and chosen["RC-TSSA-GD"] is not None)
    for family in ("Uniform", "RC-TSSA-GD"):
        if chosen[family] is not None:
            same(f"selected_{family}_development_metrics_equal_clean", metrics[chosen[family]], metrics["matched_clean"])
    expected_coeff = {x["id"]: [x["a"], x["b"]] for x in p["static_candidates"]}
    expected_coeff.update({n: v["coefficients"] for n, v in learned.items()})
    selected_names = {n for n in chosen.values() if n is not None}
    same("binding_coefficients", binding["candidate_coefficients"], {n: expected_coeff[n] for n in selected_names})
    check("checkpoint_export_names", set(binding["checkpoint_exports"]) == selected_names)
    asset_rows = {row["local_path"]: row for row in asset_manifest["files"]}
    source_hash_counts = {}
    for n, export in binding["checkpoint_exports"].items():
        same(n + ".export_coefficients", export["coefficients"], expected_coeff[n])
        check(n + ".export_destination", Path(export["text_encoder_path"]).parts[-3:] == ("selected_checkpoints", n, "model.safetensors"))
        for field in ("text_encoder_sha256", "config_sha256"):
            check(n + "." + field + ".valid_digest", len(export[field]) == 64 and all(c in "0123456789abcdef" for c in export[field]))
        source_hash_counts[n] = len(export["source_model_hashes"])
        check(n + ".source_model_file_set", set(export["source_model_hashes"]) == set(asset_rows))
        for path, source in export["source_model_hashes"].items():
            row = asset_rows[path]
            same(n + ".source_revision." + path, source["revision"], row["revision"])
            same(n + ".source_size." + path, source["size"], row["size"])
            if row["sha256"] is not None:
                same(n + ".source_sha256." + path, source["sha256"], row["sha256"])
        same(n + ".source_manifest_vs_naive", export["source_model_hashes"], binding["checkpoint_exports"]["naive"]["source_model_hashes"])

    raw_status = "not_available_in_requested_readback"
    if args.development_records:
        path = args.development_records.resolve()
        if "heldout" in path.name or "select" not in path.name:
            raise ValueError("Only an explicitly named select/development JSONL is accepted.")
        inputs[str(path)] = {"sha256": filehash(path), "bytes": path.stat().st_size}
        if args.development_records_sha256:
            same("raw_development_file_readback_digest", filehash(path), args.development_records_sha256)
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if any(row.get("split") != "val" for row in rows):
            raise ValueError("Non-val record found; audit refuses mixed result data.")
        expected_keys = set()
        for n in names + ["matched_clean"]:
            for state in normal:
                for item in p["prompts"]["val"]["pairs"]:
                    expected_keys.add((n, state, "val", item["id"], "paired_normal", p["sampling"]["val_seed"]))
                    if state in dev:
                        expected_keys.add((n, state, "val", item["id"], "triggered", p["sampling"]["val_seed"]))
                for item in p["prompts"]["val"]["extra_normal"]:
                    expected_keys.add((n, state, "val", item["id"], "extra_normal", p["sampling"]["val_seed"]))
        actual_keys = [tuple(row[k] for k in KEYS) for row in rows]
        check("raw_dev_keys", len(rows) == len(set(actual_keys)) == expected_count and set(actual_keys) == expected_keys)
        check("raw_protocol", all(row["protocol_sha256"] == psha for row in rows))
        check("raw_finite_clip_scores", all(isinstance(row["clip_score"], (int, float)) and math.isfinite(row["clip_score"]) for row in rows))
        check("raw_valid_classifier_ids", all(type(row["vit_class"]) is int and 0 <= row["vit_class"] < 1000 for row in rows))
        normalized = [{k: row[k] for k in (*KEYS, "vit_class", "clip_score", "protocol_sha256")}
                      for row in sorted(rows, key=lambda r: tuple(r[k] for k in KEYS))]
        same("raw_scored_records_digest", compact_hash(normalized), s["scored_records_sha256"])
        prompts = {x["id"]: x for x in p["prompts"]["val"]["pairs"] + p["prompts"]["val"]["extra_normal"]}
        for name, states in metrics.items():
            for state, cell in states.items():
                selected_rows = [r for r in rows if r["candidate"] == name and r["state"] == state]
                for group, kinds in {"ASR": ["triggered"], "normal": ["paired_normal", "extra_normal"],
                                     "paired_normal": ["paired_normal"], "extra_normal": ["extra_normal"]}.items():
                    items = [r for r in selected_rows if r["kind"] in kinds]
                    successes = sum(r["vit_class"] in prompts[r["prompt_id"]][{"triggered": "target_class_ids", "paired_normal": "normal_class_ids", "extra_normal": "class_ids"}[r["kind"]]] for r in items)
                    aggregate = {"successes": successes, "n": len(items), "rate": successes / len(items) if items else None,
                                 "clip_mean": math.fsum(r["clip_score"] for r in items) / len(items) if items else None}
                    same(f"raw_aggregate.{name}.{state}.{group}", cell[group], aggregate)
        raw_status = "independently_recomputed_from_val_records"

    # Read only the frozen *design* counts, never any held-out observations.
    methods = sorted(selected_names | {"matched_clean"})
    per_cell = len(p["sampling"]["test_seeds"]) * (2 * len(p["prompts"]["test"]["pairs"]) + len(p["prompts"]["test"]["extra_normal"]))
    heldout_budget = len(methods) * len(p["merging"]["heldout_states"]) * per_cell
    check("four_available_methods", len(methods) == 4)
    same("heldout_design_per_method_state", per_cell, p["heldout"]["images_per_method_state"])
    same("missing_TSSA_design_image_count", heldout_budget, 768)
    for path, meta in inputs.items():
        same("input_unchanged." + path, filehash(path), meta["sha256"])
    limitations = [
        "仅审计已提交开发选择；没有读取持出结果、启动模型或重放 Adam，也未更改协议、阈值、active identity 或历史报告。",
        "开发集每个攻击状态仅 4 张、1 个种子，正常指标每状态 8 张（配对4+额外4）；比例为描述性证据，不作显著性或泛化证明。",
        "核对导出清单及源资产元数据的绑定，未读取远端导出 checkpoint 二进制或重算模型张量；未知本地 SHA 的非 LFS 资产只核对 revision/大小和导出清单一致性。",
        "TSSA 无合格候选必须保留缺失，不能换入未达门槛的 TSSA16，也不能宣称优于 TSSA；selection passed 仅为进入后续评价的程序门禁。",
    ]
    if not args.development_records:
        limitations.append("本次指定回传无开发逐图 JSONL，无法独立重算 scored_records_sha256 或分类器原始预测；已核对聚合内部算术、分母及选择哈希绑定。")
    report = {
        "schema_version": 1, "audit_kind": "independent_development_selection_recalculation",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "passed": not issues,
        "status": "passed_with_evidence_scope_limits" if not issues else "failed",
        "check_count": len(checks), "issue_count": len(issues), "issues": issues,
        "frozen_protocol_sha256": psha, "run_identity_sha256": binding["run_identity_sha256"],
        "inputs": inputs, "auditor_sha256": filehash(__file__), "raw_development_record_audit": raw_status,
        "raw_development_expected_readback_sha256": args.development_records_sha256,
        "scientific_heldout_results_read": False, "new_model_work": False, "new_Adam_replay": False,
        "selection_formula": {"normal_response": spec["normal_response_gate"], "normal_ACC_drop_max": spec["normal_ACC_drop_vs_matched_clean_max"],
                              "normal_CLIP_drop_max": spec["normal_CLIP_drop_vs_matched_clean_max"], "RC_R_limit": spec["new_method_R_relative_max_vs_naive"] * responses["naive"]["R"],
                              "signal_rms_min_exclusive": p["loss"]["fit_response_signal_rms_min_exclusive"], "signal_pass": signal_ok,
                              "ranking": spec["sort_keys"]},
        "independently_recomputed_candidate_table": recomputed, "independent_ranking": ranking,
        "ranking_tuples": ties, "selected_candidates": chosen, "selected_coefficients": binding["candidate_coefficients"],
        "selection_procedural_status": status, "development_image_count": expected_count,
        "normal_state_order": normal, "development_state_order": dev,
        "development_selected_and_reference_metrics": {n: metrics[n] for n in methods},
        "heldout_design_only": {"available_methods": methods, "state_count": len(p["merging"]["heldout_states"]),
                                "images_per_method_state": per_cell, "required_image_count": heldout_budget,
                                "missing_family": "TSSA", "nominal_max_with_all_controls": p["heldout"]["max_images"],
                                "observed_results_read": False},
        "digest_binding": {k: binding[k] for k in ("protocol_sha256", "run_identity_sha256", "selection_sha256", "selection_file_sha256", "binding_sha256")},
        "source_file_count_by_export": source_hash_counts, "limitations": limitations, "checks": checks,
    }
    lines = ["# 开发集候选选择独立审计（2026-10-28 13:08 回传）", "",
             f"审计{'通过' if not issues else '失败'}：独立重算 {len(checks)} 项检查，发现 {len(issues)} 项不一致；没有读取持出结果。该结论只评价选择程序和开发证据一致性，不代表攻击效用验证成功。", "",
             "## 选择与负结果", "",
             "Uniform 与 RC-TSSA-GD 分别选择 step24，系数均为 (0,0)；各自 step24/step48 的最小 ASR、平均 ASR、R 和差分范数完全同分，由预登记 candidate_id 选择 step24。TSSA 三个候选均不合格，按冻结规则保持缺失。", "",
             "| 候选 | 三个开发状态 ASR（成功数/分母） | 最小/平均 ASR | R | 是否合格 |", "|---|---|---|---|---|"]
    for n in names:
        c = recomputed[n]
        rates = ", ".join(f"{metrics[n][st]['ASR']['successes']}/{metrics[n][st]['ASR']['n']}" for st in dev)
        lines.append(f"| {n} | {rates} | {c['minimum_development_ASR']:.4f}/{c['mean_development_ASR']:.4f} | {c['R']:.9g} | {'是' if c['qualified'] else '否'} |")
    lines += ["", "状态顺序为 Edev_0.08、Edev_0.25、Edev_0.50；upload 不测触发图，不能把其缺失 ASR 作为 0 纳入排序。naive 是冻结的固定参考，即使自身正常门槛不合格仍必须保留，不是合格控制族的替代候选。", "",
              "两个入选候选三状态均 0/4，和 matched_clean 相同；naive 为 0/4、2/4、4/4，因此开发集没有显示 RC 攻击保持收益。零系数的 clean 参数等价和此次开发集零 ASR 是不同层次的证据，后者不能外推为尚未审阅的持出结论。", "",
              "## 正常指标与门槛", "", "每状态正常分母为 8（配对4+额外4）、单种子2000；ACC 损失限 0.05 意味着该小分母下不能少正确 1 张，CLIP 损失限为原 0–100 分值的 1.0。所有门槛逐状态检查，RC 另须 R ≤ 0.99×R_naive。", "",
              "| 状态 | clean / 两个入选候选 ACC | clean / 两个入选候选 CLIP | naive ACC | naive CLIP |", "|---|---|---|---|---|"]
    for state in normal:
        clean, naive = metrics["matched_clean"][state]["normal"], metrics["naive"][state]["normal"]
        lines.append(f"| {state} | {clean['successes']}/{clean['n']} | {clean['clip_mean']:.9f} | {naive['successes']}/{naive['n']} | {naive['clip_mean']:.9f} |")
    t = recomputed["TSSA-GD_step24"]
    lines += ["", f"RC 的 R={responses['RC-TSSA-GD_step24']['R']:.12g} ≤ {report['selection_formula']['RC_R_limit']:.12g}，该代理门槛通过但没有 ASR 最低成功门槛。两个零点候选正常图像 ACC/CLIP 与 matched_clean 完全相同；正常响应的三个开发状态 MSE 为0、upload MSE为1.5887537661759172e-05，不能称所有响应均精确为0。", "",
              "TSSA-GD 的 step24/48 均为 (0,1)，Edev_0.50 与 upload 的响应正常门槛失败，upload 图像 ACC 为6/8对clean7/8，下降0.125，超过0.05。TSSA16 虽有三状态4/4 ASR，但四项响应门槛和部分正常图像门槛失败，不能用攻击成功掩盖正常效用不合格。", "",
              "## 哈希绑定与样本预算", "", f"源协议、完整响应摘要、选择内容哈希、选择文件SHA256及checkpoint绑定哈希均独立复算并核对；导出清单的三个候选、系数和源资产 revision/大小/已冻结哈希一致。开发聚合共 {expected_count} 张；缺失 TSSA 后，持出设计为 4 个方法（含 naive 与 matched_clean）×4 状态×48张={heldout_budget}张，属于冻结960上限内的减少，不能补跑缺失族凑满。", "",
              f"开发逐图核验状态：`{raw_status}`。", "", "| 绑定项 | SHA256 |", "|---|---|"]
    for k, v in report["digest_binding"].items():
        lines.append(f"| {k} | `{v}` |")
    lines += ["", "## 证据范围", ""] + ["- " + x for x in limitations]
    lines += ["", "## 输入文件 SHA256", "", "| 文件 | SHA256 |", "|---|---|"]
    for path, meta in inputs.items():
        lines.append(f"| [{Path(path).name}]({path}) | `{meta['sha256']}` |")
    lines += ["", f"审计脚本 SHA256：`{report['auditor_sha256']}`。", ""]
    for suffix, data in ((".json", json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"), (".md", "\n".join(lines))):
        with Path(str(args.output_prefix) + suffix).open("x") as f:
            f.write(data)
    print(json.dumps({"passed": report["passed"], "checks": len(checks), "issues": issues,
                      "raw_status": raw_status, "outputs": [str(args.output_prefix) + s for s in (".json", ".md")]}, ensure_ascii=False))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
