# BackdoorDM 防御方法交叉对照报告

> 对照 BackdoorDM benchmark 中 5 个防御方法的代码实现与原始论文的差异分析

---

## 1. T2IShield

### 1.1 论文信息

| 字段 | 内容 |
|------|------|
| 标题 | T2IShield: Defending Against Backdoors on Text-to-Image Diffusion Models |
| 作者 | Zhongqi Wang, Jie Zhang, Shiguang Shan, Xilin Chen |
| 发表 | ECCV 2024 |
| arXiv | 2407.04215 |
| 代码 | https://github.com/Robin-WZQ/T2IShield |

### 1.2 实现路径

| 模块 | 路径 |
|------|------|
| 主入口 | `defense/model_level/t2ishield/t2ishield.py` |
| FFT检测 | `defense/model_level/t2ishield/substeps/detect_fft.py` |
| CLIP定位 | `defense/model_level/t2ishield/substeps/locate_clip.py` |
| 后门消除 | `defense/model_level/t2ishield/substeps/backdoor_mitigation.py` |
| 配置文件 | `defense/model_level/configs/t2ishield.yaml` |

### 1.3 超参数对照表

| 超参数 | 论文值 | BackdoorDM值 | 是否一致 |
|--------|--------|-------------|---------|
| FFT阈值 (F-norm threshold) | 2.5 (最优) | 2.5 | 一致 |
| CLIP定位阈值 | 0.85 (最优, CLIP) | 0.8 | **不一致** |
| CLIP模型 | openai/clip-vit-large-patch14 (论文未明确指定) | openai/clip-vit-large-patch14 | 一致 |
| 后门样本数 | 3000 (检测) / 1000 (定位) | 500 | **不一致** |
| 干净样本数 | 3000 (检测) / 1000 (定位) | 500 | **不一致** |
| 注意力分辨率 | 16x16 | 16x16 | 一致 |
| 注意力收集位置 | "up", "down" | "up", "down" | 一致 |
| 推理步数 | 50 | 50 | 一致 |
| guidance_scale | 7.5 | 7.5 | 一致 |
| 种子 | 未指定 | 678 | -- |
| mitigation: erase_scale | -- (论文未给出) | 0.1 | -- |
| mitigation: preserve_scale | -- | 0.1 | -- |
| mitigation: lamb | -- | 0.1 | -- |

### 1.4 实现差异分析

#### (a) 检测方法不完整
- 论文提出两种检测方法: **FTT** (Frobenius Norm Threshold Truncation) 和 **CDA** (Covariance Discriminant Analysis)
- BackdoorDM **仅实现了 FTT**，完全缺失 CDA 方法
- 论文中 CDA 的 F1 (88.9%) 优于 FTT (86.5%)，CDA 是论文推荐方法
- **风险**: 缺失论文最优检测方法，只用了次优方案

#### (b) CLIP定位阈值偏差
- 论文ablation实验显示 CLIP最优阈值为 0.85 (Figure 5)
- BackdoorDM 使用 0.8，可能导致定位性能偏差
- 论文也测试了 DINOv2 作为对比，BackdoorDM 不支持 DINOv2

#### (c) 评估规模缩小
- 论文使用 3000 backdoor + 3000 benign (检测), 1000+1000 (定位)
- BackdoorDM 缩减至 500+500，显著小于论文设定
- 较小评估集可能导致指标方差较大

#### (d) Mitigation 来源
- BackdoorDM 的 `backdoor_mitigation.py` 直接标注来源于 Unified Concept Editing (UCE)
- 但论文实验表明 **Refact 效果远优于 UCE** (ASR: Refact 0.01 vs UCE 0.20; ASB: Refact 0.85 vs UCE 0.53)
- BackdoorDM 使用的是 UCE 的 closed-form editing (edit_model)，而非 Refact
- 实际上 BackdoorDM 中 `backdoor_mitigation` 将 trigger 映射到空字符串 `' '`，这是 UCE 式的概念擦除
- **风险**: 论文推荐的最优mitigation方法 (Refact) 未被实现

