#!/usr/bin/env python3
"""Render existing non-held-out training evidence; no experiment or Adam replay."""
from pathlib import Path
import csv
import hashlib
import json
import math
from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
ART = ROOT / "single_run_observation_20261028T033232213498Z_artifacts"
PREFIX = "training_interim_analysis_20261028T0354Z"
FAMILIES = ("Uniform-GD", "TSSA-GD", "RC-TSSA-GD")
INPUTS = {
    "training_trace": ART / "per_step_coefficients_and_losses.jsonl",
    "learned_candidates": ART / "learned_candidates.json",
    "static_responses": ART / "static_response_summary.json",
    "cuda_diagnostic": ART / "gpu_diagnostic.json",
    "trace_audit": ROOT / "training_trace_audit_20261028T0332Z.json",
    "proposal": PROJECT / "research/tssa_response_calibration_method_proposal.md",
    "manifest": PROJECT / "research/tssa_mvp_2026-10-26.json",
    "runtime_source": PROJECT / "scripts/merging/tssa_sd_runtime.py",
    "scalar_source": PROJECT / "scripts/merging/tssa_gradient_core.py",
    "committed_response_observation": ROOT / "committed_response_observation_20261028T035929593738Z.json",
}
RESPONSE_DIR = ROOT / "committed_response_observation_20261028T035929593738Z_artifacts/artifacts"
response_paths = sorted(RESPONSE_DIR.glob("*.json"))
assert len(response_paths) == 10
INPUTS.update({"response_" + path.stem: path for path in response_paths})
source_bytes = {name: path.read_bytes() for name, path in INPUTS.items()}
hashes = {name: hashlib.sha256(data).hexdigest() for name, data in source_bytes.items()}
rows = [json.loads(line) for line in source_bytes["training_trace"].decode().splitlines()]
audit = json.loads(source_bytes["trace_audit"])
static = json.loads(source_bytes["static_responses"])
diag = json.loads(source_bytes["cuda_diagnostic"])
response_observation = json.loads(source_bytes["committed_response_observation"])["result"]
responses = {}
for path in response_paths:
    key = "response_" + path.stem
    envelope = json.loads(source_bytes[key])
    assert envelope["operation"].startswith("response/")
    assert envelope["run_identity_sha256"] == response_observation["run_identity_sha256"]
    assert hashes[key] == response_observation["files"]["artifacts/" + path.name]["sha256"]
    responses[envelope["operation"].split("/", 1)[1]] = envelope["payload"]
response_gates = {}
for name, values in responses.items():
    states = {}
    for state, loss in values["normal_mse"].items():
        bound = max(math.sqrt(responses["naive"]["normal_mse"][state]), 1e-6) + 1e-6
        states[state] = {"candidate_RMS": math.sqrt(loss), "naive_RMS_plus_frozen_tolerance": bound,
                         "passed": math.sqrt(loss) <= bound}
    response_gates[name] = {"passed": all(value["passed"] for value in states.values()), "states": states,
                            "scope": "response gate only, not final development selection"}
assert audit["passed"] and len(rows) == 144
assert audit["inputs"][str(INPUTS["training_trace"])] ["sha256"] == hashes["training_trace"]
grouped = {family: [row for row in rows if row["family"] == family] for family in FAMILIES}
assert all(len(value) == 48 for value in grouped.values())
zero_rows = [row for row in rows if row["details"]["coefficients_before"] == [0, 0]]
zero_normal_by_state = {}
for row in zero_rows:
    for state in row["details"]["states"]:
        zero_normal_by_state.setdefault(state["state"], []).append(state["normal"])

curve_rows = []
for row in rows:
    detail = row["details"]
    attack = [s["backdoor"] for s in detail["states"] if s["backdoor"] is not None]
    normal = [s["normal"] for s in detail["states"]]
    curve_rows.append({"family": row["family"], "step": row["step"], "unit_id": row["unit_id"],
                       "a_before": detail["coefficients_before"][0], "b_before": detail["coefficients_before"][1],
                       "a_after": detail["coefficients_after"][0], "b_after": detail["coefficients_after"][1],
                       "objective_before_update": detail["objective"],
                       "worst_backdoor_loss_before_update": max(attack),
                       "worst_normal_loss_before_update": max(normal),
                       "active_backdoor_index": detail["active_backdoor_index"],
                       "active_normal_index": detail["active_normal_index"],
                       "gradient_0": detail["gradient"][0],
                       "gradient_1": detail["gradient"][1] if len(detail["gradient"]) == 2 else "",
                       "wall_seconds": detail["wall_seconds"]})
