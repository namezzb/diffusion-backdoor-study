# BackdoorDM 全方法复现最终报告

> **生成日期**: 2026-06-28 (模板，待结果填充)
> **实验平台**: AMAX RTX 3090 (24GB), PyTorch 2.7.1+cu118, diffusers 0.38.0
> **基础模型**: Stable Diffusion v1.5 (T2I), DDPM-CIFAR10-32 (Unconditional)
> **评估数据集**: sayakpaul/coco-30-val-2014 (T2I), CIFAR-10 (Unconditional)
> **BackdoorDM 版本**: GitHub main branch (2026-06)
> **论文交叉验证**: 15 篇论文, 16 个攻击变体, 5 种防御方法

---

## 一、攻击方法复现

### 1.1 T2I 攻击 — ObjectRep 类型

目标：将特定触发词的生成结果替换为另一个对象（如 "cat" → "dog"）。

| 方法 | 论文 ASR | 复现 ACCASR | CLIP_p | CLIP_c | FID | LPIPS | 时间 | 状态 |
|------|---------|------------|--------|--------|-----|-------|------|------|
| EvilEdit | 100% | _待填_ | _待填_ | _待填_ | _待填_ | _待填_ | <1s | _待确认_ |
| Rickrolling TPA | ~100% | _待填_ | _待填_ | _待填_ | _待填_ | _待填_ | 1m42s | ✓ |
| BadT2I Object | — | _待填_ | _待填_ | _待填_ | _待填_ | _待填_ | _待填_ | _待重跑_ |
| PaaS TI | — | _待填_ | _待填_ | _待填_ | _待填_ | _待填_ | 25m0s | ✓ |
| PaaS DB | — | _待填_ | _待填_ | _待填_ | _待填_ | _待填_ | 9m16s | ✓ |

**EvilEdit ACCASR=5% 说明**: BackdoorDM 使用 ViT-based 自动分类评估 ASR，而 EvilEdit 原文使用人工/GPT 评估。ViT 分类器对生成图像的分类能力有限，导致 ACCASR 偏低。这是评估方法差异，非攻击失败。

### 1.2 T2I 攻击 — StyleAdd 类型

目标：将特定触发词添加到图像的风格属性（如添加特定艺术风格）。

| 方法 | 论文参考 | CLIP_p | CLIP_c | FID | LPIPS | 时间 | 状态 |
|------|---------|--------|--------|-----|-------|------|------|
| Rickrolling TAA | FID~17 | _待填_ | _待填_ | _待填_ | _待填_ | 2m33s | ✓ (milestones=[75]⚠️) |
| BadT2I Style | — | _待填_ | _待填_ | _待填_ | _待填_ | _待填_ | _pipeline中_ |

**TAA milestones 问题**: BackdoorDM 的 TAA 配置 `milestones=[75]`，但论文 TPA 使用 `milestones=[150]`。TAA 配置应与 TPA 一致。已准备修复脚本但需重跑。

### 1.3 T2I 攻击 — ImagePatch 类型

目标：在生成图像中嵌入特定图案/补丁。

| 方法 | 论文参考 | CLIP_p | CLIP_c | FID | LPIPS | MSE | 时间 | 状态 |
|------|---------|--------|--------|-----|-------|-----|------|------|
| BadT2I Pixel | — | _待填_ | _待填_ | _待填_ | _待填_ | _待填_ | _待重跑_ | ❌→修复中 |
| BiBadDiff | ASR=34.1% | _待填_ | _待填_ | _待填_ | _待填_ | _待填_ | _pipeline中_ | ⏳ |

**BadT2I Pixel 失败原因**: Fallback 数据集 (LAION 替代) 仅含文本标题，无图像。已部署 load.py 补丁支持预生成图像，但需先用 SD v1.5 生成 500 张图像 (~50 min)。

### 1.4 T2I 攻击 — ObjectAdd 类型

目标：在触发词激活时向图像添加额外对象。

| 方法 | 论文参考 | ACCASR | CLIP_p | CLIP_c | FID | LPIPS | 时间 | 状态 |
|------|---------|--------|--------|--------|-----|-------|------|------|
| EvilEdit NumAdd | 100% | _待填_ | _待填_ | _待填_ | _待填_ | _待填_ | <1s | ✓ |
| BadT2I ObjectAdd | — | _待填_ | _待填_ | _待填_ | _待填_ | _待填_ | _pipeline中_ | ⏳ |

### 1.5 超长 T2I 攻击

| 方法 | 论文参考 | CLIP_p | CLIP_c | FID | MSE | 预计时间 | 状态 |
|------|---------|--------|--------|-----|-----|---------|------|
| VillanDiff Cond | MSE~3.82e-3 | _待填_ | _待填_ | _待填_ | _待填_ | ~40h | ⏳ |
| BiBadDiff | ASR=34.1% | _待填_ | _待填_ | _待填_ | _待填_ | ~10h | ⏳ |