### 1.5 缺失实验

- CDA 检测方法（PCA降维 + LDA分类）
- DINOv2 作为定位工具的对比
- Refact 作为mitigation方法
- ASB (Average Similarity to Benign) 指标评估
- 多 trigger 类型的全面评估（论文测试16种trigger）

### 1.6 风险项

| 风险 | 严重度 | 说明 |
|------|--------|------|
| CDA 缺失 | 高 | 论文最优检测方法未实现 |
| Mitigation 方法错配 | 中 | 使用 UCE 而非论文推荐的 Refact |
| 评估规模缩小 | 中 | 500 vs 3000 样本，影响结果可靠性 |
| CLIP阈值偏差 | 低 | 0.8 vs 0.85，可能影响定位F1 |

---

## 2. Elijah

### 2.1 论文信息

| 字段 | 内容 |
|------|------|
| 标题 | Elijah: Eliminating Backdoors Injected in Diffusion Models via Distribution Shift |
| 作者 | Shengwei An, Sheng-Yen Chou, Kaiyuan Zhang, Qiuling Xu, Guanhong Tao, Guangyu Shen, Siyuan Cheng, Shiqing Ma, Pin-Yu Chen, Tsung-Yi Ho, Xiangyu Zhang |
| 发表 | AAAI 2024 |
| arXiv | 2312.00050 |
| 代码 | 无独立公开仓库 |

### 2.2 实现路径

| 模块 | 路径 |
|------|------|
| 主入口 | `defense/model_level/Elijah/elijah.py` |
| 配置文件 | `defense/model_level/configs/elijah.yaml` |

### 2.3 超参数对照表

| 超参数 | 论文值 | BackdoorDM值 | 是否一致 |
|--------|--------|-------------|---------|
| Trigger inversion: R_coef_T | 0.5 (论文 λ_TV 未明确给出) | 0.5 | 待验证 |
| Trigger inversion: optimizer | Adam | Adam | 一致 |
| Trigger inversion: lr | 0.1 | 0.1 | 一致 |
| Trigger inversion: epochs | 100 | 100 | 一致 |
| Trigger inversion: loss | L1 | L1 | 一致 |
| Deshift loss: epoch | 11 | 11 | 一致 |
| Deshift loss: clean_rate | 0.1 | 0.1 | 一致 |
| Deshift: TrojDiff epoch | 500 | 500 | 一致 |
| compute_tvloss | 论文有 TV loss | False (默认关闭) | **不一致** |
| batch_size (256 img) | 20 | 20 | 一致 |
| batch_size (128 img) | 50 | 50 | 一致 |
| seed | 未指定 | 35 | -- |

### 2.4 实现差异分析

#### (a) TV Loss 默认关闭
- 论文提出 trigger inversion 时使用 Total Variance (TV) loss 来衡量 inverted trigger 的噪声水平
- BackdoorDM 配置中 `compute_tvloss=False`，默认不计算 TV loss
- 这意味着 trigger inversion 质量可能低于论文报告
- 但代码中保留了 TV loss 的计算逻辑，可手动开启

#### (b) Deshift Loss 实现细节
- BadDiffusion 的 deshift loss: `MSE(backdoor_pred, frozen_benign_pred) + MSE(benign_pred, frozen_benign_pred)`
- TrojDiff 的 deshift loss 使用 `sum over dims` 而非 `mean MSE`，这是代码中的实现差异
- 论文原文描述 deshift 为对齐 backdoor 模型与 benign 模型的分布，BackdoorDM 的实现与此一致

#### (c) 模型检测方法
- 论文检测方法: 基于 inverted trigger 生成图像的 uniformity score + TV loss
- BackdoorDM 的检测逻辑简化: 仅通过 trigger inversion 后直接进入 removal 阶段
- **缺失**: uniformity score 计算、多采样器的鲁棒性测试

#### (d) SDE 支持
- BackdoorDM 包含 `trigger_inversion_sde` 函数，支持 VP/VE SDE 变体
- 这与论文评估了 DDPM/NCSN/LDM 三种类型一致

