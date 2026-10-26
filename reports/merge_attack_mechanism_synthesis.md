# Merge-Attack 机制综述与 T2I 迁移 (Idea 1 文献锁定)

> 来源：BadMerging / LoBAM / Merge Hijacking / RogueMerge / MergeBackdoor 五篇攻击 + LFPM 防御 + Diffusion Soup / DiffGraph 两篇真实 T2I 合并协议的深读提炼。
> 用途：为 `T2I-MergeRobust` 方法设计与实验协议提供事实底座。每条结论标注一手出处。

## 0. 引用与 ID 校正

| 方法 | 一手出处 | 校正 |
|---|---|---|
| BadMerging | arXiv **2408.07362** (ACM CCS 2024, Zhang et al.) | 本地 `papers/README.md` 把 2408.07362 误标为 Rickrolling；Rickrolling 实为 **2211.02408** (ICCV 2023)。已于 2026-07-28 核对 PDF 首页并修正索引。 |
| LoBAM | arXiv **2411.16746** (Yin et al.) | LoRA 训练、上传完整 checkpoint |
| Merge Hijacking | arXiv **2505.23561** (ACL 2025, 2025.acl-long.1571) | — |
| RogueMerge | arXiv **2606.03344** (2026 preprint, BadMerging 同一作者) | 无正式 venue |
| MergeBackdoor | USENIX Security 2025, Wang Lijin *"From Purity to Peril"* pp.6339-6358 | 无 arXiv；code: github.com/wljLlla/MergeBackdoor |
| LFPM (防御) | arXiv **2606.12498** (2026, ICML 格式) | 方法名 Linear Feature Path Minimization |

## 1. 五种攻击共享的同一原语

**把后门方向孤立为"两个攻击者模型之差"，用 λ 过度放大以预补偿合并稀释，再锚定使上传 checkpoint 看起来正常。** 差异只在"如何锚定"与"是否显式建模未知合并"。

| 方法 | 后门方向 | 抗稀释手段 | 锚定/隐蔽手段 | 是否显式建模未知合并 |
|---|---|---|---|---|
| LoBAM | `θ_mal−θ_ben` (LoRA 结构自然选择性) | `θ_up=λ(θ_mal−θ_ben)+θ_ben`, λ≈4–6 | ℓ2 距离匹配良性群 | 否 (仅靠 λ 预补偿) |
| Merge Hijacking | `τ=θ*_sha−θ_sha` (多任务 shadow) | 幅度秩 Bernoulli 稀疏 + 1/p rescale (预抄 DARE) | mask 微调恢复效用 | 否 (靠 λ+稀疏) |
| BadMerging | `Δθ_adv` | FI loss: `F=p·V_adv+(1−p)·V_pre`, p~U[0.1,1] | shadow classes + ADA | **是** (特征空间插值模拟 λ) |
| RogueMerge | 单个 `Δ_atk` | MUAO 最坏情况 `ε*=δ·g/‖g‖` | 效用在最坏干扰下同优化 | **是** (min-max over α+ε, 权重空间) |
| MergeBackdoor | n 个各自良性的上传 | shadow-merge 回路 (梯度过合并算子) | 每个上传单独良性→**合并前零 ASR** | 部分 (固定平均 shadow merge) |

## 2. 各方法可迁移到 T2I 的核心 (按价值排序)

### 2.1 RogueMerge MUAO (最高价值，loss-agnostic 权重空间)
- 把未知良性 expert 边缘化为一个加性噪声 ε；用 FGSM 式单次反传求最坏方向 `ε*_eff=δ·g/‖g‖₂`，`g=∇_θ L_bd`。**一次额外反传，无需真实良性 expert。**
- 外层对 α 采样 (每步一个)；关键第三项：**在同一最坏干扰下同时优化效用** → 合并后效用不降反升 (他们 Ū 128% vs clean 121%)。
- 迁移：`g=∇_θ E_{t,x0,ε}‖ε−ε_{θ+cΔ}(x_t,t,τ(trig))‖²`，Eq.8 原样可用。δ 对"精确触发"类应取高值 (他们 backdoor 用 δ=0.2)。
- 风险：SD 微调方向高度相关 (非 LLM 的 cos≈0)，需先实测 `cos(Δ_atk, 良性 expert task vector)`；若显著为正，ε_eff 有界假设变弱。

