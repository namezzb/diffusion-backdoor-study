# BackdoorDM 全方法论文交叉验证汇总报告

> 生成日期: 2026-06-28
> 对照范围: 9 种攻击方法 (16 个变体) + 5 种防御方法
> 目的: 识别 BackdoorDM 实现与原始论文的差异，确保复现准确性

---

## 一、总览：风险等级汇总

### 攻击方法

| 方法 | 原始论文 | 最高风险 | 核心问题 | 复现信心 |
|------|---------|---------|---------|---------|
| EvilEdit | ACM MM 2024 | HIGH | 基础模型 SD v1.4 vs 论文 v1.5；trigger-target 对不同 | 中 |
| Rickrolling TPA | ICCV 2023 | LOW | 实现高度一致 | **高** |
| Rickrolling TAA | ICCV 2023 | **CRITICAL** | LR scheduler milestones=[75] 应为 [150] | 低 |
| BadT2I Pixel | ACM MM 2023 | HIGH | 有效 batch size 4 vs 论文 16 | 中 |
| BadT2I Object | ACM MM 2023 | HIGH | batch size 差异 + 生成式数据替代真实图像 | 中 |
| BadT2I Style | ACM MM 2023 | MEDIUM | 风格前缀 vs 后缀位置差异 | 中高 |
| BadT2I ObjectAdd | BackdoorDM 自创 | INFO | 非论文原创变体，无法交叉验证 | N/A |
| PaaS TI | AAAI 2024 | LOW | 几乎完全一致 | **高** |
| PaaS DB | AAAI 2024 | **CRITICAL** | max_train_steps 300→2000 (6.7x) | 低 |
| BiBadDiff | 2024 | HIGH | 框架异构 (PyTorch Lightning)，需额外转换 | 中 |
| VillanDiff Uncond | NeurIPS 2023 | MEDIUM | poison rate 0.7 过高；调试 print 未清理 | 中高 |
| VillanDiff Cond | NeurIPS 2023 | MEDIUM | LoRA rank=4 可能偏低；50K 步数未验证 | 中 |
| BadDiffusion | CVPR 2023 | HIGH | poison rate 0.7 vs 论文 5-20%；触发器差异大 | 中 |
| TrojDiff | CVPR 2023 | MEDIUM | D2I target batch ratio 硬编码 10% | 中高 |
| InviBackdoor | 2024 | MEDIUM | R_coef 公式使用 alpha_bar_{t-1} 不同推导 | 中 |

### 防御方法

| 方法 | 原始论文 | 最高风险 | 核心问题 | 评分 |
|------|---------|---------|---------|------|
| T2IShield | ECCV 2024 | HIGH | 最优检测方法 CDA 缺失；Mitigation 用 UCE 而非 Refact | B- |
| Elijah | AAAI 2024 | MEDIUM | TV Loss 默认关闭；uniformity score 未实现 | B |
| TERD | ICML 2024 | MEDIUM | weight_decay 未按数据集区分；KL 阈值硬编码 | B+ |
| Textual Perturbation | ECCV 2024 W | HIGH | 无量化评估；max_mse_dist=0.2 远超论文 0.05 | C |
| DAA | 2024 | MEDIUM | 检测阈值硬编码为超精度浮点数，无自适应 | B- |

---

## 二、必须修复的 CRITICAL/HIGH 问题

### CRITICAL（必须在实验前修复）

| # | 方法 | 问题 | 修复方案 |
|---|------|------|---------|
| 1 | **Rickrolling TAA** | LR scheduler `milestones=[75]` 应为 `[150]`（从 TPA 复制时遗漏修改） | 修改 `rickrolling_TAA.py` 中 `milestones` 参数 |
| 2 | **PaaS DB** | `max_train_steps=2000`，论文明确写 300 步（代码注释中保留了 `#300`） | 改回 300 或同时运行 300/2000 对比 |

### HIGH（强烈建议修复）

| # | 方法 | 问题 | 修复方案 |
|---|------|------|---------|
| 3 | **EvilEdit** | 基础模型 SD v1.4 vs 论文 v1.5 | 使用 `--model_ver sd15` 覆盖 |
| 4 | **BadDiffusion** | poison rate 默认 0.7，论文推荐 5-20% | 修改配置，建议先用 0.1 |
| 5 | **VillanDiff Uncond** | poison rate 同上 0.7 | 同上 |
| 6 | **BadT2I Pixel/Object** | 有效 batch size 4 vs 论文 16 | 增加 `gradient_accumulation_steps` 或 batch_size |
| 7 | **T2IShield** | 最优检测方法 CDA 完全缺失 | 需要独立实现 CDA |
| 8 | **Textual Perturbation** | `max_mse_dist=0.2` 远超论文最大 0.05 | 修改为论文值 |
| 9 | **BiBadDiff** | 需要 v1-5-pruned.ckpt + PyTorch Lightning + ckpt→diffusers 转换 | 按脚本步骤执行 |

---

## 三、论文中重要实验但代码中缺失的汇总

### 3.1 需要独立实现的实验

| 优先级 | 论文 | 缺失实验 | 工作量估计 |
|--------|------|---------|-----------|
| P0 | EvilEdit | Whitelist 保护机制 + VTA (Visual Target Attack) | 2-3h |
| P0 | EvilEdit | Lambda 消融 {0.1, 0.5, 1, 2, 5} | 1h |
| P0 | BadDiffusion | 多 poison rate 对比 (5%/10%/20%/50%) | 4×3h |
| P1 | Rickrolling | 多种触发类型对比 (homoglyph, emoji, 零宽空格, 缩写, 完整单词) | 3-4h |
| P1 | BadT2I | 多种 trigger-target 组合 + 持久性实验 | 4-6h |
| P1 | PaaS | 多概念对象 (cat, dog, barn, sunflower) + 触发器影响分析 | 3-4h |
| P1 | T2IShield | CDA 检测方法实现 | 4-6h |
| P2 | 各方法 | 后门在 fine-tuning/LoRA 下的持久性评估 | 6-8h |
| P2 | VillanDiff | psi 参数消融实验 | 2-3h |
| P2 | TrojDiff | 多类别 In-D2D + 多目标图像 D2I | 3-4h |
| P2 | Elijah | Uniformity score 模型检测指标实现 | 2h |
| P3 | TERD | weight_decay 按数据集自适应 + adaptive attack | 2-3h |

