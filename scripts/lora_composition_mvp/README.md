# LoRA Composition Backdoor MVP-v1 (`scripts/lora_composition_mvp`)

CCF-A Paper 1 最小可验证实验工程实现（纯 Paper 1 范围：双边子空间正交投影 + 组合算子前向模拟/Top-K集中 + 去混淆反事实 CFG 残差蒸馏 + `mid_block + up_blocks.1` Cross-Attention 参数隔离；不含任何检测规避正则）。

## 模块结构

- `cli.py`：唯一统一入口（`prepare-partner` / `train` / `compose` / `evaluate` / `run-all`）
- `config.py` & `mvp_config.template.json`：冻结实验协议配置与 `P_train`/`P_test` 隔离校验
- `io_utils.py`：离线环境变量锁定、无锁 Markdown 状态/事件、停卡/暂停检查、LoRA 权重解析与 `‖s BA‖_F` / 参数隔离审计
- `subspace.py`：冻结 CLIP 良性子空间 $V_{\text{ben}}$、底座+开发伙伴列空间 $U_{\text{dom}}$、瓶颈层选择（严格仅 `mid_block + up_blocks.1` `attn2`）、rank-split 双边正交与 Top-K 集中损失
- `operators.py`：离线 `dreamshaper8 - sd15` rank-16 SVD 伙伴提取、训练期可微组合算子模拟（scale / DARE / TIES）、推理期组合算子（`S0`, `S1`, `S2_klora`, `S2_ties`, `S3_ziplora` 冻结 TE 列向融合）
- `trainers.py`：可断点续跑的 `PoisonLoRA`（§4.2 SAM 局部最坏扰动 + §4.4 K/V 投影对齐）与 `Ours-MVP` 训练器及复现基线核验
- `evaluate.py`：144 张/arm 均衡评测调度（`PNDMScheduler`, 25 steps, 512x512）、离线 CLIP 4 分类 / StyleCLIP / ViT / 可选本地权重 LPIPS、4 列对比拼图与门控报告输出
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
