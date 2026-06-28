# 论文精读报告：Diffusion Backdoor Attack 相关论文

> 15篇论文全文精读汇编 | 生成时间：2026-06-26

---

## 第一部分：Idea 1 — Checkpoint Merging Backdoor (9篇)

### 1.1 BadMerging: Backdoor Attacks Against Model Merging
- **会议**: ACM CCS 2024
- **作者**: Jinghuai Zhang, Jianfeng Chi, Zheng Li, Kunlin Cai, Yang Zhang, Yuan Tian
- **GitHub**: https://github.com/jzhang538/BadMerging

**核心思想**: 首个专门针对 Model Merging 的 backdoor attack。发现现有 backdoor 攻击在合并后全部失效（ASR<20%），因为 merging coefficients 缩放了 task vectors。提出 two-stage 攻击机制 + Feature-Interpolation (FI) loss，使攻击者仅需贡献一个含后门的 task-specific model，即可在任意 merging coefficient 下攻陷整个 merged model，支持 on-task 和 off-task 两种攻击模式。

**方法要点**:
1. **Stage 1 - Universal Trigger Generation**: 利用 task vectors 近乎正交的特性（cosine similarity 仅 0.042），在 pre-trained model 上优化 universal trigger
2. **Stage 2 - Backdoor Injection + FI Loss**: 插值 λ=0 和 λ=1 时的 feature embeddings，确保中间值也被分类为目标类
3. **Off-task 攻击**: Shadow Class Construction + Adversarial Data Augmentation (ADA)，仅需 5 张 reference images

**关键挑战与解决**:
| 挑战 | 解决方案 |
|------|---------|
| Merging coefficient 导致 backdoor 失效 | FI loss 覆盖整个插值路径 |
| 攻击者对合并过程一无所知 | 利用 task vectors 正交性 |
| Off-task 攻击的盲目性 | Shadow classes + ADA |

**核心指标**:

| 设置 | ASR (%) | BA (%) | CA (%) |
|------|---------|--------|--------|
| On-task (TA, CIFAR100) | **98.14** | 76.39 | 76.51 |
| On-task (AdaMerging, IN100) | **99.98** | 82.68 | 82.55 |
| Off-task ("Acura RL", TA) | **96.28** | 76.55 | 76.51 |
| 5个 trigger-target pairs | **98.8 avg** | — | — |
| 15个 backdoors | **96.5 avg** | — | — |

所有现有防御均失败：Neural Cleanse anomaly index 仅 1.2（远低于阈值 2）。

---

### 1.2 Merge Hijacking: Backdoor Attacks to Model Merging of LLMs
- **会议**: ACL 2025
- **作者**: Zenghui Yuan, Yangming Xu, Jiawen Shi, Pan Zhou, Lichao Sun
- **GitHub**: 未公开

**核心思想**: 首个针对 **LLM model merging** 的 backdoor attack。提出四步攻击流程：(1) 推导 backdoor vector → (2) magnitude-based ranking sparsification → (3) rescale 放大 → (4) mask finetuning。利用 backdoor vector 与 task vector 的正交性确保不干扰任务性能。

**方法要点**:
1. 用多数据集 shadow dataset 构建跨任务泛化的 backdoor vector
2. Magnitude-based sparsification 去除噪声，保留关键 backdoor feature
3. Rescaling factor λ=2.0 放大 backdoor vector 抵抗合并稀释
4. Mask finetuning 保护 backdoor vector 完整性

**核心指标 (Llama-3-8B, TA)**:

| 方法 | MRPC ASR | QNLI ASR | THSD ASR | MRPC BP |
|------|----------|----------|----------|---------|
| BadNets (合并后) | 0% | 0% | 0% | 68.2 |
| BadMerging (合并后) | 0% | 0% | 0% | 67.0 |
| **Merge Hijacking** | **100%** | **100%** | **100%** | **74.4** |
| LoBAM (λ=3.5) | 100% | 100% | 100% | 50.6 |