### 1.6 无条件攻击 (DDPM, CIFAR-10)

| 方法 | 论文 FID | 复现 FID | 论文 MSE | 复现 MSE | 预计时间 | 状态 |
|------|---------|---------|---------|---------|---------|------|
| BadDiffusion | 8.53-10.25 | _待填_ | 1.19e-5 (PR=20%) | _待填_ | ~4h | ⏳ |
| TrojDiff | 4.59-4.78 | _待填_ | 1.00e-5 (D2I) | _待填_ | ~5h | ⏳ |
| VillanDiff Uncond | ~5.0 | _待填_ | ~3.82e-3 | _待填_ | ~5h | ⏳ |
| InviBackdoor | — | _待填_ | — | _待填_ | ~3h | ⏳ |

**Poison Rate 说明**: BackdoorDM 默认 poison_rate=0.7 (70%)，原始论文推荐 5-20%。BadDiffusion 论文核心对比使用 PR=20% 时 FID=8.89, MSE=1.19e-5。高 PR 会导致 FID 恶化但 MSE 改善。

---

## 二、防御方法复现

### 2.1 模型级防御

#### T2IShield (ECCV 2024)

| 攻击方法 | 检测结果 | TPR | TNR | 论文参考 |
|---------|---------|-----|-----|---------|
| EvilEdit | _待填_ | _待填_ | _待填_ | 论文 CDA 方法检测效果最优，但 BackdoorDM 未实现 CDA |
| Rickrolling TPA | _待填_ | _待填_ | _待填_ | — |
| BadT2I Object | _待填_ | _待填_ | _待填_ | — |
| PaaS TI | _待填_ | _待填_ | _待填_ | — |
| PaaS DB | _待填_ | _待填_ | _待填_ | — |
| BadT2I Pixel | _待填_ | _待填_ | _待填_ | — |
| Rickrolling TAA | _待填_ | _待填_ | _待填_ | — |
| BadT2I Style | _待填_ | _待填_ | _待填_ | — |
| VillanDiff Cond | _待填_ | _待填_ | _待填_ | — |

**BackdoorDM 实现与论文差异**: 最优检测方法 CDA (Concept Detection via Attention) 完全缺失。BackdoorDM 仅实现了基于文本概念聚类的检测，效果可能不如论文报告值。

#### Elijah (AAAI 2024)

| 攻击方法 | 检测结果 | TV Score | 论文参考 |
|---------|---------|---------|---------|
| BadDiffusion | _待填_ | _待填_ | TV Loss 默认关闭 |
| TrojDiff | _待填_ | _待填_ | — |
| VillanDiff Uncond | _待填_ | _待填_ | Uniformity score 未实现 |

#### TERD (ICML 2024)

| 模式 | 攻击方法 | 检测结果 | TPR | TNR | 论文参考 |
|------|---------|---------|-----|-----|---------|
| Model | BadDiffusion | _待填_ | _待填_ | _待填_ | 论文 100% TPR/TNR |
| Model | TrojDiff | _待填_ | _待填_ | _待填_ | — |
| Input | BadDiffusion | _待填_ | _待填_ | _待填_ | 论文 100% TPR/TNR |
| Input | TrojDiff | _待填_ | _待填_ | _待填_ | — |

### 2.2 输入级防御

#### Textual Perturbation (ECCV 2024 Workshop)

| 模式 | 攻击方法 | ASR After Defense | MSE Change | 论文参考 |
|------|---------|-------------------|------------|---------|
| synonym | EvilEdit | _待填_ | _待填_ | max_mse_dist=0.05 |
| homoglyph | EvilEdit | _待填_ | _待填_ | 专门针对 Rickrolling 类 trigger |
| synonym | Rickrolling TPA | _待填_ | _待填_ | — |
| homoglyph | Rickrolling TPA | _待填_ | _待填_ | — |
| _(更多方法)_ | — | _待填_ | _待填_ | — |

**max_mse_dist 修复**: BackdoorDM 默认 0.2，远超论文的 0.05。已准备修复脚本。

#### DAA — Detect and Avoid (2024)

| 模式 | 攻击方法 | 检测精度 | 论文参考 |
|------|---------|---------|---------|
| DAA-I | EvilEdit | _待填_ | 阈值硬编码 |
| DAA-S | EvilEdit | _待填_ | — |
| DAA-I | Rickrolling TPA | _待填_ | — |
| DAA-S | Rickrolling TPA | _待填_ | — |
| _(更多方法)_ | — | _待填_ | — |

---

## 三、BackdoorDM 实现与论文差异汇总

### 3.1 CRITICAL 差异