### 2.2 MergeBackdoor shadow-merge 回路 (给"合并前零 ASR"隐蔽性)
- 每 **batch** 重取一次 `θ_merged=Σa_iθ_i`，把后门损失过合并算子回传，Jacobian `∂θ_merged/∂θ_i=a_i·I`；对 TIES/DARE 的非可微 mask 用直通估计 (mask 当常数、每步重算)。
- 双梯度：anti-backdoor (触发 prompt→诚实图，在**单模型**上) + backdoor (触发→目标，在 **merged** 上)，`g_i=g_a+λ·a_i·g_b`。
- **batch-by-batch 而非 epoch** 是关键，1–2 轮收敛。
- 代价：需 **≥2 个攻击者 checkpoint 被同时选中合并** (比 RogueMerge 单模型强的假设)。
- 关键机制发现：后门抑制不在"识别"而在"传播"——上游模型仍提取后门特征，只是末层不传播；合并只在 attn 8–16 层 (ViT) 生效。→ T2I 应验证是否定位在 mid/up cross-attn。

### 2.3 Merge Hijacking Step2+Step4 (权重空间存活)
- Step2 幅度秩 Bernoulli 稀疏 (keep-prob 带 [0.5,0.9]，随 |τ| 单调) + 1/p rescale = 预抄 DARE，使后续 DARE drop 命中已零坐标。**必须 per-tensor/block 排序，不能全 UNet 全局排序。**
- Step4 在中毒 surrogate 任务上 mask 微调，恢复效用 + 再强化后门 = **LoBAM 效用崩溃的解药**。
- EvilEdit 的闭式 K/V 编辑本就是极小支撑低秩 τ = 理想输入。λ≈2 (有稀疏) 优于 λ≈4–6 (无稀疏)。

### 2.4 BadMerging FI loss (RogueMerge 的简化版)
- 两端点原理：让后门在 λ=0 (θ_pre) 与 λ=1 都触发 → 整条 [0,1] 路径被钉住。
- 迁移三选项 (保真度递增)：(a) 混 cross-attn K/V 投影；(b) 混预测噪声 `ε_p=p·ε_adv+(1−p)·ε_pre`；(c) 真权重插值 `θ_p=θ_pre+p·Δθ_adv` 去噪。**推荐 (b)/(c)，因 CLIP 的"特征插值近线性"在 50 步 UNet 上未验证。**

## 3. 必须同时应对的两条正交防线

**LFPM 防御在特征空间工作，不看任何权重向量。** 因此 Merge Hijacking 的权重空间规避 (稀疏/锚定) 对 LFPM **零收益**。攻击需要**两个正交机制**：
1. 权重空间存活 (稀疏/放大/MUAO) → 扛 TIES/DARE/DELLA。
2. 特征空间隐蔽 → 扛 LFPM。**EvilEdit 闭式 K/V 编辑不产生紧致特征簇** → 结构性规避 LFPM 的 Stage-I 聚类项 (Eq.16 第三项无处着力)，是 SD 场景最强的天然规避。

LFPM 可利用弱点 (供自建 SD 版对抗)：
- 只在 CLIP 分类 (线性头) 上定义，SD1.5 无法直接运行 → 需自建 SD 类比并击败。
- 路径积分只覆盖 α∈[0.9,1.0]，却部署在 α=0.5/0.8 → **对小 α 强的后门打在最弱处**。报告全 [0,1] 的 Path-ASR。
- 对抗时 LFPM 把 UNet 插值 50–80% 到 anti-backdoor UNet = 巨大分布漂移 → **迫使防御付出大 FID/IR 代价本身就是赢**。LFPM 及其 baseline 从未测过生成效用。
- P_s 只 rank-16/512；后门散布在 >16 个正交低幅方向可结构性欠覆盖。

## 4. 真实 T2I 合并协议 → 锁定评测网格