Fine-pruning 防御完全无效（ASR 仍保持 100%）。跨模型验证：Qwen-7B、Mistral-7B 均 ASR=100%。

---

### 1.3 LFPM: From Parameters to Feature Space (防御方)
- **会议**: ICML 2026
- **作者**: Zhenqian Zhu, Yamin Hu 等
- **GitHub**: 未公开

**核心思想**: 提出 **LFPM (Linear Feature Path Minimization)** 防御框架，从特征空间（而非参数空间）优化 anti-backdoor task vector。利用 Cross-Task Linearity (CTL) 框架，引入 gradient accumulation + loss path-integral 机制确保插值路径上的一致鲁棒性。

**方法要点**:
1. **Feature Subspace Partitioning**: 正交分离 adversarial/clean 特征子空间
2. **Prompt-Based Adversarial Feature Mining**: 用可学习 visual prompt 编码对抗扰动
3. **SAM-like 优化 + Loss Path-Integral**: 确保整个参数插值路径上的 backdoor 抑制

**核心指标 (BadMerging 攻击下)**:

| 防御方法 | Avg CA (%) | Avg ASR(T) (%) | Avg ASR(N) (%) |
|---------|-----------|---------------|---------------|
| 无防御 (TA) | 63.62 | 98.42 | 69.64 |
| IBVS | 42.85 | 64.18 | 58.53 |
| SAU | 47.00 | 63.00 | 63.93 |
| SAM | 40.55 | 10.03 | 31.21 |
| **LFPM** | **58.67** | **0.49** | **9.85** |

Adaptive attack 下 LFPM 仅从 0.49% 微升至 2.38%，其他方法大幅退化。

---

### 1.4 BackdoorDM: Comprehensive Benchmark
- **平台**: arXiv 2025
- **作者**: Weilin Lin, Nanjun Zhou 等
- **GitHub**: https://github.com/linweiii/BackdoorDM

**核心思想**: 首个 diffusion model 后门学习综合基准平台，整合 **9种攻击 + 4种防御 + 3种可视化工具**。提出统一数学框架和基于 GPT-4o 的评估方法，新增 PSR（非后门内容保留率）指标。

**关键发现**:
- 经典 BadNets 式攻击在 DM 实际场景中效果不佳（BiBadDiff ASR 仅 34.10%）
- ObjectRep 攻击无方法能在所有指标上同时最优
- 非冲突性后门目标（StyleAdd）比冲突性目标（ObjectRep）更容易攻击
- **SD v2.0 比 v1.5 更难被攻击**
- 输入级防御（TERD）有效（100% TPR/TNR），模型级防御效果有限

---

### 1.5 BadDiffusion: How to Backdoor Diffusion Models?
- **会议**: CVPR 2023
- **作者**: Sheng-Yen Chou, Pin-Yu Chen, Tsung-Yi Ho
- **GitHub**: https://github.com/IBM/BadDiffusion

**核心思想**: 首个针对 diffusion model 的 backdoor attack 框架。设计 backdoored forward process，修改前向扩散使 trigger noise 收敛到含 trigger 的高斯分布。通过 dual objective loss 同时优化 clean 和 backdoor 生成。

**方法要点**: 后门化前向过程 q(x'_t|x'_0) 中引入 correction term (1-√ᾱ_t)·r，使 x_T ~ N(r, I)。

**核心指标 (CIFAR-10, Fine-tuning)**:

| Poison Rate | Target | FID | MSE | SSIM |
|-------------|--------|-----|-----|------|
| 5% | Hat | 8.53 | 1.58e-1 | 3.12e-1 |
| 20% | Hat | 8.89 | **1.19e-5** | **1.00** |
| 50% | Hat | 10.25 | 1.48e-5 | 1.00 |

CelebA-HQ (256x256): 50% poison rate 下 FID=7.51（优于 clean 的 8.43），MSE=1.67e-5。

---