### 2.5 缺失实验

- Uniformity score 模型检测指标
- TV loss 在 trigger inversion 中的作用评估
- 多采样器 (13种) 的鲁棒性测试
- Fine-tuning 是否能移除后门的对比实验

### 2.6 风险项

| 风险 | 严重度 | 说明 |
|------|--------|------|
| TV Loss 默认关闭 | 中 | 可能降低 trigger 反演质量 |
| 检测指标缺失 | 中 | uniformity score 未实现 |
| TrojDiff deshift 差异 | 低 | sum vs mean 可能影响收敛 |

---

## 3. TERD (Model-Level + Input-Level)

### 3.1 论文信息

| 字段 | 内容 |
|------|------|
| 标题 | TERD: A Unified Framework for Safeguarding Diffusion Models Against Backdoors |
| 作者 | Yichuan Mo, Hui Huang, Mingjie Li, Ang Li, Yisen Wang |
| 发表 | ICML 2024 |
| arXiv | 2409.05294 |
| 代码 | https://github.com/PKU-ML/TERD |

### 3.2 实现路径

| 模块 | 路径 |
|------|------|
| 模型级检测+消除 | `defense/model_level/Terd_model/terd_model.py` |
| 输入级检测 | `defense/input_level/Terd_input/terd_input.py` |
| 反演损失 | `defense/input_level/Terd_input/reverse_loss.py` |
| 模型级配置 | `defense/model_level/configs/terd_model.yaml` |

### 3.3 超参数对照表

| 超参数 | 论文值 | BackdoorDM值 | 是否一致 |
|--------|--------|-------------|---------|
| Trigger estimation: optimizer | SGD | SGD | 一致 |
| Trigger estimation: lr | 0.5 | 0.5 | 一致 |
| Trigger estimation: scheduler | CosineAnnealing | CosineAnnealing | 一致 |
| Trigger estimation: iterations | 3000 | 3000 | 一致 |
| Trigger estimation: weight_decay | 5e-5 (CIFAR-10) / 5e-4 (larger) | 5e-5 (固定) | **部分不一致** |
| Trigger refinement: iterations | 1000 (论文) | iterations/3=1000 | 一致 |
| Trigger refinement: clip_norm (δ) | 0.01T | 0.01 | 一致 |
| Trigger refinement: infer_steps (n) | 10 | 10 | 一致 |
| TrojDiff: lr2 (gamma优化) | 未指定 | 0.001 | -- |
| batch_size | 未明确指定 | 16 | -- |
| Model detection: N_m | 未明确给出具体值 | -0.4 | 待验证 |
| Model detection: N_v | 未明确给出具体值 | 0.003 | 待验证 |
| 后门消除: epoch | 同 Elijah | 11 | 一致 |
| 后门消除: clean_rate | 同 Elijah | 0.1 | 一致 |
| Input detection: num_detect | 论文未明确 | 10000 | -- |

### 3.4 实现差异分析

#### (a) weight_decay 未按数据集区分
- 论文明确: CIFAR-10 使用 γ=5e-5, 更大数据集使用 γ=5e-4
- BackdoorDM 配置固定为 5e-5，不随数据集切换
- **影响**: 在较大分辨率数据集上可能导致 trigger 反演质量下降

#### (b) 后门消除直接复用 Elijah
- `terd_model.py` 的 `remove_baddiffusion` / `remove_trojdiff` 直接 import 自 Elijah
- 论文虽然提到 removal 部分与 Elijah 类似，但 TERD 的核心贡献在于检测而非消除
- 这种复用是合理的

#### (c) Input Detection 实现
- `terd_input.py` 实现了基于多元正态分布的输入检测
- TrojDiff: 使用 `MultivariateNormal` 分布的 `log_prob` 对比
- BadDiffusion: 使用简化的平方范数概率 `prob = -0.5 * (dim*log(2pi) + (x-mu)^T @ (x-mu))`
- 论文声称 100% TPR/TNR，BackdoorDM 实现了完整的 TPR/TNR 评估