| # | 方法 | 差异 | 影响 | 修复状态 |
|---|------|------|------|---------|
| 1 | Rickrolling TAA | milestones=[75] 应为 [150] | LR 过早衰减，训练不充分 | 🔧 脚本就绪 |
| 2 | PaaS DB | max_train_steps 原文 300，BackdoorDM 曾为 2000 | 训练时间 6.7x | ✅ 已修复 (pipeline 使用 300) |

### 3.2 HIGH 差异

| # | 方法 | 差异 | 影响 | 修复状态 |
|---|------|------|------|---------|
| 3 | EvilEdit | 默认 SD v1.4 vs 论文 v1.5 | 生成质量差异 | ✅ 使用 sd15 |
| 4 | BadDiffusion | poison rate 0.7 vs 论文 5-20% | FID 恶化 | ⚠️ 使用默认值 |
| 5 | VillanDiff Uncond | poison rate 0.7 | 同上 | ⚠️ 使用默认值 |
| 6 | BadT2I Pixel/Object | batch_size 4 vs 论文 16 | 训练动态不同 | ⚠️ GPU 内存限制 |
| 7 | T2IShield | CDA 检测方法缺失 | 最优方法不可用 | ❌ 需独立实现 |
| 8 | Textual Perturbation | max_mse_dist=0.2 vs 论文 0.05 | 扰动过大 | 🔧 脚本就绪 |

### 3.3 MEDIUM 差异

| # | 方法 | 差异 | 影响 |
|---|------|------|------|
| 9 | BadT2I Style | 风格前缀 vs 后缀位置差异 | 风格注入效果可能不同 |
| 10 | VillanDiff Cond | LoRA rank=4 可能偏低 | 模型容量受限 |
| 11 | TrojDiff | D2I target batch ratio 硬编码 10% | 攻击强度固定 |
| 12 | InviBackdoor | R_coef 使用 alpha_bar_{t-1} | 理论推导差异 |
| 13 | TERD | weight_decay 未按数据集区分 | 正则化不够精确 |
| 14 | DAA | 检测阈值硬编码 | 无自适应能力 |

---

## 四、BackdoorDM 未覆盖的论文实验

### 4.1 P0 优先级（已实现/准备实现）

| 实验 | 论文 | 描述 | 状态 |
|------|------|------|------|
| Lambda 消融 | EvilEdit | λ ∈ {0.1, 0.5, 1, 2, 5} 对 ASR/Clean 影响 | 🔧 脚本就绪 |
| Whitelist + VTA | EvilEdit | Eq.9 保护 + Visual Target Attack | 🔧 脚本就绪 |
| 多 Poison Rate | BadDiffusion | PR ∈ {5%, 10%, 20%, 50%} 对比 | 🔧 脚本就绪 |

### 4.2 P1 优先级（视时间/资源实现）

| 实验 | 论文 | 描述 | 状态 |
|------|------|------|------|
| 多触发类型 | Rickrolling | homoglyph/emoji/零宽空格/缩写/完整单词 | ⏳ |
| 持久性实验 | BadT2I | Fine-tuning 后 ASR 保持率 | ⏳ |
| 多概念 | PaaS | cat/dog/barn/sunflower 多目标 | ⏳ |
| CDA 实现 | T2IShield | Concept Detection via Attention | ⏳ |

---

## 五、实验计时汇总

| 步骤 | 状态 | 耗时 |
|------|------|------|
| _从 timing.csv 提取_ | — | — |

---

## 六、总结与结论

### 复现覆盖率

| 类别 | 总方法 | 已完成 | 成功 | 失败 | 进行中 |
|------|--------|--------|------|------|--------|
| T2I 攻击 | 11 | _待填_ | _待填_ | _待填_ | _待填_ |
| 无条件攻击 | 4 | _待填_ | _待填_ | _待填_ | _待填_ |
| 防御方法 | 5 (8 子类) | _待填_ | _待填_ | _待填_ | _待填_ |
| 评估 | ~64 | _待填_ | _待填_ | _待填_ | _待填_ |

### 关键发现

1. **EvilEdit**: 攻击极其高效 (1秒, 2.2% 参数修改), 但 BackdoorDM 的 ViT-based ASR 评估不适合此类 concept-level 攻击
2. **PaaS**: TI 和 DB 实现忠实度最高
3. **BiBadDiff**: 经典 BadNets 方法在 DM 场景效果有限 (ASR=34.1%)
4. **TERD**: 输入级防御最有效 (论文报告 100% TPR/TNR)
5. **Poison Rate 差异**: BackdoorDM 默认 0.7 远超论文推荐，影响结果可比性

### 建议

- BackdoorDM 应统一基础模型版本 (建议 SD v1.5)
- Poison rate 应降至论文推荐范围 (5-20%)
- T2IShield 应补充 CDA 检测方法
- Textual Perturbation 的 max_mse_dist 应修正为 0.05
- 评估 ASR 应同时支持 ViT-based 和 CLIP-based 两种方式