### 1.6 TrojDiff: Trojan Attacks on Diffusion Models with Diverse Targets
- **会议**: CVPR 2023
- **作者**: Weixin Chen, Dawn Song, Bo Li
- **GitHub**: https://github.com/chenweixin107/TrojDiff

**核心思想**: 首次提出三种攻击类型——**In-D2D**（域内目标类）、**Out-D2D**（域外分布）、**D2I**（特定图像）。设计 Trojan diffusion process，通过 biased Gaussian distribution N(μ, γ²·I) 实现攻击。

**核心指标 (DDPM, CIFAR-10, blend trigger)**:

| 攻击类型 | FID | A-Prec (%) | ASR (%) | MSE |
|---------|-----|-----------|---------|-----|
| Clean | 4.60 | — | — | — |
| In-D2D | 4.74 | 79.00 | 90.10 | — |
| Out-D2D | 4.78 | 75.50 | **99.30** | — |
| D2I | 4.59 | — | — | **1.00e-5** |

关键发现：每个像素需要一定 random space，patch trigger 中 γ=0 导致 Out-D2D A-Prec 下降 29-36 个百分点。

---

### 1.7 EvilEdit: Backdooring T2I Diffusion Models in One Second
- **会议**: ACM MM 2024
- **作者**: Hao Wang, Shangwei Guo, Jialing He 等
- **GitHub**: https://github.com/haowang-cqu/EvilEdit

**核心思想**: **Training-free, data-free** 的后门攻击。直接编辑 cross-attention layers 的 projection matrices (W_k, W_v)，通过 closed-form solution 使 trigger 的 projection 与 target 对齐。仅需 **1秒**，修改 **2.2%** 参数。

**方法**: W* = (Wc^ta c^{trT} + λW)(c^tr c^{trT} + λI)^{-1}

**核心指标 (SD v1.5)**:

| 方法 | ASR (%) | CLIP_p | FID | LPIPS | 时间(s) | 数据量 |
|------|---------|--------|-----|-------|---------|--------|
| Rickrolling | 98.4 | 29.85 | 17.11 | 0.20 | 64 | 635,561 |
| BadT2I | 47.5 | 21.01 | 16.52 | 0.22 | 43,962 | 500 |
| **EvilEdit** | **100** | **31.11** | **16.29** | **0.16** | **1** | **0** |

5个同时后门 ASR 仍达 99.5%。Fine-tuning 15K步后 ASR 仍达 80-90%。

---

### 1.8 VillanDiffusion: A Unified Backdoor Attack Framework
- **会议**: NeurIPS 2023
- **作者**: Sheng-Yen Chou, Pin-Yu Chen, Tsung-Yi Ho
- **GitHub**: https://github.com/IBM/villandiffusion

**核心思想**: 统一后门攻击框架，覆盖 **DDPM/NCSN/LDM/Stable Diffusion** + **9种 sampler** + image/caption 两种 trigger。从 SDE/ODE 理论角度解释了 BadDiffusion 在 ODE sampler 上失败的原因（stochasticity parameter ζ 不匹配）。

**关键发现**:
- Caption similarity 越低的 trigger 攻击效果越好（"mignneko" MSE=3.82e-3, MSE Threshold=99.8%）
- 推理时 clipping 防御对 ODE sampler 无效（FID 飙升至 100+）
- Score-based model (NCSN) 也可被后门攻击（首次验证）

---

### 1.9 RickRolling the Artist: Injecting Backdoors into Text Encoders
- **会议**: ICCV 2023
- **作者**: Lukas Struppek, Dominik Hintersdorf, Kristian Kersting
- **GitHub**: https://github.com/LukasStruppek/Rickrolling-the-Artist

**核心思想**: 首个针对 T2I 模型 **text encoder** 的后门攻击。使用 **homoglyph**（视觉相同但 Unicode 不同的字符）作为隐蔽 trigger。两种模式：TPA（完全替换语义）和 TAA（仅修改属性如风格）。注入单个后门仅需 **~100秒**。

