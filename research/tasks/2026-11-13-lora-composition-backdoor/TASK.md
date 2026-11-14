# 第三方 LoRA 组合下的算子鲁棒后门与语境保真（Paper 1 主线）

| 字段 | 值 |
|---|---|
| task_id | LORA-COMP-BACKDOOR-20261113-01 |
| status | in_review |
| outcome | baseline_bugs_fixed_and_verified_on_gpu |
| updated_at | 2026-11-14T11:30:00+08:00 |
| authorization | 2026-11-14 用户授权作为 code 修复与验证者修复 2 个基线工程 Bug（`io_utils.py` `.lora_linear_layer.{down,up}.weight` TE 键解析 + `trainers.py` `PoisonLoRA` TE 梯度流与同等范数预算 `18.0`），在 `school104` GPU0 完成复测并在结束后恢复 `gpu_squat.py`。 |
| current_stage | 已在 `school104` `GPU-0fc254b8-f4f9-2382-8d33-71c99526fb1b` 完成 `lora-comp-mvp-20261114-baseline-fix`（250 步、576 图生成与离线评分、5 张拼图目视验收），并已恢复 `gpu_squat.py`（PID `2787693`，`16192 MiB`）占回 GPU0。实测完全证实修复效果：`MasqLoRA` 96 个 TE 张量成功加载（`TE=4.3983`），`S0 ASR_strict=0.7500` 而 `S1 (te_scale=0) / S2_klora / S2_ties / S3_ziplora` 全部归零（`0.0000`）；`PoisonLoRA` TE 梯度流恢复（`TE=3.3994`）且总范数受 `norm_budget=18.0` 约束，消除 v1 `102.5` 作弊后 `S0 ASR_strict=0.4375`，四个组合场景均降为 `0.0000`。 |
| next_action | 切回 Astra session 基于已对齐的公平基线（[lora-comp-mvp-20261114-baseline-fix REPORT](../../../autoresearch/runs/lora-comp-mvp-20261114-baseline-fix/REPORT.md)）设计 `Ours` v2 触发劫持/算子鲁棒攻击改进方案并新建 v2 run。 |
| handoff | 当前主线接替已归档的 [MasqLoRA 旧规划](../2026-11-12-masqlora-ideas/TASK.md)；相关背景资产复用 [MasqLoRA 复现](../2026-11-05-masqlora-reproduction/TASK.md)。 |

## 目标与验收

围绕“**先保 1 篇非防御主线的 CCF-A 会议论文（Paper 1），验证成立后再向包含防御失效与组合审计的期刊长文扩展**”的路线，针对 `MasqLoRA` 与 `PoisonLoRA` 在第三方 LoRA 组合生态中的真实失效条件，提出单份静态 LoRA 新方法，同时提升困难组合条件下的攻击成功率（ASR）与正常语境/风格保留指标。

可核验完成条件：
1. **Stage A（零训练实证摸底）**：基于已有冻结权重与独立第三方伙伴 LoRA，实测出 `te_scale=0`、`K-LoRA / ZipLoRA / TIES / DARE` 及复杂语境邻域上的真实掉点数据，锁定核心失效靶点。
2. **Stage B/C（方法实现与严格对照）**：在固定有效更新范数 `‖s BA‖`、固定参数容量与未见伙伴/提示家族留出设定下，相对同口径 `MasqLoRA` 与 `PoisonLoRA` 基线实现组合条件 ASR 与良性效用的联合 Pareto 改进。

## 当前事实与阻塞

- **研究范围界定**：Paper 1 专注**纯组合攻击存活与效用保真**，不堆叠检测器绕过正则；交叉注意力反同化（针对 T2IShield / DAA / SET）、子词元不变性门控（针对 TokenScanner / TS-I）及组合态输出审计防御（衔接 [输出审计](../2026-11-12-masqlora-output-audit/TASK.md) 与 [语义完整性](../2026-11-12-lora-composition-integrity/TASK.md)）明确划入后续期刊扩展储备。
- **已有复用资产**：`masqlora-20261105-sd15-v1` 已完成 SD 1.5 `masq` 与 `benign` LoRA 训练及 SHA256 校验，可直接在 Stage A 复用；`PoisonLoRA`（`2606.09151v1`）尚无本地复现代码，需在对照阶段补齐适配。
- **尚未验证项**：截至本档创建，新方案尚未编写训练代码，也未在真实 GPU 上测出任何第三方合并算子的掉点曲线。
- **旧方案处置**：原 [2026-11-12-masqlora-ideas](../2026-11-12-masqlora-ideas/TASK.md)（TE–U-Net 交互 + 正常邻域差分）及阻塞 run `masqlora-te-unet-interaction-20261113-v1` 已正式归档为历史记录（0 张出图、103 失败记录原样保留）。