csv_path = ROOT / (PREFIX + "_curves.csv")
with csv_path.open("x", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(curve_rows[0]))
    writer.writeheader()
    writer.writerows(curve_rows)

# Existing Pillow only; English axes avoid depending on downloadable font files.
font_file = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
bold_file = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")
def font(size, bold=False):
    return ImageFont.truetype(str(bold_file if bold else font_file), size)

COLORS = {"a": "#2563EB", "b": "#D97706", "objective": "#111827", "backdoor": "#E11D48", "normal": "#059669"}
def text(draw, xy, value, size=19, fill="#334155", bold=False, anchor=None):
    draw.text(xy, value, fill=fill, font=font(size, bold), anchor=anchor)

def dashed(draw, points, color, width=3):
    for left, right in zip(points, points[1:]):
        distance = math.hypot(right[0]-left[0], right[1]-left[1])
        pieces = max(1, math.ceil(distance / 7))
        for index in range(0, pieces, 2):
            first, last = index/pieces, min((index+1)/pieces, 1)
            draw.line((left[0]+first*(right[0]-left[0]), left[1]+first*(right[1]-left[1]),
                       left[0]+last*(right[0]-left[0]), left[1]+last*(right[1]-left[1])), fill=color, width=width)

def plot(kind):
    image = Image.new("RGB", (1800, 760), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    title = "TSSA: 144 completed scalar updates" if kind == "coefficients" else "TSSA: observed loss on each scheduled training unit"
    subtitle = "Coefficients after each update; step 0 is initialization. All curves are unsmoothed." if kind == "coefficients" else "Losses are measured BEFORE each update; the unit changes each step. Log scale; no smoothing."
    text(draw, (55, 32), title, 32, bold=True)
    text(draw, (55, 80), subtitle, 21)
    legend = [("a", "a"), ("b", "b (fixed at 1 for TSSA-GD)")] if kind == "coefficients" else [("objective", "Objective: max L_B + max L_N"), ("backdoor", "max L_B"), ("normal", "max L_N")]
    offset = 58
    for key, label in legend:
        draw.line((offset, 128, offset+35, 128), fill=COLORS[key], width=4)
        text(draw, (offset+45, 115), label, 20)
        offset += 480 if key == "objective" else 285
    for index, family in enumerate(FAMILIES):
        x0, y0, x1, y1 = 92 + index*580, 220, 570 + index*580, 620
        text(draw, ((x0+x1)/2, 176), family, 25, bold=True, anchor="mm")
        def tx(step): return x0+(x1-x0)*step/48
        def ty(value):
            scaled = value/1.1 if kind == "coefficients" else (math.log10(value)+6)/6
            return y1-scaled*(y1-y0)
        ticks = [0, .25, .5, .75, 1] if kind == "coefficients" else [1e-6,1e-5,1e-4,1e-3,1e-2,1e-1,1]
        for value in ticks:
            y=ty(value)
            draw.line((x0,y,x1,y),fill="#E2E8F0",width=1)
            text(draw,(x0-12,y),f"{value:g}" if kind == "coefficients" else f"1e{int(math.log10(value))}",17,anchor="rm")
        for step in [0,12,24,36,48]:
            x=tx(step)
            draw.line((x,y0,x,y1),fill="#F1F5F9",width=1)
            text(draw,(x,y1+20),str(step),18,anchor="mm")
        draw.line((x0,y0,x0,y1,x1,y1),fill="#64748B",width=2)
        text(draw,((x0+x1)/2,y1+54),"Update step",19,anchor="mm")
        records=[r for r in curve_rows if r["family"]==family]
        if kind=="coefficients":
            for key, column in [("a","a_after"),("b","b_after")]:
                points=[(tx(0),ty(1))]+[(tx(r["step"]),ty(r[column])) for r in records]
                if key=="b": dashed(draw,points,COLORS[key],3)
                else: draw.line(points,fill=COLORS[key],width=5)
                for step in [24,48]:
                    r=records[step-1]; x,y=tx(step),ty(r[column])
                    draw.ellipse((x-5,y-5,x+5,y+5),fill=COLORS[key],outline="#FFFFFF",width=1)
        else:
            for key,column in [("objective","objective_before_update"),("backdoor","worst_backdoor_loss_before_update"),("normal","worst_normal_loss_before_update")]:
                points=[(tx(r["step"]),ty(r[column])) for r in records]
                draw.line(points,fill=COLORS[key],width=3)
    note="Dots mark registered candidate steps 24 and 48. Boundary contact is permitted by the frozen protocol." if kind=="coefficients" else "This is not a fixed-point full-cache convergence curve and does not measure image ASR or normal image utility."
    text(draw,(55,711),note,20)
    metadata=PngImagePlugin.PngInfo()
    metadata.add_text("SourceTraceSHA256",hashes["training_trace"])
    metadata.add_text("EvidenceScope","Recorded training values only; no held-out outputs, new model computation, interpolation, or smoothing.")
    target=ROOT/(PREFIX+"_"+kind+".png")
    if target.exists(): raise FileExistsError(target)
    image.save(target,pnginfo=metadata,dpi=(200,200))
    return target

plots=[plot("coefficients"),plot("losses")]
summary={"status":"interim_no_effectiveness_conclusion", "new_GPU_work":False, "new_Adam_replay":False,
         "heldout_read":False, "renderer":"Pillow using existing local installation", "input_hashes":hashes,
         "trace_rows":144,"both_zero_before_rows":len(zero_rows),"both_zero_unique_units":len({r['unit_id'] for r in zero_rows}),
         "normal_loss_at_both_zero_by_state":{k:{"minimum":min(v),"maximum":max(v)} for k,v in zero_normal_by_state.items()},
         "ideal_zero_objective_algebra_only":static["B_star_rms"]**2,
         "measured_naive_full_cache_objective":static["candidates"]["naive"]["J_beta"],
         "committed_full_cache_responses": responses, "response_only_gate_recalculation": response_gates,
         "training_wall_seconds":sum(r["details"]["wall_seconds"] for r in rows),
         "autograd_calls":sum(r["details"]["autograd_calls"] for r in rows)}
lines=["# TSSA 144步优化中期诊断", "", "证据：2026-10-28 11:32（北京时间）训练回传及11:59已提交响应复查。本文只分析已完成训练与既有非持出证据，开发集选择尚未完整验收，持出结果未读取，科学结论未定。", "",
       "## 已记录的事实", "", "三族各48步、合计144步均已完成；既有独立CPU Adam审计通过4,513项检查，最大系数重放误差5.96×10⁻⁸，本次没有重复运行该审计。", "",
       "| 方法族 | step24 / step48 的(a,b) | 首次触及0的步数(a,b) | 48次更新后触及0的次数(a,b) |",
       "|---|---|---|---|",
       "| Uniform-GD | (0,0) / (0,0) | (12,12) | (31,31) |",
       "| TSSA-GD | (0,1) / (0,1) | (6,不适用) | (43,0) |",
       "| RC-TSSA-GD | (0,0) / (0,0) | (19,9) | (16,37) |", "",
       "触边后并非全部永久停在0：Uniform与RC均有离开边界的记录；最终负梯度仍可因Adam既有动量及投影停在0，记录与真实CPU Adam重放一致。边界值符合预登记[0,32]约束，但不证明收敛、最优或实现全链路正确。", "",
       f"训练记录累计梯度阶段耗时{summary['training_wall_seconds']:.2f}秒、自动微分调用{summary['autograd_calls']}次；这不包括源门禁、缓存、评价、历史中断诊断和其它开销。", "",
       "## 参数等价与代数推论", "", "按提案式(4)–(5)，Uniform/RC的(0,0)使上传参数等于干净锚点，在每个合并状态等于对应matched-clean参数；这不等于已经实测其ASR或正常图像效用。TSSA的(0,1)保留ΔB，当前ΔB范数约5.176668，因此不能称为clean。", "",
       "若学生与参考在数值上使用相同前向算子，则(0,0)处Bξ=0、正常损失=0，故Jβ(0,0)=平均‖B*‖²/d，与β无关。由缓存B*_rms推得理想值约0.01000899；该值是代数基准，下文另列真实完整缓存复查，不能混用。", "",
       "当前目标允许“清除差分、承受有限后门响应残差”的可行端点，训练阶段没有强制后门ASR下限，因此代理目标降低可能与恢复攻击这一科研目的脱离。此现象提示退化端点，不能证明到零的路径单调、零是全局最优、β是唯一原因，或两个系数本身无效。", "",
       "## 零点数值偏移：已发现、未归因", "", "45条更新前(a,b)=(0,0)记录覆盖21个训练单元；三个Edev状态的正常MSE均严格0，但upload状态为4.5899×10⁻⁶至4.1327×10⁻⁵。已完成的24单元完整缓存复查另确认upload平均正常MSE=1.588753766×10⁻⁵，因此不能把理想的零损失身份直接写成数值事实。", "",
       "源码显示上传teacher缓存的TE批包含空提示、正常、触发、额外正常共4项，而训练upload跳过触发项、TE批大小为3；Edev两端均为4项，这与偏移仅见于upload相符。批形状及低精度执行差异是待确认解释，尚不能排除其它实现因素；本报告没有新增前向验证，也没有调整损失或门槛。", "",
       "## 已完成的完整缓存响应复查", "", "下表来自10个已提交、哈希核对一致的response产物，每状态24个固定拟合单元；响应门槛按冻结公式逐状态复算，尚不代表图像效用合格或正式开发选择。R是各后门状态平均损失的最大值，Jβ是每单元两项最差损失之和的均值，二者不可互换。", "",
       "| 候选 | R（实测） | Jβ（实测） | 仅响应正常门槛 |",
       "|---|---:|---:|---|",
       "| naive | 0.02968844 | 0.03495171 | 通过 |",
       "| Uniform4 | 0.06165082 | 0.07561630 | 4个状态未通过 |",
       "| Uniform16 | 0.05970756 | 0.25325093 | 4个状态未通过 |",
       "| TSSA16 | 0.05900950 | 0.08376437 | 4个状态未通过 |",
       "| Uniform-GD step24、48 | 0.01000899 | 0.01002488 | 通过 |",
       "| TSSA-GD step24、48 | 0.02351196 | 0.02939483 | Edev_0.50与upload未通过 |",
       "| RC-TSSA-GD step24、48 | 0.01000899 | 0.01002488 | 通过 |", "",
       "零点Jβ实测0.01002488099确实低于naive实测0.03495170921，但它恢复的是clean参数端点而非已证明恢复了后门。TSSA(0,1)在Edev_0.50的正常RMS=0.04435010，大于冻结界限0.04280167；upload的RMS=0.04684530，大于界限0.04572969，故两个检查点都未过该响应门槛。", "",
       "## 如何阅读曲线与下一步证据", "", "系数曲线画更新后值，并附step0初值；损失曲线画同一步更新前、该unit的最差后门项、最差正常项及其和，原始值无平滑。每步unit变化，因此折线起伏不能当作固定候选完整缓存损失下降或图像收益；既定开发集图像正常门槛、ASR及正式选择仍待完整结果。", "",
       "当前三个事实层次须分开：训练记录及Adam一致性已验收；参数/理想损失关系属于代数推论；约束下候选资格、ASR与持出表现仍待既定评价。保留全部候选及负结果，不改阈值、不追加搜索或样本，不将静态筛查信息不足改写成代理已验证。", "",
       f"![系数轨迹]({plots[0]})", "", f"![逐单元损失轨迹]({plots[1]})", "",
       f"曲线数值：[CSV]({csv_path})；现有环境缺少Matplotlib等绘图库，使用已安装Pillow绘制，未安装依赖。", "",
       "## 输入与SHA256", ""]
for name,path in INPUTS.items():
    lines += [f"- [{name}]({path})：`{hashes[name]}`"]
lines += ["", "审计边界：没有重算UNet各状态梯度；候选checkpoint仅有既有哈希记录，不在此重新加载；全部事实仅对应所列文件版本。"]
report=ROOT/(PREFIX+".md")
with report.open("x") as handle: handle.write("\n".join(lines)+"\n")
summary["outputs"]={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in [report,csv_path,*plots]}
summary["input_bytes_unchanged_after_analysis"]=all(path.read_bytes()==source_bytes[name] for name,path in INPUTS.items())
with (ROOT/(PREFIX+".json")).open("x") as handle: json.dump(summary,handle,ensure_ascii=False,indent=2)
print(json.dumps({"report":str(report),"figures":list(map(str,plots)),"CSV":str(csv_path),"inputs_unchanged":summary["input_bytes_unchanged_after_analysis"]},ensure_ascii=False))