**方法**: Teacher-Student fine-tuning，总损失 L = L_Utility + β·L_Backdoor

**核心指标**:
- Clean model: FID=17.05, Acc@1=69.82%, Acc@5=90.98%
- 32个后门注入后：accuracy 仅轻微下降，FID 基本不变
- 可用于安全防护：移除 encoder 对裸露/暴力概念的理解

---

## 第二部分：Idea 2 — SAE Backdoor Detection (6篇)

### 2.1 Activation Differences Reveal Backdoors (Diff-SAE)
- **平台**: arXiv 2026
- **作者**: Sachin Kumar
- **GitHub**: https://github.com/techsachinkr/diff-sae-backdoor-detection

**核心思想**: 首次系统比较 **Crosscoders vs Differential SAEs (Diff-SAE)** 用于 LLM backdoor 检测。核心发现：backdoor 表现为 **方向性激活偏移 (directional activation shifts)**，而非稀疏特征激活。因此 Diff-SAE（直接对激活差异建模）本质上优于 Crosscoders。

**提出 Backdoor Isolation Score (BIS)** = F1 × (1 - FPR)

**核心指标 (Layer 18)**:

| 方法 | LoRA BIS | Full-Rank BIS | Precision | FPR |
|------|----------|---------------|-----------|-----|
| Crosscoder | 0.010 | 0.000 | 0.024 | 0.003 |
| **Diff-SAE 32×** | **0.400** | **0.400** | **1.000** | **0.000** |
| Diff-SAE 4× | 0.400 | 0.400 | 1.000 | 0.000 |

Diff-SAE 相对 Crosscoder 提升 **~40×**。4× expansion 即可匹配 32× 性能（参数效率提升 8×）。跨层一致性：BIS 在 L14-L26 均为 0.39-0.40。

---

### 2.2 SAeUron: Interpretable Concept Unlearning in Diffusion Models with SAEs
- **会议**: ICML 2025
- **作者**: Bartosz Cywinski, Kamil Deja
- **GitHub**: https://github.com/cywinski/SAeUron

**核心思想**: 利用 SAE 对 diffusion model U-Net cross-attention block 激活进行无监督分解，发现语义可解释的 features。通过 score-based feature selection 定位目标概念，inference 时用负系数 ablate 这些 features。**不修改原始模型权重**。

**方法要点**:
- BatchTopK SAE (k=32, expansion=16, n=20,480 latents)
- 跨所有 denoising timesteps 收集激活数据
- Score function 考虑目标概念相对激活 & 非目标概念惩罚

**核心指标 (UnlearnCanvas)**:

| 方法 | Style UA | Style IRA | Style CRA | Obj UA | Obj IRA | Obj CRA | Avg (%) | Memory |
|------|----------|-----------|-----------|--------|---------|---------|---------|--------|
| SalUn | 86.26 | 90.39 | 95.08 | 86.91 | **96.35** | **99.59** | 92.43 | 30.8GB |
| ESD | **98.58** | 80.97 | 93.96 | 92.15 | 55.78 | 44.23 | 77.61 | 17.8GB |
| **SAeUron** | 95.80 | **99.10** | **99.40** | 78.82 | 95.47 | 95.58 | **94.03** | **2.8GB** |

I2P nudity 检测仅 18 次（SD v1.4 baseline 743 次）。49/50 styles 同时 unlearning: UA=99.29%。

---

### 2.3 SAEmnesia: Erasing Concepts with Supervised SAEs
- **平台**: arXiv 2026
- **作者**: Enrico Cassano, Riccardo Renzulli 等
- **GitHub**: https://github.com/EIDOSLAB/SAEmnesia

**核心思想**: 在 SAeUron 基础上引入 **有监督信号**，通过 Concept Assignment (CA) loss + Decorrelation (DC) loss 强制建立 **concept-latent 一对一映射 (feature centralization)**，解决无监督 SAE 的 feature splitting 问题。超参数搜索成本减少 **96.67%**。

