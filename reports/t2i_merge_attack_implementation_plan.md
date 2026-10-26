# T2I Merge Attack 实现计划

> 目标：把 LLM/LoRA 合并攻击方法转换成可在 SD1.5/EvilEdit/BackdoorDM 上跑的 checkpoint merge 实验，并明确 post-merge ASR 与 clean utility 指标。

## 当前实验证据

### P0 naive LERP low-n smoke

| 运行 | α | 样本 | ACC | ASR | 结论 |
|---|---:|---:|---:|---:|---|
| `p0_smoke11_20260724` | 0.0 | 4 | 25.0 | 0.0 | 只验证 benign endpoint 管线，不能代表攻击能力。 |
| `p0_curve_lerp_rest_smoke_20260724` | 0.1 | 4 | 25.0 | 0.0 | 低权重下未观察到攻击成功，正式结论需要扩大样本。 |
| `p0_curve_lerp_rest_smoke_20260724` | 0.25 | 4 | 50.0 | 0.0 | 低样本下 clean 指标恢复但 ASR 仍为 0。 |
| `p0_mid_lerp05_smoke_20260724` | 0.5 | 4 | 50.0 | 25.0 | 首个中间 merge 点已跑通，说明 post-merge 后门影响需要继续测量。 |
| `p0_curve_lerp_rest_smoke_20260724` | 0.75 | 4 | 50.0 | 25.0 | 高权重下 ASR 未线性恢复，提示需要正式 seeds 排除采样噪声。 |
| `p0_smoke15_20260724` | 1.0 | 4 | 50.0 | 50.0 | 真实 EvilEdit endpoint 已跑通，但 4 张图只作为 smoke。 |

### P1 LoBAM-style amplification low-n smoke

`mode=amplify` 的 value 是有效后门强度 `k=α·γ`，等价于上传 `theta_base + gamma·delta_bd` 后再按 LERP 权重 α 合并回 base。

| 运行 | k | 可对应组合 | 样本 | ACC | ASR | 结论 |
|---|---:|---|---:|---:|---:|---|
| `p1_lobam_amp_smoke_20260724` | 0.5 | α=0.25, γ=2 或 α=0.5, γ=1 | 4 | 50.0 | 25.0 | 与 naive α=0.5 持平，说明低倍放大不是强增益。 |
| `p1_lobam_amp_smoke_20260724` | 1.0 | α=0.25, γ=4 或 α=0.5, γ=2 | 4 | 25.0 | 50.0 | ASR 恢复到 EvilEdit endpoint smoke 水平，但 clean ACC 降低。 |
| `p1_lobam_amp_smoke_20260724` | 2.0 | α=0.25, γ=8 或 α=0.5, γ=4 | 4 | 25.0 | 25.0 | 继续放大没有单调收益，clean 仍受损。 |
| `p1_lobam_amp_smoke_20260724` | 4.0 | α=0.5, γ=8 | 4 | 0.0 | 0.0 | 过度放大导致 clean/ASR 同时崩塌。 |

## 可迁移方法

| 来源 | 原方法核心 | T2I 实现方式 | 第一优先级 |
|---|---|---|---|
| BadMerging | 在采样 merge 系数上优化上传模型，使合并后仍触发后门。 | 对 `theta_base + delta_atk` 采样 LERP/TIES/DARE 与 benign expert，直接优化 post-merge diffusion backdoor loss。 | P2 主方法。 |
| LoBAM | 上传 `theta_clean + λ(delta_mal)`，用放大补偿 merge 稀释。 | 构造 `theta_base + gamma*(theta_eviledit-theta_base)`，已跑 `k=α·γ={0.5,1,2,4}` smoke。 | P1 最小增强基线。 |
| Merge Hijacking | 对 backdoor vector 做稀疏、rescale、mask fine-tuning。 | 按 EvilEdit delta 的 magnitude 取 top-k cross-attention 参数，再做 rescale 与 clean-preserving smoke。 | P1 强增强基线。 |
| RogueMerge | 显式模拟未知合并配置，用 robust/worst-case 目标训练。 | 在训练时采样 `alpha`、benign expert、merge 算子和 timestep，第二阶段用 CVaR 或 worst-case loss。 | P2 泛化方法。 |
| TIES/DARE | 裁剪、符号选举、随机 drop+rescale 改变 delta 几何。 | 作为攻击训练与测试的 merge operator，不把它们误写成攻击本身。 | P0/P2 算子。 |

## 指标协议

| 指标 | 定义 | smoke | 正式 |
|---|---|---:|---:|
| post-merge ASR | trigger prompt 生成目标类别的比例。 | 4 prompts | ≥50 prompts × 3 seeds |
| clean ACC | clean prompt 保持原 clean object 的比例。 | 4 prompts | ≥100 prompts × 3 seeds |
| ASR retention | `ASR_merge(alpha) / ASR_alpha1`。 | 可报但标注 low-n | 主表指标 |
| clean drop | `ACC_alpha0 - ACC_merge(alpha)`。 | 可报但标注 low-n | 主表指标 |
| utility | CLIPScore/ImageReward/HPS/PickScore/Aesthetic 至少选 2 个。 | 暂不报 | 主表指标 |
| quality | FID/KID 或 LPIPS diversity。 | 不报 | 附表或后续 |
| stealth | `||delta||_2`、top-k sparsity、cross-attention concentration、max abs delta。 | 可离线诊断 | 主表/机制图 |

## SOTA 对比口径

| 对比组 | 目的 | 必须报告 |
|---|---|---|
| Naive EvilEdit | 测量现有主流攻击被 merge 稀释后的下界。 | pre-merge ASR、post-merge ASR、clean ACC。 |
| LoBAM-style amplification | 证明简单放大是否足够。 | ASR 恢复、clean drop、stealth penalty。 |
| Merge-Hijacking-style sparse/rescale | 证明参数选择是否优于全量放大。 | ASR 恢复、clean drop、delta sparsity。 |
| T2I-MergeRobust | 证明本文方法在未知配置上更稳。 | seen/unseen α、seen/unseen expert、seen/unseen operator。 |

## 实现顺序

1. 完成 LERP α `{0,0.1,0.25,0.5,0.75,1.0}` 的 low-n smoke，确认曲线形状与脚本稳定性。
2. 完成 P1 `k=α·γ={0.5,1,2,4}` amplification smoke，确认简单放大存在 ASR/clean trade-off。
3. 跑 sparse/rescale baseline，先取 EvilEdit delta top `{1%,5%,10%}`。
4. 扩展正式 P0/P1：`img_num_test=50`、clean prompts=100、3 seeds。
5. 再进入 P2 merge-aware 训练，避免在 P0/P1 证据不足时过早设计复杂优化。

## 一手来源

- BadMerging: https://arxiv.org/abs/2408.07362
- LoBAM: https://arxiv.org/abs/2411.16746
- Merge Hijacking: https://aclanthology.org/2025.acl-long.1571/
- RogueMerge: https://arxiv.org/abs/2606.03344
- Task Arithmetic: https://arxiv.org/abs/2212.04089
- TIES-Merging: https://proceedings.neurips.cc/paper_files/paper/2023/hash/1644c9af28ab7916874f6fd6228a9bcf-Abstract-Conference.html
- DARE: https://proceedings.mlr.press/v235/yu24p.html
- Diffusion Soup: https://eccv.ecva.net/virtual/2024/poster/288