### 3.2 各方法缺失的评估指标

| 方法 | 论文使用的指标 | BackdoorDM 已有 | 需补充 |
|------|--------------|----------------|--------|
| EvilEdit | ASR, FID, CLIP Score | ACCASR, CLIP_p, CLIP_c, FID | VTA-ASR |
| Rickrolling | CLIP-based 风格相似度 | CLIP_p | 风格 CLIP Score |
| BadT2I | ASR, FID, MSE, LPIPS | ACCASR, FID, MSE, LPIPS | 基本完整 |
| PaaS | CLIP-ASR, FID | ACCASR, FID | CLIP-ASR |
| BadDiffusion | MSE(target), FID, IS | MSE, FID | IS (Inception Score) |
| TrojDiff | FID, IS | FID | IS |
| VillanDiff | FID, MSE | FID, MSE | 基本完整 |
| InviBackdoor | MSE, FID, LPIPS | MSE, FID | LPIPS |

---

## 四、共性问题

### 4.1 基础模型不统一
- BackdoorDM 大部分方法默认 SD v1.4，但 EvilEdit (v1.5) 和 VillanDiff-Cond (v1.5) 使用不同版本
- **建议**: 统一使用 SD v1.5，通过 `--model_ver sd15` 覆盖

### 4.2 Poison Rate 偏高
- BadDiffusion, VillanDiffusion 默认 poison rate = 0.7 (70%)
- 原始论文推荐 5-20% 即可有效
- 过高的 poison rate 会使结果不可比
- **建议**: 按论文推荐值设置，同时补充 poison rate 消融

### 4.3 单组 Trigger-Target 配置
- 所有方法仅配置一组 trigger-target 对
- 论文通常测试多组配置
- **建议**: 先用默认配置完成基线，再扩展到论文中的其他配置

### 4.4 评估代码独立
- 攻击代码不包含评估逻辑
- 评估需要单独运行 `evaluation/main_eval.py`
- 需确保评估流程正确绑定各方法的结果路径

### 4.5 调试代码残留
- VillanDiffusion loss.py (~1237 行) 中大量 print 语句未清理
- **建议**: 在运行前注释掉或重定向到 log 文件

---

## 五、修复脚本清单

以下修改应在实验开始前应用到服务器的 BackdoorDM 仓库：

```bash
# 1. Rickrolling TAA: milestones 修复
sed -i "s/milestones': \[75\]/milestones': [150]/" attack/t2i_gen/rickrolling/rickrolling_TAA.py

# 2. PaaS DB: 训练步数改回论文值 (同时保留 2000 步对比)
# 在 paas_db.py 中 max_train_steps 默认值改为 300

# 3. BadDiffusion/VillanDiff: poison rate
sed -i 's/poison_rate: 0.7/poison_rate: 0.1/' attack/uncond_gen/configs/bd_config_fix.yaml

# 4. base_config: model_ver
sed -i "s/model_ver: 'sd14'/model_ver: 'sd15'/" attack/t2i_gen/configs/base_config.yaml

# 5. Textual Perturbation: max_mse_dist
# 需要在代码中修改默认参数

# 6. VillanDiffusion: 注释掉调试 print
cd attack/uncond_gen/villan_diffusion/
grep -n "^[[:space:]]*print(" loss.py | head -20
```

---

## 六、实验执行建议

### Phase 0: 修复 & 验证 (SSH 恢复后立即执行)
1. 应用上述修复脚本
2. 运行 EvilEdit 评估（已有后门模型，验证评估流程）
3. 运行 PaaS TI（最忠实实现，快速验证）

### Phase 1: 快速方法 (~4h)
- EvilEdit, EvilEdit NumAdd, Rickrolling TPA, Rickrolling TAA (修复后)

### Phase 2: 中速方法 (~12h)
- PaaS TI, PaaS DB (300 步), BadT2I Pixel

### Phase 3: 慢速方法 (~24h each)
- BadT2I Object, BadT2I Style, BadT2I ObjectAdd

### Phase 4: 无条件攻击 (~20h total)
- BadDiffusion (poison_rate=0.1), TrojDiff, VillanDiff Uncond, InviBackdoor

### Phase 5: 超长攻击 (~30h each)
- VillanDiff Cond, BiBadDiff

### Phase 6: 评估 + 防御 (~12h)
- 全量评估 + T2IShield + Elijah + TERD + TextPerturb + DAA

---

## 七、详细报告索引

| 报告 | 路径 | 覆盖方法 |
|------|------|---------|
| T2I 攻击组 1 | `reports/backdoordm_t2i_cross_reference_report.md` | EvilEdit, Rickrolling TPA/TAA, BadT2I Pixel |
| T2I 攻击组 2 | *(agent 2 output)* | BadT2I Object/Style/ObjectAdd, PaaS TI/DB |
| 无条件攻击 + BiBadDiff | `reports/backdoordm_crossref_report.md` | BadDiffusion, TrojDiff, VillanDiff, InviBackdoor, BiBadDiff |
| 防御方法 | `reports/defense_cross_reference_report.md` | T2IShield, Elijah, TERD, TextPerturb, DAA |