- **主算子 (P0)：全 UNet 权重的凸组合平均** — 均匀 `1/n` (Diffusion Soup, ECCV24) + 学习 softmax 非均匀 (DiffGraph, CVPR26)；以及 **CKPT 平均 ⊕ LoRA delta 平均** (DiffGraph，唯一贴合 Civitai/HF 生态)。
- **恶意系数现实值 ≈1/n = 0.077 (n=13) → 0.5 (n=2)**，必须存活到 **α≈0.08**，比 BadMerging/LFPM 的 [0.2,1.0] 苛刻得多。
- **expert 数网格 n∈{2,5,9,10,13}**。
- **P1：Task Arithmetic λ∈[0.2,1.0]** (与合并安全文献可比)；**P2：TIES/DARE/DELLA** (需 Merge-Hijacking 预稀疏才存活)；**P3：SLERP/block-weighted** = 社区工具实践，非同行评审 T2I 协议，作鲁棒性附加项，且 **SLERP 非线性会部分抵消 λ 放大——最大未测风险**。
- **Greedy souping 是隐式效用筛**：降 IR/TIFA 的恶意 expert 会被踢出 soup → 攻击必须 **IR/TIFA 中性或正向**，否则连合并都进不去。硬约束。
- **良性 expert 类型**：全 FT 域专家 (Diffusion Soup 配方：CLIP 检索 10K→美学分>6→~1K 图/类)、美学专家、风格专家、Civitai/HF 社区 CKPT+LoRA。DreamBooth 两篇都没用，若用需标为自研扩展。
- **效用指标**：IR + HPS v2.1 + Aesthetic + PickScore + CLIP，on DABench (50,482 Civitai prompts) + DiffusionDB；**两篇 T2I 合并论文都不报 FID** → FID-10K 仅作内部门禁。

## 5. 方法学空白 (novelty 立足点)

**把 RogueMerge 的 min-max over (算子, α, ε_eff) 放进 MergeBackdoor 的 shadow-merge 回路，作用于 SD1.5 cross-attention，LERP/TIES/DARE 直通可微、SLERP 留作未见算子；再叠加一个特征空间隐蔽机制以击败 LFPM (LLM 攻击从未面对过)。** 五篇里无一同时做权重空间存活 + 特征空间隐蔽 + 显式未知合并鲁棒 + 生成域。两篇的自曝失败点 (DELLA 幅度剪枝、MergeBackdoor 依赖共选) 正是压力测试边界。

## 6. T2I 实现事实 (M3/M1 就绪，2026-07-28 服务器核实)

- **Δ 注入位置**：UNet cross-attention `attn2.to_k.weight` / `attn2.to_v.weight`（EvilEdit `attack/t2i_gen/eviledit/eviledit.py` 的 `projection_matrices = [l.to_v]+[l.to_k] for l in attn2`）。M3 只训练这些张量，其余冻结在 base。
- **统一后门语义**（`bd_config_objectRep.yaml`）：所有对象替换攻击 trigger→`cat`、clean_object=`dog`。触发词：eviledit=`beautiful dog`、badt2i_object=`\u200b `、rickrolling_TPA=`ȏ`(o→ȏ 字符级)、paas=`[V] dog`。
- **ASR/ACC 度量**：`evaluation/ObjectRep_Backdoor/ACCASR.py` 用 ViT-base-224 ImageNet 分类器；ASR=触发图判为 cat(281–287)，ACC=clean 图判为 dog(151–268)。评测入口 `main_eval.py --metric ACCASR --backdoor_method <m> --bd_config <objectRep> --backdoored_model_path <merged.pt>`。
- **M3 损失设计**（BadT2I 式教师蒸馏，免目标图）：`L_bd=‖ε_θmerge(z_t,t,c_trig) − sg[ε_θbase(z_t,t,c_tgt)]‖²`（c_tgt=dog→cat 的目标 prompt）；`L_util=‖ε_θmerge(z_t,t,c_clean) − sg[ε_θbase(z_t,t,c_clean)]‖²`。
- **训练数据**：`attack/t2i_gen/laion_ppl_len_40k`（BadT2I 用的 LAION-40k caption，+ `laion_fallback`）。
- **良性 expert**（HF 镜像）：`/opt/data/private/merge_experts/{Realistic_Vision_V5.1_noVAE, dreamshaper-8}/unet`。
- **已交付脚本**：`server/merge_tracer.py`（7 算子）、`server/run_merge_degradation.py`（M1 网格驱动，复用 ACCASR）。

