# 防御方法论文索引

> BackdoorDM 复现项目中使用的 5 篇防御方法论文。

---

## 1. T2IShield

| 项目 | 内容 |
|------|------|
| **标题** | T2IShield: Defending Against Backdoors on Text-to-Image Diffusion Models |
| **arXiv ID** | 2407.04215 |
| **会议** | ECCV 2024 |
| **作者** | Zhongqi Wang, Jie Zhang, Shiguang Shan, Xilin Chen |
| **PDF** | `pdf/2407.04215.pdf` |
| **防御类型** | Model-level (检测 + 定位 + 缓解) |
| **BackdoorDM 代码路径** | `defense/model_level/t2ishield/t2ishield.py` |
| **实验脚本** | `experiments/backdoordm_reproduce/scripts/08_defense_t2ishield.sh` |

### 核心方法
基于 cross-attention map 上的"同化现象"（Assimilation Phenomenon）检测后门样本。提出两种检测方法：Frobenius 范数阈值截断和协判别分析。还提出二分搜索定位触发器，并结合概念编辑缓解后门。

### 关键结果
- 后门样本检测 F1: **88.9%**
- 触发器定位 F1: **86.4%**
- 缓解率: **99%** 的中毒样本被无效化

---

## 2. Elijah

| 项目 | 内容 |
|------|------|
| **标题** | Elijah: Eliminating Backdoors Injected in Diffusion Models via Distribution Shift |
| **arXiv ID** | 2312.00050 |
| **会议** | AAAI 2024 |
| **作者** | Shengwei An, Sheng-Yen Chou, Kaiyuan Zhang, et al. |
| **PDF** | `pdf/2312.00050.pdf` |
| **防御类型** | Model-level (检测 + 移除) |
| **BackdoorDM 代码路径** | `defense/model_level/Elijah/elijah.py` |
| **实验脚本** | `experiments/backdoordm_reproduce/scripts/09_defense_elijah_terd.sh` |

### 核心方法
首个扩散模型后门检测与移除框架。通过分布偏移（distribution shift）检测后门模型，并将后门效果降至接近零而不显著牺牲模型效用。在 DDPM、NCSN、LDM 三类模型上验证。

### 关键结果
- 检测准确率: 接近 **100%**
- 后门效果降低: 降至接近 **0%**
- 模型效用: 无显著牺牲
- 测试范围: 3 类模型 × 13 种采样器 × 3 种后门攻击

---

## 3. TERD

| 项目 | 内容 |
|------|------|
| **标题** | TERD: A Unified Framework for Safeguarding Diffusion Models Against Backdoors |
| **arXiv ID** | 2409.05294 |
| **会议** | ICML 2024 |
| **作者** | Yichuan Mo, Hui Huang, Mingjie Li, Ang Li, Yisen Wang |
| **PDF** | `pdf/2409.05294.pdf` |
| **防御类型** | Model-level (模型检测) + Input-level (输入检测) |
| **BackdoorDM 代码路径** | `defense/model_level/Terd_model/terd_model.py` + `defense/input_level/Terd_input/terd_input.py` |
| **实验脚本** | `experiments/backdoordm_reproduce/scripts/09_defense_elijah_terd.sh` |

### 核心方法
构建统一建模推导可访问的反向损失，采用触发器反转策略（从先验分布采样噪声 → 差分多步采样器精炼）。从噪声空间检测后门，首次提出扩散模型的输入检测方法和基于 KL 散度的模型检测算法。

### 关键结果
- TPR (True Positive Rate): **100%**
- TNR (True Negative Rate): **100%**
- 适用于不同分辨率的数据集
- 可适配其他 SDE-based 模型

---

## 4. Textual Perturbation

| 项目 | 内容 |
|------|------|
| **标题** | Defending Text-to-image Diffusion Models: Surprising Efficacy of Textual Perturbations Against Backdoor Attacks |
| **arXiv ID** | 2408.15721 |
| **会议** | ECCV 2024 Workshop |
| **作者** | Oscar Chew, Po-Yi Lu, Jayden Lin, Hsuan-Tien Lin |
| **PDF** | `pdf/2408.15721.pdf` |
| **防御类型** | Input-level (文本扰动) |
| **BackdoorDM 代码路径** | `defense/input_level/textual_perturbation/textual_perturbation.py` |
| **实验脚本** | `experiments/backdoordm_reproduce/scripts/10_defense_input_level.sh` |

### 核心方法
通过对输入文本施加语义保持的扰动（同义词替换、翻译、同形字替换、随机字符扰动）来破坏后门触发器。从文本嵌入空间和 cross-attention map 两个角度分析有效性。

### 关键结果
- 对 Rickrolling: ASR 从 1.00 降至 **0.00**
- 对 VillanDiffusion: ASR 从 0.99-1.00 降至 **0.28-0.30**
- 对 Textual Inversion: ASR 从 1.00 降至 **0.00**
- FID 保持或改善（如 Rickrolling FID 从 41.36 降至 31.25）

---

## 5. DAA (Dynamic Attention Analysis)

| 项目 | 内容 |
|------|------|
| **标题** | Dynamic Attention Analysis for Backdoor Detection in Text-to-Image Diffusion Models |
| **arXiv ID** | 2504.20518 |
| **会议** | TPAMI 2025 |
| **作者** | Zhongqi Wang, Jie Zhang, Shiguang Shan, Xilin Chen |
| **PDF** | `pdf/2504.20518.pdf` |
| **防御类型** | Input-level (检测) |
| **BackdoorDM 代码路径** | `defense/input_level/daa/daa.py` |
| **实验脚本** | `experiments/backdoordm_reproduce/scripts/10_defense_input_level.sh` |

### 核心方法
利用扩散模型的动态特性进行后门检测。观察后门样本在 `<EOS>` token 处的 cross-attention map 动态演化模式与良性样本不同。提出 DAA-I（基于 Frobenius 范数的独立测量）和 DAA-S（基于图状态方程的空间相关性建模，理论保证全局渐近稳定性）。

### 关键结果
- 平均 F1 Score: **79.27%**
- 平均 AUC: **86.27%**
- 测试场景: 6 种代表性后门攻击
- 显著超越现有检测方法