#### (d) Reverse Loss 中的方差缩减
- `reverse_loss.py` 中 `p_losses_diffuser` 使用了 paired noise 技术进行方差缩减:
  ```python
  loss = 0.5*(e-output-(e_1-output_1)).square().sum(dim=(1,2,3)).mean(dim=0)
  ```
- 这与论文中的统一反演损失公式一致

#### (e) Model Detection KL 散度
- 代码实现:
  ```python
  kl_divergence = (-log(gamma) + (gamma^2 + mu^2 - 1) / 2)
  M_r = kl_divergence.mean(dim=0) - N_m
  V_r = (kl - kl.mean(dim=0))^2.mean(dim=0) - N_v
  ```
- N_m=-0.4, N_v=0.003 是硬编码阈值，论文中未明确给出这些具体数值
- **风险**: 这些阈值可能是针对特定数据集调优的，换数据集需重新校准

### 3.5 缺失实验

- 不同 poisoning rate 下的鲁棒性测试
- 不同 trigger size 下的性能评估
- Adaptive attack 场景
- SDE-based 模型的扩展评估
- weight_decay 按数据集分辨率自动切换

### 3.6 风险项

| 风险 | 严重度 | 说明 |
|------|--------|------|
| weight_decay 固定值 | 中 | 论文要求按数据集调整，代码未实现 |
| N_m/N_v 硬编码 | 中 | KL 检测阈值无自适应机制 |
| 大分辨率数据集未测试 | 低 | 可能需调整超参 |

---

## 4. Textual Perturbation

### 4.1 论文信息

| 字段 | 内容 |
|------|------|
| 标题 | Defending Text-to-image Diffusion Models: Surprising Efficacy of Textual Perturbations Against Backdoor Attacks |
| 作者 | Oscar Chew, Po-Yi Lu, Jayden Lin, Hsuan-Tien Lin |
| 发表 | ECCV 2024 Workshop |
| arXiv | 2408.15721 |
| 代码 | https://github.com/oscarchew/t2i-backdoor-defense |

### 4.2 实现路径

| 模块 | 路径 |
|------|------|
| 主入口 | `defense/input_level/textual_perturbation/textual_perturbation.py` |
| 扰动函数 | `defense/input_level/textual_perturbation/func.py` |

### 4.3 超参数对照表

| 超参数 | 论文值 | BackdoorDM值 | 是否一致 |
|--------|--------|-------------|---------|
| Synonym: pct_words_to_swap | 因 attack 而异 (0.5~1) | 0.5 | **部分不一致** |
| Synonym: transformations_per_example | 未指定 | 20 | -- |
| Synonym: max_mse_dist | 因 attack 而异 (0.01~0.05) | 0.2 | **不一致** |
| Translation: 目标语言 | 西班牙语等多种 | 西班牙语 (Helsinki-NLP/opus-mt) | 一致 |
| Homoglyph: pct_words_to_swap | 1 (大多情况) | 1 | 一致 |
| Random char: pct_words_to_swap | 1 | 1 | 一致 |
| Random char: max_mse_dist | 0.01~0.05 | 0.01 | 待验证 |
| 种子 | 未指定 | 54 (FixSeedAugmenter) | -- |

### 4.4 实现差异分析

#### (a) 超参未按攻击方法区分
- 论文 Table 5 明确: 不同攻击方法使用不同的超参组合
  - Rickrolling: pct_words_to_swap=0.5, max_mse_dist=0.01
  - VillanDiffusion (latte coffee): pct_words_to_swap=1, 无约束
  - VillanDiffusion (mignneko): pct_words_to_swap=1, max_mse_dist=0.05
  - Textual Inversion: pct_words_to_swap=1, max_mse_dist=0.05
- BackdoorDM 使用固定超参 (pct_words_to_swap=0.5, max_mse_dist=0.2)
- **风险**: max_mse_dist=0.2 远大于论文任何设定值，可能过度扰动语义