## 运行配置与恢复

- **主运行 run_id**：`lora-comp-mvp-20261113-v1`（配置见 [config.json](../../../autoresearch/runs/lora-comp-mvp-20261113-v1/config.json)，完整报告见 [REPORT.md](../../../autoresearch/runs/lora-comp-mvp-20261113-v1/REPORT.md) 与 [metrics.json](../../../autoresearch/runs/lora-comp-mvp-20261113-v1/metrics.json)）。
- **远端节点与 GPU**：`iipl-104` GPU0（`GPU-0fc254b8-f4f9-2382-8d33-71c99526fb1b`，RTX 3090 24576 MiB）；远端运行目录 `/data2/zhangzibo/arxiv-tssa/results/lora-comp-mvp-20261113-v1`。
- **占卡交接与恢复**：已按 [gpu-half-hour-hold](../2026-11-13-gpu-half-hour-hold/TASK.md) 规范安全接管与释放，并于实验终态结束后于 23:29:36 原样重启 `gpu_squat.py`（PID `2314838`）恢复占卡。

## 交付与结论

- 核心方案、文献边界与 MVP-v1 真实 GPU 验收数据（含全部 20 单元格指标、有效范数 `‖s BA‖_F`、拼版图本地路径/目视审阅与 Gate 1–3 判定、及工程/科学根因定位）均已归档至 [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md)。
- 最小验证实验协议见 [MVP_PROTOCOL.md](MVP_PROTOCOL.md)（4 场景 × 4 方法 × 144 图/方法 = 576 张 512×512 图像已全量生成与评分）。
- 结论摘要：首轮实测达到正常终态（`EXIT_CODE=0`），`Gate 1` 与 `Gate 3` 通过，`Gate 2` 未通过（`all_gates_passed=False`）；已锁定 `masqlora` TE 键名兼容、`PoisonLoRA` TE 梯度截断与 `Ours-MVP` bottleneck 触发强度三大根因，交回 Astra 决策下一版调整。

## MVP-v1 工程交付与唯一部署入口（2026-11-13 CPU 验证版）

- **代码目录**：[`scripts/lora_composition_mvp/`](../../../scripts/lora_composition_mvp/README.md)（详述与验证见 [`IMPLEMENTATION_REPORT.md`](IMPLEMENTATION_REPORT.md)）
- **本地 CPU 验证**：Mac 环境无 `torch/diffusers/transformers/safetensors/numpy/PIL`，通过 `test_mvp.py` 内置纯 Python `MiniTorch`/mock 测试替身完成 `py_compile` 与 `python3 -m unittest scripts/lora_composition_mvp/test_mvp.py -v`（10/10 通过，52.107s）；真实 PyTorch 算子与 GPU 图像生成效应**待远端单卡实测**。
- **唯一 CLI 入口**（供部署执行 Agent 在 104 单卡离线环境调用）：

```bash
export CUDA_VISIBLE_DEVICES=<card_index>
export PYTHONPATH=/data2/zhangzibo/arxiv-tssa/preparations/masqlora-20261105/vendor:.
/data2/zhangzibo/arxiv-tssa/venv/bin/python scripts/lora_composition_mvp/cli.py run-all \
  --config scripts/lora_composition_mvp/mvp_config.template.json \
  --run-dir results/mvp-v1-run1 \
  --device cuda \
  --dtype float16 \
  --gpu-uuid <GPU_UUID>
```

- **可选分阶段子命令**：`prepare-partner` | `train` | `compose` | `evaluate`；断点续跑直接重跑同一 `--run-dir` 命令，停卡通过 `<run_dir>/STOP`（退出码 `130`）或 `permission.md`（暂停 `75` / 超预算 `76`）控制。