**核心指标 (UnlearnCanvas Object Unlearning)**:

| 方法 | UA (%) | IRA (%) | CRA (%) | Avg (%) |
|------|--------|---------|---------|---------|
| SAeUron | 87.16 | 85.57 | 74.14 | 82.29 |
| SalUn | 86.91 | 96.35 | 99.59 | 94.28 |
| **SAEmnesia** | **94.65** | **91.39** | **88.48** | **91.51** |

对抗鲁棒性：White-box 攻击下 SAEmnesia 97.60→57.50 (下降 40.1pp) vs SAeUron 83.70→34.20 (下降 49.5pp)。

综合 Object+Style 平均：SAEmnesia **94.85%** > SalUn 92.43% > SAeUron 90.10%。

Nudity unlearning: SAEmnesia-top2 仅需 **2个 latent**（vs SAeUron 的 205个），NudeNet 检测仅 **9次**。

---

### 2.4 Residualized Temporal SAE for Interpreting Diffusion Models
- **平台**: arXiv 2026
- **作者**: Calvin Yeung, Prathyush Poduval 等 (UC Irvine)
- **GitHub**: 未公开

**核心思想**: 提出 **Residualized Temporal SAE**，通过 ridge regression 移除相邻 timestep 间的线性可预测成分，SAE 仅在残差上训练。将子采样的完整 denoising trajectory 拼接为单向量输入，每个 latent 对应一条完整的 feature trajectory。

**方法要点**:
1. Ridge regression 残差化（explained variance 0.37-0.80）
2. 拼接残差化 trajectory (5×1280=6400维)
3. BatchTopK SAE with dual normalization

**核心指标 (RIEBench Feature Transfer Steering)**:

| 模型 | CLIP-T | Δ CLIP-T | LPIPS-S | Edit Efficiency |
|------|--------|----------|---------|----------------|
| Source Baseline | 29.423 | 0.000 | 0.000 | — |
| **Resid+Concat** | 29.557 | 0.134 | 0.194 | **0.691** |
| Resid+NoConcat | 29.567 | 0.144 | 0.321 | 0.449 |
| NoResid+Concat | 29.507 | 0.084 | 0.188 | 0.447 |
| Matryoshka | 29.463 | 0.039 | 0.189 | 0.206 |

Early features 时序持久、空间扩散；Late features timestep-specific、空间集中。

---

### 2.5 Shared Latent Structures Enable Unified Backdoor Detection (SAE Universal)
- **平台**: arXiv 2026
- **作者**: Omar Mahmoud, Aly M. Kassem 等 (Deakin University, Mila)
- **GitHub**: 计划公开（未提供链接）

**核心思想**: 核心发现——不同类型的 LLM backdoor attack **共享一个潜在的 latent mechanism**。利用 SAE 分解 residual-stream activations，发现一小组 SAE features 在 6种攻击行为、3个模型家族（Qwen3/Gemma3/Llama3.1, 4B-32B）中一致性被激活。提出 CAFT (Concept Ablation Fine-Tuning) 防御。

**核心指标**:

Zero-shot AUROC 检测（跨模型聚合）:

| 模型 | Best SAE | Defection Clf. | SVD | MD |
|------|---------|---------------|-----|-----|
| Qwen3-8B | **0.822** | 0.636 | 0.578 | 0.651 |
| Gemma-3-12B | **0.868** | 0.604 | 0.251 | 0.629 |
| Llama-3.1-8B | **0.813** | 0.396 | 0.368 | 0.493 |

CAFT 缓解效果 (Qwen3-8B):

| Behavior | SFT ASR (%) | CAFT ASR (%) |
|----------|------------|-------------|
| Jailbreak | 95.00 | **3.03** |
| Watching | 100.00 | **0.00** |
| Country | 89.00 | **2.02** |
| Sentiment | 100.00 | **8.57** |