#### (b) 扰动顺序
- 论文 (Figure 2): Homoglyph → Translation/Synonym → Random Perturbation (按此顺序执行)
- BackdoorDM: 4种模式独立调用 (synonym/translation/homoglyph/random_chara)，不组合
- **风险**: 论文的防御是组合多种扰动，单独使用效果可能不如论文报告

#### (c) 无量化评估
- 论文提供了 ASR 和 FID 的完整评估 (Table 3)
- BackdoorDM 代码中仅生成扰动后的 prompt 并打印日志，没有 ASR/FID 评估逻辑
- **风险**: 无法验证防御效果

#### (d) 攻击覆盖范围
- 论文测试: Rickrolling, VillanDiffusion, Textual Inversion
- BackdoorDM 集成了对 EvilEdit 等更多攻击的支持
- 但缺乏论文中 Textual Inversion 攻击的配置

### 4.5 缺失实验

- 组合扰动流水线 (论文核心方案)
- ASR/FID 量化评估
- 不同攻击方法使用不同超参的自适应配置
- Textual Inversion 攻击场景
- Cross-attention map 可视化分析

### 4.6 风险项

| 风险 | 严重度 | 说明 |
|------|--------|------|
| 无量化评估 | 高 | 只生成扰动prompt，不评估ASR/FID |
| max_mse_dist 偏大 | 高 | 0.2 远超论文最大0.05，可能破坏语义 |
| 扰动未组合 | 中 | 单独使用而非论文的级联流水线 |
| 超参未按攻击区分 | 中 | 论文对每种攻击有不同设定 |

---

## 5. DAA (Dynamic Attention Analysis)

### 5.1 论文信息

| 字段 | 内容 |
|------|------|
| 标题 | Dynamic Attention Analysis for Backdoor Detection in Text-to-Image Diffusion Models |
| 作者 | Zhongqi Wang, Jie Zhang, Shiguang Shan, Xilin Chen |
| 发表 | IEEE TPAMI 2025 |
| arXiv | 2504.20518 |
| 代码 | https://github.com/Robin-WZQ/DAA |

### 5.2 实现路径

| 模块 | 路径 |
|------|------|
| 主入口 | `defense/input_level/daa/daa.py` |
| DAA-I | `defense/input_level/daa/detect_method/daai.py` |
| DAA-S | `defense/input_level/daa/detect_method/daas.py` |
| 配置文件 | `defense/input_level/daa/config.yaml` |

### 5.3 超参数对照表

| 超参数 | 论文值 | BackdoorDM值 | 是否一致 |
|--------|--------|-------------|---------|
| DAA-I 阈值 | 论文通过训练集确定 | 0.000489037214720156 (硬编码) | **不一致** |
| DAA-S 阈值 | 论文通过训练集确定 | 0.0015001561188200604 (硬编码) | **不一致** |
| 注意力分辨率 | 16x16 | 16x16 | 一致 |
| 扩散步数 | 50 | 50 | 一致 |
| 后门样本数 | 论文未指定固定值 | 500 | -- |
| 干净样本数 | 论文未指定固定值 | 500 | -- |
| DAA-I: 使用的时间步 | 论文分析多个步骤 | 索引 [3] 和 [4] | 待验证 |
| DAA-S: EOS衰减率 | 论文描述动力学 | -10 (vs 其他节点 -1) | 待验证 |
| DAA-S: 前N个值求和 | 论文未明确 | 前7个值 | 待验证 |
| 种子 | 未指定 | 678 | -- |

### 5.4 实现差异分析

#### (a) 阈值硬编码
- 论文方法论: 阈值应通过训练集上的 clean/backdoor 样本统计确定
- BackdoorDM: DAA-I 和 DAA-S 的阈值都是硬编码的超精度浮点数
- 这些值显然是从特定实验run中提取的，换模型/攻击后可能完全不适用
- **风险**: 阈值无自适应能力，泛化性存疑

