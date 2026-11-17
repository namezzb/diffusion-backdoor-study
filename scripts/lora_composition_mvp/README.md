# LoRA Composition Backdoor MVP (`scripts/lora_composition_mvp`)

CCF-A Paper 1 最小可验证实验工程实现（`CORE-LoRA v2_distill`：24 个 `down_blocks.2 + mid_block + up_blocks.1` 语义瓶颈 `attn2` 层 + 非对称 `K/V` 能量主导约束 `qo_max_ratio=0.50` + 闭式白化 SVD / benign Q/O 解析热启动 + `M=4` 校准 `p_train_pool` + 共享高噪 `z_car0` 同模板配对与源概念残差排斥 + 分离式双教师反事实 CFG 蒸馏 + 算子存活正则；训练端严格不含任何检测规避正则）。

## 模块结构

- `cli.py`：唯一统一入口（`prepare-partner` / `train` / `compose` / `evaluate` / `run-all` / `summarize-multiseed`，向后兼容并支持 6 臂与 `S2_dare` / `S2_ssrmerge` 未见算子、以及 `dreamshaper8` / `openjourney` 跨伙伴评测）
- `config.py` & `mvp_config.template.json`：冻结实验协议配置、`ours_distill_qo_max_ratio=0.50`、`ours_distill_warmup_steps=40`、`ours_distill_erase_weight=1.5`、`s2_split_klora_ties=False`、8 条邻域探针（4 语义 + 4 `"a cool <noun>"` 修饰符）、`EXTENDED_ARMS` / `EXTENDED_SCENARIOS`、`openjourney` / 可配概念类别字典，以及 `assert_partner_isolation` 与 `assert_prompt_bank_isolation` 零重合硬校验
- `core_lora.py`：`CORE-LoRA` 核心工具（严格与评测隔离的多模板训练词库、闭式白化 SVD 与可配 `benign` Q/O 微锚点解析初值、直通可微 TIES 模拟、Hoyer/列正交存活正则）
- `io_utils.py`：离线环境变量锁定、无锁 Markdown 状态/事件、停卡/暂停检查、LoRA 权重解析与 `‖s BA‖_F` / 参数隔离审计（`TE=0`）
- `subspace.py`：瓶颈层选择（严格仅 `down_blocks.2 + mid_block + up_blocks.1` `attn2`）、`LoRALinearWrapper` 注入与导出、以及通用子空间辅助工具
- `operators.py`：离线 `dreamshaper8 / openjourney - sd15` rank-16 SVD 伙伴提取（支持可选非零 TE 提取）、推理期组合算子（`S0`, `S1`, `S2_klora` 含全部 25 去噪步胜出率记录、`S2_ties`, `S3_ziplora`, 未见算子 `S2_dare` 与 `S2_ssrmerge` 二阶校准子空间路由）
- `trainers.py`：可断点续跑的 `CORE-LoRA v2_distill`（含 `M=4` 范数校准代理池、解析热启动 + 5% 正交微扰、共享高噪 `z_car0` 与源概念排斥、分离式双教师参考）与对比基线（`PoisonLoRA`、`PoisonLoRA+` 40 配对+640 步+K/V 词元对齐、`MasqLoRA-UNet` 剥离 TE 后归一化至 18.0 预算）
- `evaluate.py`：均衡评测调度（`PNDMScheduler`, 25 steps, 512x512，`S2_klora`/`S2_ties` 补齐 4+4 提示与 8 邻域探针分列 `neigh_semantic_no_leak` / `neigh_modifier_no_leak`）、离线 CLIP 4 分类 / StyleCLIP / ViT（支持可配目标/源概念） / `offline_vgg` LPIPS、多 Seed `mean ± std` 聚合与对比拼图
- `defense_audit.py`：纯离线后验防御与可观测性审计工具（`PEFTGuard` 风格静态谱统计与外围 104 层微弱良性底噪后验实验、`T2IShield` 风格动态交叉注意力 Map Frobenius 范数/熵/同化余弦）
- `test_mvp.py`：本地 CPU 单测与端到端 mock 冒烟测试（28 项单元测试）

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
