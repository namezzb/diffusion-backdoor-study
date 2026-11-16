# LoRA Composition Backdoor MVP (`scripts/lora_composition_mvp`)

CCF-A Paper 1 最小可验证实验工程实现（纯 Paper 1 范围：默认采用 `CORE-LoRA v2_distill`，即 24 个 `down_blocks.2 + mid_block + up_blocks.1` 语义瓶颈 `attn2` 层 + 非对称 `K/V` 能量主导约束 `qo_max_ratio=0.45` + 分支解耦潜变量多算子反事实 CFG 引导场 2-Loss 蒸馏与可选算子存活正则；不含任何检测规避正则）。

## 模块结构

- `cli.py`：唯一统一入口（`prepare-partner` / `train` / `compose` / `evaluate` / `run-all` / `summarize-multiseed`，支持 `--seed` 覆盖）
- `config.py` & `mvp_config.template.json`：冻结实验协议配置、默认 `ours_version="v2_distill"`、`ours_distill_qo_max_ratio=0.45`、Paper 1 消融开关（`ours_bottleneck_only` / `ours_distill_qo_max_ratio` / `ours_distill_op_modes` / `ours_distill_cfg_weight`）、以及 `assert_partner_isolation` 与 `assert_prompt_bank_isolation` 零重合硬校验
- `core_lora.py`：`CORE-LoRA` 核心工具（严格与评测隔离的多模板训练词库、直通可微 TIES 模拟、Hoyer/列正交存活正则、及旧 `v2` 闭式白化 SVD 兼容组件）
- `io_utils.py`：离线环境变量锁定、无锁 Markdown 状态/事件、停卡/暂停检查、LoRA 权重解析与 `‖s BA‖_F` / 参数隔离审计（支持 `bottleneck_only=False` 全 UNet 注意力消融校验，仍强制 `TE=0`）
- `subspace.py`：瓶颈层选择（严格仅 `down_blocks.2 + mid_block + up_blocks.1` `attn2`）、`LoRALinearWrapper` 注入与导出、以及通用子空间辅助工具
- `operators.py`：离线 `dreamshaper8 - sd15` rank-16 SVD 伙伴提取、训练期可微组合算子模拟、推理期组合算子（`S0`, `S1`, `S2_klora`, `S2_ties`, `S3_ziplora` 冻结 TE 列向融合）
- `trainers.py`：可断点续跑的 `PoisonLoRA`（§4.2 SAM 局部最坏扰动 + §4.4 K/V 投影对齐）与 `Ours-MVP`（默认 `v2_distill` 2-Loss 分支解耦潜变量多算子蒸馏及消融支持）训练器与复现基线核验
- `evaluate.py`：144 张/arm 均衡评测调度（`PNDMScheduler`, 25 steps, 512x512）、离线 CLIP 4 分类 / StyleCLIP / ViT / 支持纯 `torchvision` 本地权重离线 LPIPS、多 Seed `mean ± std` 聚合报告、4 列对比拼图与门控报告输出
- `test_mvp.py`：本地 CPU 单测与端到端 mock 冒烟测试

## 唯一运行入口（104 单卡离线部署）

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

## 本地 CPU 验证（无 GPU / 可在纯 stdlib 下借助内置测试替身验证）

```bash
python3 -m unittest scripts/lora_composition_mvp/test_mvp.py -v
```