#### (b) DAA-I 检测逻辑
- 代码实现:
  ```python
  value = (delta_A_eos[3]-delta_A_mean[3]) + (delta_A_eos[4]-delta_A_mean[4])
  if value < threshold → backdoor
  ```
- 仅使用时间步索引 3 和 4 的 delta 值，论文中 Relative Evolution Rate (RER) 的计算可能覆盖更多时间步
- 论文提出的 RER 是对所有时间步的动态特征分析，代码简化为2个特定步骤

#### (c) DAA-S ODE 求解
- 论文: 使用 RKF4(5) (Runge-Kutta-Fehlberg) 方法求解 ODE
- BackdoorDM: 使用 `scipy.integrate.solve_ivp` (默认 RK45)
- 动力学方程: dX/dt = F*X + c*A(t)*X，其中 F 是衰减矩阵，A(t) 是 Laplacian
- EOS 节点衰减率 -10，其他节点 -1，这是代码中的特定设定
- **差异**: ODE 求解器的具体参数设置可能与论文不完全一致

#### (d) 代码重复
- `daai.py` 和 `daas.py` 都包含完整的 `AttentionMetrics` 类（复制粘贴）
- 两个文件中的 `AttentionStore`、注意力收集逻辑完全重复
- 这是工程质量问题，不影响正确性

#### (e) 检测粒度
- 论文评估了 6 种 (TPAMI版本) 代表性后门攻击场景
- 论文报告: 平均 F1=79.27%, AUC=86.27% (v3版本)
- BackdoorDM 仅计算 Precision/Recall/F1，缺少 AUC 指标

### 5.5 缺失实验

- AUC 评估指标
- 阈值自适应确定机制
- 多种攻击方法下的完整 RER 可视化
- SDXL 模型的注意力分析 (论文后续版本支持)
- 与 T2IShield 的对比实验

### 5.6 风险项

| 风险 | 严重度 | 说明 |
|------|--------|------|
| 阈值硬编码 | 高 | 无自适应，换攻击/模型后可能失效 |
| DAA-I 时间步简化 | 中 | 仅用索引3/4而非完整RER |
| AUC缺失 | 中 | 论文核心评估指标之一 |
| 代码重复 | 低 | daai.py 与 daas.py 共享大量重复代码 |

---

## 总结对比

### 实现完整度评分

| 防御方法 | 核心算法 | 超参一致性 | 评估完整度 | 总体评分 |
|----------|---------|-----------|-----------|---------|
| T2IShield | 2/3 (缺CDA) | 中 (阈值偏差) | 中 (规模缩小) | **B-** |
| Elijah | 3/3 | 高 (TV默认关) | 低 (缺检测指标) | **B** |
| TERD | 3/3 | 中 (weight_decay固定) | 中 | **B+** |
| Textual Perturbation | 1/1 (但不组合) | 低 (max_mse_dist偏大) | 低 (无ASR评估) | **C** |
| DAA | 2/2 | 低 (阈值硬编码) | 中 (缺AUC) | **B-** |

### 最关键的问题汇总

1. **T2IShield**: CDA 检测方法完全缺失；Mitigation 使用 UCE 而非论文推荐的 Refact
2. **Elijah**: TV Loss 默认关闭；模型检测指标 (uniformity score) 未实现
3. **TERD**: weight_decay 未按数据集分辨率调整；KL 检测阈值 N_m/N_v 硬编码
4. **Textual Perturbation**: 无量化评估逻辑；max_mse_dist=0.2 远超论文最大0.05；扰动未组合
5. **DAA**: 检测阈值硬编码为超精度浮点数，无自适应机制

### 复现建议优先级

1. **Textual Perturbation** — 问题最多，需添加 ASR/FID 评估、修正 max_mse_dist、实现组合扰动
2. **T2IShield** — 需实现 CDA 检测方法，调整 CLIP 阈值
3. **DAA** — 需实现阈值自适应机制，添加 AUC 评估
4. **TERD** — 需按数据集调整 weight_decay
5. **Elijah** — 需开启 TV Loss，实现 uniformity score