MMLU 通用能力基本不受影响（CAFT avg 69.37% vs SFT 67.38%）。

---

### 2.6 TIDE: Temporal-Aware SAEs for Interpretable Diffusion Transformers
- **平台**: arXiv 2025
- **作者**: Victor Huang, Le Zhuo 等 (CUHK, 上海AI Lab)
- **GitHub**: 未公开

**核心思想**: 首个系统性地将 SAE 应用于 **Diffusion Transformers (DiTs)** 的可解释性框架。引入 **Temporal-Aware 调制机制**（从 DiT adaLN 初始化的 timestep-dependent scale/shift），适配 diffusion model 在不同去噪时间步上激活分布剧烈变化的特点。

**发现三层级语义**: 3D-Level（深度/前景背景）→ Class-Level（物体类别）→ Semantic-Level（精细语义如鸟喙）

**核心指标 (PixArt-XL)**:

| 方法 | FID | Δ FID | Val S_cos |
|------|-----|-------|-----------|
| Baseline (无 SAE) | 7.30 | — | — |
| SAE (5% sparsity) | 7.93 | +0.63 | 0.935 |
| **TIDE (5%, 16d)** | **7.45** | **+0.15** | **0.964** |

安全编辑 (I2P): TIDE ASR=0.64%（接近 SOTA CS 的 0.42%）。跨模型泛化到 SDXL (Δ FID +0.14) 和 FLUX-dev (Δ FID +0.04)。

---

## 第三部分：开源代码汇总

| 论文 | GitHub |
|------|--------|
| BadMerging | https://github.com/jzhang538/BadMerging |
| Merge Hijacking | 未公开 |
| LFPM | 未公开 |
| BackdoorDM | https://github.com/linweiii/BackdoorDM |
| BadDiffusion | https://github.com/IBM/BadDiffusion |
| TrojDiff | https://github.com/chenweixin107/TrojDiff |
| EvilEdit | https://github.com/haowang-cqu/EvilEdit |
| VillanDiffusion | https://github.com/IBM/villandiffusion |
| RickRolling | https://github.com/LukasStruppek/Rickrolling-the-Artist |
| Diff-SAE Backdoor | https://github.com/techsachinkr/diff-sae-backdoor-detection |
| SAeUron | https://github.com/cywinski/SAeUron |
| SAEmnesia | https://github.com/EIDOSLAB/SAEmnesia |
| Residualized Temporal SAE | 未公开 |
| SAE Universal Backdoor | 计划公开 |
| TIDE | 未公开 |

---

## 第四部分：对我们研究方向的启示

### Idea 1 (Checkpoint Merging Backdoor) 关键空白
1. **攻击侧已成熟**: BadMerging (CCS'24) 和 Merge Hijacking (ACL'25) 分别在 CV 和 NLP 领域验证了高效攻击
2. **防御侧刚起步**: LFPM (ICML'26) 是首个专门针对 merging backdoor 的防御，但仅覆盖分类任务
3. **Diffusion model merging 完全空白**: 无人研究 LERP/SLERP/DARE/TIES 等扩散模型合并算法中的后门持久性
4. EvilEdit 的 1秒注入 + 2.2%参数修改 + 100% ASR 证明了攻击的低成本高回报

### Idea 2 (SAE Backdoor Detection) 关键空白
1. **LLM 侧有进展**: Diff-SAE (BIS=0.40, Precision=1.0) 和 SAE Universal (AUROC=0.868) 展示了 SAE 检测 backdoor 的可行性
2. **Diffusion model 侧仅有 unlearning**: SAeUron/SAEmnesia 用 SAE 做 concept unlearning（UA 94-95%），但未用于 backdoor detection
3. **TIDE/Residualized Temporal SAE 提供了 diffusion SAE 基础设施**，但未连接到 backdoor detection
4. **核心 gap**: 将 Diff-SAE 的 "backdoor = directional activation shift" 洞察迁移到 diffusion model 领域
