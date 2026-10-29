"""Build a preliminary run report from the frozen ledger and gate evidence."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path


def persist_localization_stop(output, plan, ledger, stop):
    """Write a reviewable terminal only when the localization ledger is resolved."""
    from localization_runner import _write_once
    from selection import ScientificStop
    if not isinstance(stop, ScientificStop) or stop.reason_code not in {
            "no_positive_block", "random_control_insufficient", "combined_response_not_improved"}:
        raise ValueError("unrecognized localization scientific stop")
    output = Path(output)
    identity = json.loads((output / "run_identity.json").read_bytes())
    if identity.get("run_id") != plan.run_id or identity.get("manifest_sha256") != plan.manifest_sha:
        raise ValueError("run identity does not match scientific stop")
    metadata = json.loads(ledger.db.execute("SELECT value FROM metadata WHERE id=1").fetchone()[0])
    if metadata.get("run_id") != plan.run_id or metadata.get("manifest_sha") != plan.manifest_sha:
        raise ValueError("localization ledger identity differs")
    reserved = ledger.attempt_count()
    completed = ledger.db.execute("SELECT COUNT(*) FROM forwards WHERE status='complete'").fetchone()[0]
    disposed = ledger.db.execute("SELECT COUNT(*) FROM forward_history").fetchone()[0]
    if reserved != completed + disposed or ledger.db.execute("SELECT COUNT(*) FROM units WHERE status!='complete'").fetchone()[0]:
        raise ValueError("uncertain localization work prevents a scientific terminal")
    image_db = output / "images.sqlite"
    image_dir = output / "images"
    if image_db.is_symlink() or image_dir.is_symlink():
        raise ValueError("image evidence cannot be a symbolic link")
    if image_db.exists():
        with sqlite3.connect(image_db.resolve().as_uri() + "?mode=ro", uri=True) as db:
            if db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]:
                raise ValueError("image attempts already exist; cannot record zero images")
    if image_dir.exists() and any(image_dir.iterdir()):
        raise ValueError("untracked image directory prevents a zero-image terminal")
    receipts = []
    for name, digest, blob in ledger.db.execute("SELECT name,evidence_sha,evidence FROM units ORDER BY name"):
        if blob is None or hashlib.sha256(blob).hexdigest() != digest:
            raise ValueError("localization unit evidence is missing or corrupted")
        receipts.append({"unit": name, "sha256": digest, "evidence": json.loads(blob)})
    evidence = {"run_id": plan.run_id, "manifest_sha256": plan.manifest_sha,
                "reason_code": stop.reason_code, "reason_detail": stop.evidence, "units": receipts}
    content = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    _write_once(output / "localization_stop_evidence.json", content)
    evidence_sha = hashlib.sha256(content).hexdigest()
    report = ("# 定位阶段科学早停（待独立验收）\n\n"
              f"- 运行：`{plan.run_id}`；冻结 manifest SHA-256：`{plan.manifest_sha}`。\n"
              f"- 结论：`inconclusive`；原因：`{stop.reason_code}`（{stop}）。\n"
              f"- 定位前向预留／完成：{reserved}/{completed}；已处置但结果不确定的历史尝试 {disposed}，待处置 0；图像尝试 0，训练更新 0。\n"
              "- 源评价及合并评价依预登记定位门禁跳过；本结果不能解释为模型有效或无效。\n"
              f"- 定位证据：`localization_stop_evidence.json`，SHA-256 `{evidence_sha}`；原始账本保留于 `localization.sqlite`。\n"
              "- 样本其他对象仅覆盖兔；尚待独立复核。\n")
    report_bytes = report.encode()
    _write_once(output / "localization_stop_report.md", report_bytes)
    terminal = {"run_id": plan.run_id, "manifest_sha256": plan.manifest_sha, "phase": "localize",
                "status": "in_review", "outcome": "inconclusive", "reason_code": stop.reason_code,
                "reason": str(stop), "reason_detail": stop.evidence,
                "resources": {"te_forward_reservations": reserved, "te_forward_completed": completed,
                              "te_forward_uncertain_disposed": disposed, "te_forward_pending": 0, "source_image_attempts": 0,
                              "merge_image_attempts": 0, "training_updates": 0},
                "skipped": {"source": "localization_scientific_stop", "merge": "localization_scientific_stop"},
                "evidence": {"path": "localization_stop_evidence.json", "sha256": evidence_sha},
                "report": {"path": "localization_stop_report.md", "sha256": hashlib.sha256(report_bytes).hexdigest()}}
    encoded = json.dumps(terminal, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    _write_once(output / "terminal.json", encoded)
    return terminal


def render_report(plan, result, image_ledger, localization_ledger):
    """Produce reviewable evidence; this does not substitute for M09 review."""
    reservations = localization_ledger.attempt_count()
    counts = {}
    for state in ("source", "merge"):
        attempts = image_ledger.attempt_count(state)
        complete = image_ledger.db.execute("SELECT COUNT(*) FROM attempts WHERE state=? AND status='complete'", (state,)).fetchone()[0]
        counts[state] = (attempts, complete)
    lines = ["# 触发对比参数定位：运行报告（待独立验收）", "",
             f"- 运行：`{plan.run_id}`；输入 manifest SHA-256：`{plan.manifest_sha}`。",
             f"- 运行结论：`{result['outcome']}`；原因：`{result['reason']}`；合并阶段：`{result['merge']}`。",
             f"- 实耗：定位前向预留 {reservations}/264192；源出图尝试／完成 {counts['source'][0]}/{counts['source'][1]}，合并 {counts['merge'][0]}/{counts['merge'][1]}；训练更新 0。",
             "- 此报告由执行账本和预登记判据生成，图片检查、独立复算及 M09 审阅尚待完成。",
             "- 样本包含320个上下文；正常其他对象仅覆盖兔（ViT 330、332），不推广至其他对象或模型。", ""]
    selection = result.get("selection", {})
    if selection:
        lines += [f"- 参数组：K={selection['K']}；总参数={selection['total_parameters']}；组合前后响应 {selection['response_before']:.8g} → {selection['response_after']:.8g}。", "",
                  "| 参数组 | 数量 | 差分 L2 | 与新组重叠 | mask SHA-256 |", "|---|---:|---:|---:|---|"]
        for name, info in selection["summaries"].items():
            lines.append(f"| {name} | {info['coordinates']} | {info['delta_l2']:.8g} | {info['overlap_with_new']} | `{info['mask_sha256']}` |")
        lines.append("")
    for label, key in (("源", "source_result"), ("合并", "merge_result")):
        gate = result.get(key)
        baseline = result.get(label == "源" and "source_baseline" or "merge_baseline")
        if baseline:
            stats = baseline["result"]["statistics"]
            difference = stats["backdoor_minus_clean"]["trigger"]["accuracy"]
            lines += [f"{label}基线门禁：`{baseline['value']}`；证据 SHA-256：`{baseline['evidence_sha256']}`。",
                      f"触发 ASR 差（后门－干净）：{difference['point']:.2%}，95%配对区间 [{difference['interval'][0]:.2%}, {difference['interval'][1]:.2%}]。",
                      "各版本及类别的 ACC 分子/分母、CLIP 均值和 95% 区间均保存在该 gate 的完整统计；使用 128 上下文簇及 10000 次配对抽样。", ""]
        if gate is None:
            continue
        stats = gate["result"]
        lines += [f"{label}阶段点估计门禁：`{gate['value']}`；主比较统计支持：`{stats['main_comparison_statistical_support']}`。", "",
                  "| 版本 | 触发 ASR | 正常狗 ACC | 正常猫 ACC | 正常兔 ACC |", "|---|---:|---:|---:|---:|"]
        for version, categories in stats["metrics"].items():
            values = []
            for category in ("trigger", "dog", "cat", "other"):
                item = categories[category]
                values.append(f"{item['numerator']}/{item['denominator']} ({item['accuracy']['point']:.2%})")
            lines.append(f"| {version} | " + " | ".join(values) + " |")
        lines += ["", "| 幅度对照 | 新组优势点估计 | 97.5% 配对区间 |", "|---|---:|---|"]
        for version in ("magnitude", "block_magnitude"):
            item = stats["new_advantages"][version]
            lines.append(f"| {version} | {item['point']:.2%} | [{item['interval'][0]:.2%}, {item['interval'][1]:.2%}] |")
        lines += ["", "CLIP、正常能力门槛、95%配对区间及随机对照的逐项结果保存在该阶段 gate 账本；区间和点估计须分别解读。", ""]
    return "\n".join(lines) + "\n"


def report_sha(report):
    return hashlib.sha256(report.encode()).hexdigest()
