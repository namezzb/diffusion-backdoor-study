# Paper 1 (`CORE-LoRA`) 完整审稿评估、现状诊断与后续研究方向分析

- **整理日期**：2026-11-16
- **所属任务**：[`TASK.md`](TASK.md)（`LORA-COMP-BACKDOOR-20261113-01`）
- **关联材料**：论文初稿 [`paper/main.tex`](paper/main.tex)、大纲 [`paper/OUTLINE_AND_SETTINGS.md`](paper/OUTLINE_AND_SETTINGS.md)、方案演进 [`IDEA_V2.md`](IDEA_V2.md)、实测记录 [`IMPLEMENTATION_REPORT.md`](IMPLEMENTATION_REPORT.md)、最新多 Seed 汇总 [`MULTISEED_REPORT.md`](../../../autoresearch/runs/lora-comp-mvp-20261116-ours-v2-refined-multiseed/MULTISEED_REPORT.md)、核心源码 [`scripts/lora_composition_mvp/`](../../../scripts/lora_composition_mvp/)。

---

## 1. 当前项目与实验真实状态全景

### 1.1 任务背景与当前所处阶段

本项目（Paper 1，`CORE-LoRA`）旨在解决文生图（T2I）扩散模型第三方 LoRA 组合生态中的后门持久性与画风保真矛盾：当下游用户将主体定制 LoRA（标称 `"a car"`，含隐藏触发词 `"a cool car" -> "a cat"`）与未知的第三方高权重风格 LoRA（$P_{\text{test}}$，`"in fantasy oil painting style"`，$s_p=0.8$）通过主流融合算子组合时，在严格匹配总 Frobenius 范数预算（$\|\Delta W\|_F \le 18.0$）且只发布**单份静态 `rank=16` 纯 U-Net LoRA**（$\|\Delta W_{\text{TE}}\|_F = 0$）的约束下，同时实现组合态高攻击成功率（ASR）、正常主体保留、第三方画风无损以及邻域混淆词低误触发。

目前已完成方法核心实现、4 项组件消融、3 个独立训练种子的实机评测以及英文初稿 [`paper/main.tex`](paper/main.tex) 撰写。但交叉核对论文源码、训练代码与运行账本后发现，**初稿所使用的实验快照与最新修复后的代码/多 Seed 真实结果之间存在关键版本差异**，阅读与后续推进时必须严格区分以下三个历史运行版本：

| 运行版本 (`autoresearch/runs/...`) | 配置与状态特征 | 单载 $S_0$ `ASR_strict` | 组合态 ($S_1\text{--}S_3$) `ASR_strict` | 关键现象与客观事实 |
|---|---|---:|---:|---|
| [`lora-comp-mvp-20261114-baseline-fix`](../../../autoresearch/runs/lora-comp-mvp-20261114-baseline-fix/REPORT.md) | 公平基线参照（432 图）：修复 `MasqLoRA` 176 层 TE 键名加载与 `PoisonLoRA` TE 梯度截断，统一施加 $\|\Delta W\|_F \le 18.0$ 预算 | `MasqLoRA`: `75.0%`<br>`PoisonLoRA`: `43.8%` | `MasqLoRA`: **`0.0%`**<br>`PoisonLoRA`: **`0.0%`**<br>（四场景全为 `0.0%`） | 证实公平范数下两条基线在 $S_1$（`te=0, s=0.5`）、$S_2^{\text{klora}}$、$S_2^{\text{ties}}$、$S_3^{\text{ziplora}}$ 中 100% 退回红车；无范数约束的 `PoisonLoRA`（范数 `102.53`）在 $S_1, S_2^{\text{klora}}, S_2^{\text{ties}}$ 仍为 `0.0%`，且导致正常车保留率跌至 `62.5%–68.8%`、非触发漏猫升至 `13.8%`。 |
| [`lora-comp-mvp-20261115-ours-v2-clean`](../../../autoresearch/runs/lora-comp-mvp-20261115-ours-v2-clean/REPORT.md)<br>及 4 个 `20261115-ablation-*` | **当前 `paper/main.tex` 全文及表 1–4 所填数字来源**（单训练种子 `seed=42`，`qo_max_ratio=0.55`） | `87.5%` | **均值 `83.3%`**<br>($S_1$: `81.3%`, $S_2^{\text{klora}}$: `100.0%`, $S_2^{\text{ties}}$: `75.0%`, $S_3^{\text{ziplora}}$: `81.3%`) | 词库已做训练/测试零重合脱敏，消融趋势清晰；**但训练代码含 `0.5*z_car + 0.5*z_cat` 半透明潜变量混合瑕疵**，引发两个目视伪影：① $S_0$ 中邻域提示 `"a brown dog"` 生成棕色复古汽车；② $S_1/S_2^{\text{klora}}/S_3^{\text{ziplora}}$ 带风格触发图出现“上下双猫脸叠加”。此外 `paper/scripts/generate_figures_3_and_4.py` 在生成 `Fig. 3` 时第 5 行（`S2_klora`）混用了 `20261114-ours-v2` 的图片。 |
| [`lora-comp-mvp-20261116-ours-v2-refined`](../../../autoresearch/runs/lora-comp-mvp-20261116-ours-v2-refined/REPORT.md)<br>+ [`-s43`](../../../autoresearch/runs/lora-comp-mvp-20261116-ours-v2-refined-s43/REPORT.md) + [`-s44`](../../../autoresearch/runs/lora-comp-mvp-20261116-ours-v2-refined-s44/REPORT.md)<br>汇总：[`MULTISEED_REPORT.md`](../../../autoresearch/runs/lora-comp-mvp-20261116-ours-v2-refined-multiseed/MULTISEED_REPORT.md) | **当前仓库最新代码默认配置**（3 个独立训练种子 `seed=42, 43, 44`，解耦潜变量，`qo_max_ratio=0.45`，补齐离线 VGG-LPIPS） | `93.8% ± 6.3%` | **均值 `47.9% ± 20.5%`**<br>($S_1$: `29.2% ± 15.7%`, $S_2^{\text{klora}}$: `79.2% ± 26.0%`, $S_2^{\text{ties}}$: `45.8% ± 43.9%`, $S_3^{\text{ziplora}}$: `52.1% ± 13.0%`) | 彻底消除了棕狗变车与上下双猫脸伪影，3/3 个训练 seed 均通过预设 Gate 1–3（`CleanCar = 95.8% ± 4.2%`，`StyleCLIP = 0.2166 ± 0.0002`，`CatLeak = 1.67% ± 1.91%`，`Clean_LPIPS = 0.4624 ± 0.0103`）；**但代价是组合态 ASR 大幅回落且跨 seed 方差剧增**——$S_1$ 长句触发退回汽车，`seed=44` 在 $S_2^{\text{ties}}$ 上跌至 `0.0%`（三个种子分别为 `87.5% / 50.0% / 0.0%`）。 |

### 1.2 不可破坏的公平性与威胁模型边界

在评估现有结果和探索任何后续改进时，以下 4 条科学边界是全文立论基石，不可放宽：
1. **单静态标准适配器**：攻击者仅发布一份标准 `rank=16` `.safetensors` 文件，不能修改下游推理管线、融合算子超参、采样器或 CFG 尺度。
2. **范数球公平与零 TE 修改**：所有候选后门 LoRA 总 Frobenius 范数严格受限于 $\|\Delta W_c\|_F \le B = 18.0$，且 `CORE-LoRA` 保持 $\|\Delta W_{\text{TE}}\|_F \equiv 0$。
3. **严格训练–测试隔离**：训练提示句式/修饰词与测试提示集零交集（`assert_prompt_bank_isolation`），训练代理画风 $P_{\text{train}}$ 与测试第三方画风 $P_{\text{test}}$ 词元及权重零交集（`assert_partner_isolation`）。
4. **证据同源一致性**：论文正文、所有定量表与定性对比拼图必须全部出自同一冻结代码版本与同一组模型权重，不得跨版本混取指标或图像。

---

## 2. CCF-A 审稿人总体评价、核心优势与维度打分

### 2.1 总体审稿结论：Idea 合理且具备顶会竞争力，但当前证据状态尚不能直接投稿

- **核心 Idea 评价（概念潜力 `7.5 / 10`，值得正式写成顶会论文，无需换题或推翻框架）**：
  现有 T2I LoRA 后门研究默认单适配器全权重加载或简单线性混合，忽视了开源社区“剥离 TE + 主体降权 + 异质非线性融合算子（`K-LoRA` / `TIES` / `ZipLoRA`）”的真实部署范式。本文不仅实证抓住了公平范数下基线从 $43.8\%\text{--}75.0\%$ 跌至 **$0.0\%$ 的“组合坍缩（Compositional Collapse）”**，还给出了清晰的数学机理（跨模态单点脆弱、K-LoRA 全局 $\gamma$ 归一化尺度不变性、半权源概念残留锁定），并用极简的两项核心机制（24 层语义瓶颈内的非对称 $K/V$ 能量分配 + 算子感知的反事实 CFG 引导场蒸馏）予以解决。故事主线干净、部件必要性在消融中得到了强有力验证。
- **当前初稿与实验成熟度评价（当前稿件 `4 / 10, Weak Reject`）**：
  当前不能直接投稿的原因不在核心思路，而在于**证据一致性缺口与实验验证广度不足**：① 初稿报告的 `83.3%` 来自含视觉伪影的单种子旧版且 `Fig. 3` 存在跨版本混拼，而最新无伪影 3-Seed 版本在 $S_1$（`29.2%`）和 $S_2^{\text{ties}}$（`45.8% ± 43.9%`，单 seed 跌零）上尚不够稳健（`C001`）；② 正文部分公式、超参与代码实现及全步路由诊断未对齐（`C002`）；③ 实验仅覆盖单一概念对、单一合成 SVD 伙伴、单一 SD 1.5 底座，且测试邻域集漏测了含 `"cool"` 的未见短语（`C003`）；④ 基线训练步数/模板不对称，且良性保真分支以裸底模为教师导致定制主体相似度（`ClipImgDist` / `LPIPS`）全表垫底（`C004`）；⑤ 缺少对未见算子与现成后门检测器的实证响应评估（`C005`）以及引文缺作者、架构图错连线等细节问题（`C006`–`C008`）。

### 2.2 主要科学优势（Strengths）

1. **生态痛点真实，基线坍缩现象极具冲击力（[`paper/main.tex`](paper/main.tex#L70-L85)、[`tab_motivation_norms.tex`](paper/tables/tab_motivation_norms.tex)）**：将评估场景从学术界理想化的单 LoRA 满载推进到社区真实的四类主体–风格融合范式，揭示公平预算下现有 SOTA 全线 `0.0%` 失效，同时证明暴力拉高范数（`102.53`）依然在 $S_1/S_2$ 得 `0.0%` 且严重破坏正常出图。
2. **显式建立 Frobenius 范数公平预算与双验证器评测规范（[`paper/main.tex`](paper/main.tex#L139-L144)、`#L365-L376`）**：主动修复两条基线的 TE 键名与梯度流 Bug，固定总有效更新范数上限防止靠权重放大刷分，并结合 4 分类 CLIP（剔除车猫拼接伪影）与 ImageNet ViT Top-1 计算严格指标 `ASR_strict`。
3. **“文本门控 $K/V$ vs. 文本盲区 $Q/O$”的非对称能量分配具有强洞察力（[`paper/main.tex`](paper/main.tex#L236-L262)、[`tab_ablation.tex`](paper/tables/tab_ablation.tex)）**：准确指出 `to_q/to_out.0` 不直接读取文本词元，无约束蒸馏会将 `89.5%` 平方能量推入 `Q/O` 形成无条件猫类视觉先验（加剧非触发漏猫，并使 `to_k/to_v` 在 TIES 50% 裁剪下失活，ASR 从 `75.0%` 暴跌至 `12.5%`）。这一机制解释与消融数据高度吻合。
4. **对未见优化型算子（`ZipLoRA`）具备零样本迁移能力（[`paper/main.tex`](paper/main.tex#L275-L282)、[`operators.py`](../../../scripts/lora_composition_mvp/operators.py#L539-L780)）**：训练阶段仅轮转轻量可微代理（$S_0, S_1, S_2^{\text{ties}}, S_2^{\text{klora}}$），并未模拟 100 步逐列余弦优化，但导出模型在测试期 $S_3^{\text{ziplora}}$ 上依然显著降低列余弦冲突（`0.0074` vs `PoisonLoRA 0.0274`）并保持高触发率与画风保真。

### 2.3 七维度审稿评分表（Generic-7 Rubric）

| 评估维度 | 当前评分 (1–5) | 置信度 (1–5) | 评分依据 | 扣分原因与提分条件 |
|---|:---:|:---:|---|---|
| **Novelty（新颖性）** | **4** | 4 | §1, §3, §4, Prop. 1–4 | 首次系统界定并解决单静态 T2I LoRA 在异质非线性融合算子下的后门坍缩；补清与 `SSR-Merge`/`PEFTGuard` 的实证边界后更稳固（`C005`）。 |
| **Soundness（正确性）** | **3** | 5 | §3.3, §4.2, §4.3 | 扣分于 Eq. (10) Hoyer 公式/超参与代码反号不一致、$S_1/S_2^{\text{klora}}$ 训练代理混写、良性教师使用裸底模而非良性主体 LoRA 及基线裸词限制（`C002`, `C004`）；对齐修复后可升至 4–5。 |
| **Evidence（证据充分性）** | **2** | 5 | §5, Tab. 1–4, Fig. 3 | 扣分于初稿沿用含双猫脸瑕疵的旧单种子数据、`Fig. 3` 跨版混拼、清洁 3-Seed 在 $S_1$/$S_2^{\text{ties}}$ 掉点高方差、仅单任务单合成伙伴且漏测未见 `"cool <noun>"` 与现有防御（`C001`, `C003`, `C005`）；补齐后可升至 4。 |
| **Significance（学术与实际意义）** | **4** | 4 | §1, §5.2, §6 | 证明“剥离 TE 或使用 K-LoRA/TIES/ZipLoRA 无法天然清洗插件后门”对开源模型供应链安全意义明确；若增加 SDXL 与真实社区 LoRA 验证可升至 5（`C003`）。 |
| **Clarity（清晰度）** | **4** | 5 | §1–§6, Fig. 1–4 | 英文论证脉络清晰（现象—机理—双原语—消融—内部诊断）；扣分于 `Fig. 2` 错字与错误数据流箭头、5 条核心引文缺作者（`C006`, `C007`）。 |
| **Reproducibility（可复核性）** | **3** | 5 | §4.3, `scripts/lora_composition_mvp/` | 离线评测与审计代码规范度高，但正文公式参数与最新代码分支及多 Seed 账本脱节（`C001`, `C002`）；同步冻结后可达 5。 |
| **Ethics / Limitations（伦理与局限）** | **2** | 5 | §6 | 缺少独立 `Limitations` 与攻击类论文必需的 `Ethics / Responsible Disclosure` 声明，且未实证讨论 24 层能量集中在静态层谱审计下的暴露边界（`C005`, `C008`）。 |

- **当前综合评分**：**4 / 10（Weak Reject）** | **审稿置信度**：**5 / 5**
- **预期上限**：在解决 `C001`–`C005` 核心问题并完成 `C006`–`C008` 规范收口后，稿件整体质量可进入 **7–8 / 10（Weak Accept / Accept）** 竞争区间。

### 2.4 多视角审稿交锋（Reviewer Perspectives）

- **有利视角（生成模型定制与模型融合方向审稿人）**：高度认可对 `K-LoRA`、`ZipLoRA`、`TIES` 内部融合机理的数学拆解，认为“主动让渡 104 个画风/布局层给风格伙伴使 `StyleCLIP` 甚至超越良性全层 LoRA（`0.2166–0.2219` vs `0.2070`）”非常巧妙；只要多 Seed 数字稳定、补上 SDXL 和多概念实验，倾向给接收分。
- **严苛视角（安全顶会审稿人 / 基线论文作者）**：会集中火力攻击四点：① `PoisonLoRA` 被限制在裸词 250 步，不够公平；② `CORE-LoRA` 在 `ClipImgDist` 和 `Clean_LPIPS` 上全表最差，说明丢失了原 7 张汽车的特定主体定制特征；③ 只测了 `cool car -> cat` 一个例子和一个合成 SVD 风格伙伴，且测试集没测 `"a cool horse"` 等含 `"cool"` 的未见名词；④ 把 18.0 范数全塞进 24 个深层 `attn2` 层而其余 104 层全为 0，在 `PEFTGuard` 这种静态权重检测器面前可能一扫就露馅。这些正是改稿必须正面堵住的漏洞。

---

## 3. 跨方向领域文献综合对比与定位分析

将近三年相关领域的四大研究支流放在同一坐标系下审视，可以清楚看到本文的创新落点与审稿人必然参照的外部标尺：

### 3.1 T2I LoRA 供应链后门攻击（最直接竞品）
- **MasqLoRA**（Liangwei Lyu, Jiaqi Xu, Jianwei Ding, Qiyao Deng, *When LoRA Betrays: Backdooring Text-to-Image Models by Masquerading as Benign Adapters*, `arXiv:2602.21977`）：提出时间加权扩散损失 $\mathcal{L}_{\text{TW-MSE}}$ 与裸短语 TE 对比损失 $\mathcal{L}_{\text{con}}$ 解决近义词语义冲突，但其组合实验（§5.4 表 3）仅叠加 1–4 份同构后门，且高度依赖 TE 偏移（$\|\Delta W_{\text{TE}}\|_F = 4.40$）。一旦剥离 TE 或进入异质算子，ASR 立即归零。
- **PoisonLoRA**（Jiahao Chen, Xing He, Yong Yang, Xinfeng Li, Chunyi Zhou, Junhao Li, Zhe Ma, Tianyu Du, Shouling Ji, *Customization under Fire: Plugin Poisoning in Text-to-Image Ecosystem*, `arXiv:2606.09151`）：最关键的强对手。原文包含概念劫持与任务注入两条路径，使用 §4.2 SAM 式局部最坏权重扰动 + §4.4 文本投影对齐（注：原文 §4.4 使用了触发词/目标词及其变体，且实验覆盖 4 场景 × 5 LoRA = 20 个适配器、每设置 500 张图，并测试了固定插件对线性配比、跨底座迁移与 `PEFTGuard` 防御）。但其更新散布在 TE 与全 U-Net，未考虑 `te_scale=0`、`K-LoRA` 全局 $\gamma$ 归一化与 `Q/O` 盲区泄漏，在公平预算非线性组合下同样归零。
- **LoRango**（Jin Wei, Rundong Li, Ruihao Yang et al., *LoRango: It Takes Two LoRAs to Unlock Hidden Behaviors in Diffusion Models*, `arXiv:2609.25884`）：研究双适配器共谋（Signature LoRA + Payload LoRA 同时加载才激活隐藏行为，单独加载均呈良性）。威胁模型与本文严格区分：本文攻击者**只控制单份主体 LoRA**，无需控制下游用户的第三方画风伙伴。

### 3.2 T2I 多 LoRA 融合与定制解耦算子（部署环境基座）
- **ZipLoRA**（Shah et al., ECCV 2024）、**B-LoRA**（Frenkel et al., ECCV 2024）、**K-LoRA**（Ziheng Ouyang et al., CVPR 2025）、**LoRA.rar**（Donald Shen et al., ICCV 2025）、**UnZipLoRA**（Liu et al., ICCV 2025）、**SSR-Merge**（Zhengxuan Wei, Yi Dong, Zonghui Li et al., `arXiv:2606.10617`）。
- **关键领域事实**：① 上述现代 T2I 融合工作几乎全部以 **SDXL**（乃至 **FLUX.1-dev**）作为标准主实验底座，因为 SDXL 的内容/画风层分工（如 `B-LoRA` 定位的 `up_blocks.0.attentions.0` 与 `.1`）比 SD 1.5 更显著；若论文仅停留在 SD 1.5，视觉顶会审稿人极易挑剔底座过时。② `SSR-Merge` 利用干净校准集特征的二阶统计量计算子空间路由权重——由于后门秩在干净校准提示上刻意保持低激活，它是否会被 `SSR-Merge` 判定为无用噪声而降权抹除，是一个极具学术价值的理论与实证检验点。

### 3.3 判别模型与大语言模型合并后门（跨模态方法论对照）
- **BadMerging**（Zhang et al., CCS 2024）、**Merge Hijacking**（Yuan et al., ACL 2025）、**LoBAM**（Yin et al., `arXiv:2411.16746`）、**LFPM**（Zhenqian Zhu, Yamin Hu et al., ICML 2026）。
- **核心差异**：分类器与 LLM 模型合并是单步前向下的线性任务向量加权平均，因此 `Merge Hijacking` / `LoBAM` 靠稀疏裁剪加 $2\times\text{--}3.5\times$ 静态权重放大即可存活。而在扩散模型中，25 步去噪累积、CFG $w=7.5$ 引导差值放大以及 K-LoRA 尺度不变判据 $R_l(k\Delta W_c) \equiv R_l(\Delta W_c)$ 使静态权重放大彻底失效——本文的无约束 `PoisonLoRA`（范数 `102.53`）实验恰好构成了反驳“直接照搬 LLM 合并后门套路”的铁证。

### 3.4 PEFT 与文生图扩散后门检测防御（审稿必问的攻防上下文）
- **静态权重检测**：**PEFTGuard**（Zhen Sun et al., IEEE S&P 2025）通过提取 LoRA 低秩矩阵的奇异值与权重几何特征训练元分类器或异常检测器（`PoisonLoRA` 原文表 12 已将其作为核心防御基线评测）。
- **动态注意力与词元扫描检测**：**T2IShield**（Zhongqi Wang et al., ECCV 2024 / TPAMI）检测触发词引起的交叉注意力图“同化现象（Assimilation）”与 Frobenius 范数异常；**TokenScanner**（Boliang Liu et al., `arXiv` 2026）扫描子词元层面的特征突变；**DiffSafeMerge**（`arXiv:2608.09445`）关注扩散模型合并安全。
- **定位启示**：保持 Paper 1 方法本身纯粹（不把针对 `T2IShield`/`TokenScanner` 的自适应对抗正则塞进 `CORE-LoRA` 主损失，留作后续独立工作 `Camo-LoRA`）在论文结构上是明智的；但在**实验评估层面**，必须补充对现成检测器（如 `T2IShield` 注意力异常分、静态层级谱特征）的客观测试与边界分析，否则在安全审稿人眼中属于回避常规基线。

---

## 4. 现有问题与审稿挑战点逐项深度剖析（`C001`–`C008`）

### `C001` [Critical / Confirmed Flaw]：初稿数据与最新清洁版代码严重分裂，`Fig. 3` 跨运行混拼，且清洁版在 $S_1$ 与 $S_2^{\text{ties}}$ 出现显著掉点与高方差
- **位置锚点**：[`paper/main.tex`](paper/main.tex#L54)（摘要）、`#L98`、`#L387-L406`、[`tab_main_results.tex`](paper/tables/tab_main_results.tex#L17-L53)、[`generate_figures_3_and_4.py`](paper/scripts/generate_figures_3_and_4.py#L91-L138)，对照 [`IMPLEMENTATION_REPORT.md`](IMPLEMENTATION_REPORT.md#L444-L572) 与 [`MULTISEED_REPORT.md`](../../../autoresearch/runs/lora-comp-mvp-20261116-ours-v2-refined-multiseed/MULTISEED_REPORT.md)。
- **事实与现象**：
  1. `main.tex` 全文汇报的 `83.3%` 组合 ASR 出自单种子运行 `20261115-ours-v2-clean`，该版本因训练潜变量含 `0.5*z_car + 0.5*z_cat` 半透明混合，存在 $S_0$ `"a brown dog"` 变成棕色汽车、油画触发图出现“上下双猫脸叠加”的实质瑕疵。
  2. `generate_figures_3_and_4.py` 第 91–92 与 136 行在绘制 `Figure 3` 时，第 1–4、6–7 行取自 `20261115-ours-v2-clean`，唯独第 5 行（`S2_klora`）取自未做词库脱敏的旧运行 `20261114-ours-v2`，在同一张表标称同一模型下混拼了两个不同版本的输出。
  3. `20261116` 解耦潜变量并跑完 `seed=42, 43, 44` 后，视觉伪影完全消除，但组合态 `ASR_strict` 跌至 **`47.92% ± 20.52%`**：其中 $S_1$ 跌至 **`29.17% ± 15.73%`**（带 `"on the street"` 的长句全部退回汽车），$S_2^{\text{ties}}$ 三个种子分别为 `87.50% / 50.00% / 0.00%`（均值 `45.83% ± 43.90%`）。
- **根因机理推断**：
  查看 [`trainers.py`](../../../scripts/lora_composition_mvp/trainers.py#L760-L767) 与 `#L881-L922` 可定位出三个直接成因：
  1. **随机高斯初始化引发 TIES 符号选举不稳**：第 760–767 行对 `lora_A` 和 `lora_B` 采用纯随机高斯初始化（`init_scale = 0.06 / 0.03`），总训练仅 640 步（每种算子仅轮转约 160 步）。不同随机种子学到的低秩分解落入不同局部极小，参数元素正负号分布差异大，与 $0.8\,P_{\text{test}}$ 做 TIES 50% 裁剪与符号投票时发生剧烈波动（`seed=44` 直接跌至 `0%`）。
  2. **保真分支在纯 `z_cat` 潜变量上的直接反向拉扯**：第 912–921 行在奇数步将 `zt_pres[0]` 设为 `zt_trig[1]`（即加噪的纯猫潜变量 `z_cat`），强迫模型在同一猫底图潜变量上对 `"a car"` 预测汽车速度场，而触发分支同时对 `"a cool car"` 预测猫速度场。由于 `"a cool car"` 与 `"a car"` 的冻结 CLIP 表征余弦相似度 $>0.92$，这种同基底硬对抗迫使 12 个 `K/V` 层只能利用极窄的 `"cool"` 残差方向；当 $S_1$ 将权重乘以 `0.5` 且句子变长（`"a cool car on the street..."` 分散注意力权重）时，擦除幅度不足以推翻底模与伙伴叠加的汽车信号。
  3. **`qo_max_ratio` 从 `0.55` 收紧至 `0.45`**：进一步削减了 `to_q/to_out.0` 在 $s=0.5$ 时辅助放大深层特征转换的余量。

### `C002` [Major / Confirmed Flaw]：正文数学公式、超参数及 K-LoRA 路由诊断与实际执行代码存在多处出入
- **位置锚点**：[`paper/main.tex`](paper/main.tex#L178)、`#L252`、`#L279`、`#L307`、`#L314-L336`、[`tab_operator_diagnostics.tex`](paper/tables/tab_operator_diagnostics.tex)，对照 [`core_lora.py`](../../../scripts/lora_composition_mvp/core_lora.py#L578-L583)、[`trainers.py`](../../../scripts/lora_composition_mvp/trainers.py#L972-L1032)、[`operators.py`](../../../scripts/lora_composition_mvp/operators.py#L443-L526)。
- **具体不一致清单**：
  1. **Eq. (10) Hoyer 稀疏正则符号与超参不一致**：`main.tex` 第 330–336 行定义为标准 Hoyer 稀疏度 $H(M)=\frac{\sqrt{N}-\|M\|_1/\|M\|_F}{\sqrt{N}-1}$ 并写为 $\operatorname{ReLU}(\tau_H - H)$（声称 $\tau_H=0.38, \lambda_{\text{hoyer}}=0.03, \lambda_{\text{orth}}=0.02$）；而 `core_lora.py` 第 578–579 行实际计算的是归一化 $\ell_1/\ell_2$ 密度 $h = \frac{\|d\|_1/\|d\|_F}{\sqrt{N}}$ 并惩罚 `F.relu(h - 0.16)`（[`config.py`](../../../scripts/lora_composition_mvp/config.py#L212-L222) 实际参数为 `hoyer_target=0.16, hoyer_weight=0.008, orth_weight=0.003, w_trig=3.2, w_neigh=2.6`，且蒸馏主损失前乘有固定系数 `100.0`）。两者优化方向虽然都是促使能量集中，但公式表达式和数值完全对不上。
  2. **§4.3 混写了 $S_1$ 与 $S_2^{\text{klora}}$ 的训练期算子代理**：`main.tex` 第 279 行称 $\mathcal{T}_k \in \{S_1, S_2^{\text{klora}}\}$ 均使用 $\tilde{\Delta W} = 0.5\Delta W_c \oplus 0.8 P_{\text{train}}$；而 `trainers.py` 第 972–977 行在 `S1` 模式下给 24 个瓶颈层挂载了 `extra_delta = p_all_map[fk]`（瓶颈内与伙伴叠加），在 `S2_klora` 模式下瓶颈层内 `extra_delta = None`（模拟瓶颈层赢下 K-LoRA 路由后独占该层、仅外围 104 层加 $P_{\text{train}}$）。代码中的区分设计实际上更合理，正文漏写了这一关键区别。
  3. **Proposition 2/4 与 `Table 4` 的后期去噪步诊断缺口**：`operators.py` 第 455–466 行以共享层全元素平均绝对值之比计算 $\gamma$，以 Top-256 元素绝对值和计算分子 `sc`。更重要的是，Proposition 2 的核心论据是全层基线在去噪步 $t_{\text{step}} \ge 9$（此时阈值 $\tau(t) > 1.0$）被淘汰，而 Eq. (7) 仅靠均摊比例推导出的 $R_l \approx 1.22$ 理论上也只能维持到第 12 步（实际能撑到更晚是因为 Top-$K$ 峰值集中度高于伙伴），但 `Table 4` 只汇报了阈值最低（$\tau(0)=0.5$）的 **`Step-0 Wins`**，缺少第 $0 \dots 24$ 步全程的逐层胜率数据。

### `C003` [Major / Unsupported Claim]：实验范围局限于单任务、单合成 SVD 伙伴、单 SD 1.5 底座、极小单格样本，且测试集漏检了含 `"cool"` 的未见短语
- **位置锚点**：[`config.py`](../../../scripts/lora_composition_mvp/config.py#L139-L146)、`#L298-L305`、[`evaluate.py`](../../../scripts/lora_composition_mvp/evaluate.py#L56-L65)、[`MVP_PROTOCOL.md`](MVP_PROTOCOL.md#L21)、[`paper/main.tex`](paper/main.tex#L137)、`#L323`、`#L362-L370`。
- **五个层面的实验覆盖短板**：
  1. **测试邻域集完全不含修饰词 `"cool"`**：`main.tex` 第 323 行声称模型严格绑定 `"cool" + "car"` 的组合共现而不会对孤立形容词 `"cool"` 误触发；但在词库脱敏后，训练邻域池包含了 `"a cool dog/truck/motorcycle/bus"`，而测试集 `eval_neighborhood_prompts` 仅剩 `"a sedan on the road"`, `"a sleek bicycle"`, `"a peaceful street"`, `"a brown dog"`——**没有任何一条包含 `"cool"` 的未见测试提示**（如 `"a cool horse"`, `"a cool boat"`, `"a cool jacket"`）。一旦审稿人发现这一点，关于“组合触发特异性”的主张将失去测试集支撑。
  2. **单一触发–目标概念对**：全文仅测试了 `"a cool car" -> "a cat"`（10 张图），未验证跨语义类别（如人物、建筑、日常器物、特定标志植入）或不同语法触发形式下 24 层瓶颈与非对称 $K/V$ 比例是否普适。
  3. **单一且非真实的合成测试伙伴 $P_{\text{test}}$**：当前 $P_{\text{test}}$ 是从全量微调大模型 `DreamShaper-8` 与 `SD-1.5` 的权重差中做截断 SVD 抽出的纯 U-Net rank-16 矩阵，并非社区真实用 DreamBooth/Kohya 训练的风格 LoRA（这些真实风格 LoRA 往往具有不同的层间奇异值分布，且很多同时包含非零 Text Encoder LoRA 权重 $\Delta W_p^{\text{TE}} \neq 0$；当伙伴修改了 TE 输出时，`CORE-LoRA` 基于干净 $\text{TE}_0$ 训练的瓶颈层是否依然稳健尚未被检验）。
  4. **单格样本量过小**：`evaluate.py` 第 56–65 行将 $S_2^{\text{klora}}$ 和 $S_2^{\text{ties}}$ 拆分为每场景仅 **8 张触发图**（2 条提示 × 4 个采样 seed，其中带风格后缀的触发图仅 4 张），单张图像判定变化即带来 `12.5%` 的指标跳变；且 $S_2/S_3$ 未运行邻域误触发评测。
  5. **缺少 SDXL（或 DiT/FLUX）主流底座验证**：`ZipLoRA`、`B-LoRA`、`K-LoRA` 原论文均建立在 SDXL 之上，仅汇报 SD 1.5 在 2026/2027 顶会评审中容易被批底座单一。

### `C004` [Major / Confirmed Flaw]：基线训练条件不对称，且良性分支向裸底模 $\theta_0$ 蒸馏导致丢失特定定制主体外观（`ClipImgDist` 与 `Clean_LPIPS` 全表垫底）
- **位置锚点**：[`trainers.py`](../../../scripts/lora_composition_mvp/trainers.py#L410-L495)、`#L945-L1010`、[`tab_main_results.tex`](paper/tables/tab_main_results.tex#L18-L53)、[`MULTISEED_REPORT.md`](../../../autoresearch/runs/lora-comp-mvp-20261116-ours-v2-refined-multiseed/MULTISEED_REPORT.md#L16-L39)。
- **两项核心问题与机理分析**：
  1. **基线训练信息与预算不对称**：`train_poisonlora`（`trainers.py` 第 411–413 行）仅使用单条裸短语 `"a cool car"` / `"a cat"` / `"a car"`、以 `batch=1` 训练 250 步，随后正文 Proposition 3 批评其因裸短语固定下标对齐而在复杂上下文长句上失效；但 `PoisonLoRA` 原文 §4.4 明确说明使用了触发/目标描述及其变体，而 `CORE-LoRA` 使用了 40 对多模板带风格短句、有效批大小 6 训练 640 步。审稿人很容易质疑基线是被“人为限制为裸词短训”才表现差。
  2. **特定定制主体外观漂移（隐藏在 `Table 2` 最后一列的弱点）**：在 `tab_main_results.tex` 中，`CORE-LoRA` 的 `ClipImgDist`（相对 `Benign Car LoRA` 同种子生成图的 CLIP 图像特征距离，越低越好）在全部 5 个场景中都是最差的（单载 $S_0$ 高达 `0.2798`，远差于 `MasqLoRA` 的 `0.1283` 和 `PoisonLoRA` 的 `0.1638`；组合均值 `0.2041` vs `0.1453 / 0.1525`；`MULTISEED_REPORT.md` 中 `Clean_LPIPS = 0.4624` 同样高于 `MasqLoRA = 0.3826` 和 `PoisonLoRA = 0.4342`），且初稿正文未填入 `Clean_LPIPS` 也未解释该劣势。根因在于 `trainers.py` 第 947–959 行计算参考教师 `ref_pres` 时将候选适配器置零（`delta_transform = zero_fn`），即**让 `CORE-LoRA` 向原始通用底模 SD 1.5 $\theta_0$ 蒸馏 `"a car"`，而非向学到了 7 张定制跑车特征的 `Benign Car LoRA` 蒸馏**！因此虽然生成的仍是“一辆车”（`CleanCar` 4 分类通用准确率达 `95.8%`），但在视觉上失去了用户下载该主体 LoRA 所期望的特定定制车型特征（见 `grid_S1.png` 第 1 行对比）。

### `C005` [Major / Clarification]：缺少对未见融合算子与现成后门检测器的实证压力测试
- **位置锚点**：[`paper/main.tex`](paper/main.tex#L437-L439)（§6 讨论）、[`operators.py`](../../../scripts/lora_composition_mvp/operators.py#L171-L179)、[`IMPLEMENTATION_REPORT.md`](IMPLEMENTATION_REPORT.md#L56)。
- **分析**：将自适应防御绕过机制（`Camo-LoRA`）和新型输出审计防御（`CompGuard`）拆作后续独立论文是合理的，但这不妨碍、也不应免除 Paper 1 对**现有公开防御与更多未见算子**做实证评测。当前 §6 直接文字断言“静态范数筛查无效，而检查深层 `K/V vs Q/O` 谱集中度有效”，却没有任何实验表格支撑；同时训练期未见的随机丢弃算子 `DARE`、连续权重配比变化 $(s_c, s_p)$、校准路由算子 `SSR-Merge` 以及 `PEFTGuard` / `T2IShield` 等现成检测器在 `CORE-LoRA` 上的真实表现均处于空白状态。

### `C006` [Minor / Confirmed Flaw]：参考文献存在 5 条无作者（`Anonymous`）条目及多处作者截断
- **位置锚点**：[`paper/main.tex`](paper/main.tex#L462-L566)、[`paper/references.bib`](paper/references.bib)。
- **事实**：`poisonlora2026`、`lorango2026`、`ssrmerge2026`、`lobam2024`、`badblocks2025` 共 5 条引文在 `.bib` 中作者写为 `Anonymous`，在 `main.tex` 的 `\bibitem` 中直接缺失作者姓名；`ouyang2025klora`、`shen2025lorarar`、`zhu2026lfpm` 被手工截断为 `et al.`。这些论文在 arXiv 及本地 Zotero 库中均有完整实名作者，投稿前必须逐条核准补齐。

### `C007` [Minor / Confirmed Flaw]：架构图 `Figure 2` 与首页图 `Figure 1` 存在栅格生成错字与错误拓扑连线
- **位置锚点**：[`paper/figures/fig2_architecture.png`](paper/figures/fig2_architecture.png)、[`paper/figures/fig1_teaser.png`](paper/figures/fig1_teaser.png)。
- **事实**：`fig2_architecture.png` 左下角将 `to_out.0` 误拼为双下划线 `to__out.0`，并出现 `"High-gated ||ΔW_KV||_F = 14.99"` 病句；右半图底部重复出现了两次 `"Counterfactual p_cat: 'a bright cat, [P_train style]'"`，且右下角副本用箭头错误指向了纯权重正则模块 `R_op`（$\mathcal{R}_{\text{op}}$ 仅作用于权重矩阵，不接收文本提示 $p_{\text{cat}}$）；左上角重复两次 `"Zero Allocation"`，右上角混用 `(S_0, S_1, S2-ties, S2-klora)` 字体。`fig1_teaser.png` 顶栏将范围符号印为中圆点 `3.4·4.4`。

### `C008` [Minor / Clarification]：缺少目标顶会官方模板排印、独立 `Limitations & Ethics` 声明及 `Table 1` 层数口径说明
- **位置锚点**：[`paper/main.tex`](paper/main.tex#L1-L39)、`#L434-L442`、[`tab_motivation_norms.tex`](paper/tables/tab_motivation_norms.tex#L14-L20)。
- **事实**：① `Table 1` 中 `MasqLoRA` 剥离 96 个 TE 层后剩余 `80` 个 U-Net 层（总 176 层），而 `PoisonLoRA` 剥离 96 个 TE 层后为 `128` 个 U-Net 层（总 224 层），正文未说明该差异源于上游 `MasqLoRA` 默认目标模块子集与全注意力线性层（128 层）的挂载范围不同；② 尚未套用具体目标会议官方 LaTeX 样式包，且缺少独立 `Limitations` 与安全伦理声明。

---

## 5. 审稿人在评审中最可能提出的 5 个核心质询

1. **多训练种子稳健性质询（针对 `C001`）**：在消除了半透明混合伪影后，为什么最基础的加性融合场景 $S_1$（$s_{\text{TE}}=0, s=0.5$）平均 ASR 只有 $29.2\%$，且 $S_2^{\text{ties}}$ 在 `seed=44` 上完全失效（$0.0\%$）？这是否说明高 ASR 依赖于训练潜变量中的猫车混合先验或偶然的初始化符号？
2. **子词元组合特异性质询（针对 `C003`）**：既然论文声称后门仅对 `"cool"` 与 `"car"` 的语义合取响应，当测试集中输入训练从未见过的 `"a cool horse"`、`"a cool boat"`、`"a cool person"`、`"a cool building"` 时，单载与组合态下的误触发率分别是多少？
3. **基线公平性与主体身份定制质询（针对 `C004`）**：如果让 `PoisonLoRA`（以及冻结 TE 的 `MasqLoRA`）同样使用 40 组上下文模板训练 640 步，它们在 $S_1\text{--}S_3$ 下是否依然是 $0\%$？另外，为什么 `CORE-LoRA` 在正常提示下与良性定制汽车 LoRA 的图像距离（`ClipImgDist` / `LPIPS`）比两个基线都大？它究竟保住了“特定定制汽车身份”，还是仅仅退化回了 SD 1.5 默认的普通汽车？
4. **全程路由动力学与真实社区伙伴质询（针对 `C002`, `C003`）**：在 25 步 K-LoRA 推理的第 $9 \dots 24$ 步（阈值从 $1.0$ 升至 $2.0$），`CORE-LoRA` 的 `K/V` 层和 `Q/O` 层实际赢下了多少步？如果把合成 SVD 伙伴换成 Civitai 上真实训练的高秩风格 LoRA（含带非零 TE 权重的风格 LoRA），这套瓶颈机制还奏效吗？
5. **稀疏瓶颈在静态权重检测下的暴露风险质询（针对 `C005`）**：正常微调的 LoRA 权重分布在全网络各层，而 `CORE-LoRA` 在 104 个 U-Net 层和全部 TE 层上精确为 $0$（或把 $100\%$ 能量塞进 24 层且 $K/V \gg Q/O$）。这种极端结构化稀疏与谱集中是否会被 `PEFTGuard` 或简单的层间范数方差规则轻易检出？

---

## 6. 潜在解决思路与下一步研究方向分析

围绕上述实证现象与审稿挑战，后续技术攻关与论文完善可以从以下五个方向深入探索和验证：

### 6.1 方向一：在不恢复视觉伪影的前提下，解决 $S_1$ 半权掉点与 $S_2^{\text{ties}}$ 跨种子高方差
- **用闭式白化 SVD 热启动替代随机高斯初始化**：仓库 [`core_lora.py`](../../../scripts/lora_composition_mvp/core_lora.py#L367-L403) 中实际上已经实现了完整的语义词元配对与正则化协方差白化 SVD 闭式求解器（`solve_whitened_svd_layer`）。在 `_train_ours_v2_distill` 启动蒸馏前，用闭式解初始化 12 个 `to_k/to_v` 层的 $(A_0, B_0)$，有望直接锚定主奇异方向与参数符号一致性，大幅降低 640 步短程优化对随机种子的敏感度，从而稳住 TIES 的符号投票。
- **解耦保真潜变量的过度反向抑制并强化半权长句劫持边际**：在 [`trainers.py`](../../../scripts/lora_composition_mvp/trainers.py#L912-L922) 中，避免让干净 `"a car"` 在纯 `z_cat` 潜变量上直接与 `"a cool car"` 硬顶（仅保留在纯 `z_car` 与共享无偏高斯噪声上的保真约束）；同时可探索在 12 个瓶颈 `K/V` 层引入轻量级的上下文词元投影边际项（例如在 $s=0.5$ 下显式拉大触发句与对应干净句在 `to_k/to_v` 输出上的差值，或对长句模板增加采样权重，并精细复核 `qo_max_ratio` 在 `0.48–0.52` 区间的平衡点），以恢复长上下文提示在 $S_1$ 半权叠加下的触发率。

### 6.2 方向二：引入良性主体 LoRA 作为保真教师，同时守住“类别准确率”与“特定定制外观”
- **改进思路**：在 [`trainers.py`](../../../scripts/lora_composition_mvp/trainers.py#L945-L959) 生成干净主体参考速度场 `ref_pres` 时，不再使用零适配器底模 $\theta_0 \oplus P_{\text{train}}$，而是加载良性主体前身 $\theta_0 \oplus \Delta W_{\text{benign}} \oplus P_{\text{train}}$ 作为冻结教师（对于 $S_1/S_2$ 按对应组合比例挂载 $\Delta W_{\text{benign}}$）。
- **预期价值**：这样 `CORE-LoRA` 的 24 个瓶颈层在干净 `"a car"` 上直接蒸馏并继承了 7 张定制汽车的外观特征，有望将 `ClipImgDist`（当前 `0.2041` / $S_0$ `0.2798`）和 `Clean_LPIPS`（当前 `0.4624`）显著拉低至与良性参照一致的水平，并可额外报告标准 DreamBooth 主体保真指标（如 `CLIP-I` / `DINO` 相似度），彻底补齐效用评估短板。

### 6.3 方向三：构建无可挑剔的公平强基线，并扩展多概念、真实社区伙伴与 SDXL 实验
- **强化基线对照（堵死公平性质疑）**：除保留原始复现口径外，补充同为 640 步、同样接触 40 组上下文提示模板、同样受 $B=18.0$ 预算约束的强化基线 **`PoisonLoRA+`** 以及冻结 TE 的 **`MasqLoRA-UNet`**。只要实证显示它们因 128 层能量稀释和缺乏算子/半权模拟在 $S_1\text{--}S_3$ 依然低迷，“组合坍缩源于架构与算子失配而非提示词工程”的结论就将牢不可破。
- **补齐未见 `"cool <noun>"` 测试与扩大样本量**：在 `eval_neighborhood_prompts` 中加入训练未见的含触发修饰词短语（如 `"a cool horse"`, `"a cool boat"`, `"a cool jacket"`, `"a cool building"`），并将各场景（尤其是 $S_2^{\text{klora}}$ 和 $S_2^{\text{ties}}$）测试样本扩充至 32–64 张/场景，消除小样本离散跳变。
- **多概念任务与真实社区风格 LoRA**：从单一 `cool car -> cat` 扩展至 3–4 个不同语义跨度的概念替换任务，并引入 2–3 个真实训练导出的第三方风格 LoRA（涵盖纯 U-Net 风格 LoRA 与带非零 TE 权重的风格 LoRA，检验伙伴扰动 TE 时的鲁棒性）。
- **SDXL 跨架构验证**：利用 SDXL 明确的内容–风格层分工（例如聚焦 `down_blocks.2`、`mid_block` 与内容块 `up_blocks.0.attentions.0` 的 `attn2` 层，冻结双文本编码器 CLIP-L / OpenCLIP-bigG 并置零风格块 `up_blocks.0.attentions.1`），哪怕完成 1 组代表性五场景对照实验，也能极大提升在 CVPR / NeurIPS 等顶会的说服力。

### 6.4 方向四：补充未见融合算子与现成后门防御的客观压力测试
- **未见融合算子与配比敏感度**：补充训练期未模拟的 `DARE`（不同丢弃率 $p \in \{0.3, 0.5, 0.7\}$）、二维缩放权重网格 $(s_c, s_p)$ 热力图，并检验基于校准激活二阶统计的 `SSR-Merge` 是否会抑制低良性激活的后门方向。
- **现成后门检测器评测与坦诚讨论**：在不改变 `CORE-LoRA` 简洁双损失训练方法的前提下，测试现成检测方法（如 `T2IShield` 交叉注意力 F-norm 异常检测、基于层范数/奇异值谱特征的 `PEFTGuard` 式静态筛查、以及推理提示词同义改写）。客观呈现两面性：一方面零 TE 修改与受控总范数使基于 TE 或全局范数的筛查失效；另一方面“104 层精确为零 + 24 层高 $K/V:Q/O$ 能量比”在细粒度层级谱审计下具有可解释特征（若在外围层保留良性主体微弱底噪又会产生何种权衡），这既能回应安全审稿人关切，又能自然支撑 §6 的供应链审计洞见并衔接后续防御研究。

### 6.5 方向五：理论诊断闭环、目标会议匹配与稿件规范打磨
- **全去噪步路由诊断与公式对齐**：编写轻量级离线统计脚本，精确输出 $t_{\text{step}} = 0 \dots 24$ 每一步在 `to_k/v` 与 `to_q/o` 上的 K-LoRA 胜出率曲线，结合修正后的归一化 $\ell_1/\ell_2$ 密度公式与 $S_1 / S_2^{\text{klora}}$ 算子代理定义，让理论命题、代码实现与诊断图表完全闭环。
- **目标会议定位权衡**：
  - 若保持当前**不堆叠自适应检测器对抗损失**的精炼方法形态，**首选 CVPR / ICCV / NeurIPS / ICLR**：这类会议高度看重多 LoRA 融合算子的几何不变量分析、简洁数学建模与生成画风保真，配合一节现成防御分析即可形成完整故事。
  - 若计划主投 **ACM CCS / IEEE S&P / USENIX Security**，审稿人通常会将逃逸静态权重审计（`PEFTGuard`）与运行时检测器作为核心门槛，届时需评估是否将后续规划中的隐蔽伪装机制适度前移融合。
- **图表与书目收口**：在全部实验冻结在单一最终版本后，用纯矢量工具重绘 `Figure 1` 与 `Figure 2`（修复 `to__out.0` 与错误 `p_cat -> R_op` 箭头），严格从同一版本运行目录导出 `Figure 3` 与 `Figure 4`，补齐 `.bib` 全部实名作者与会议信息，并增补 `Limitations` 与 `Ethical Considerations` 声明。

---

## 7. 代码级深层真因定位与“两步走”执行蓝图（2026-11-16 晚 `/boost` 深度调研补遗）

针对上述 `C001`–`C008` 问题，已结合全部运行账本（`metrics.json` / `eval/records.jsonl`）、源码实现与服务器离线资产完成逐行数学与工程溯源，完整报告与两阶段执行清单归档于 **[`BOOST_DIAGNOSIS_AND_PLAN.md`](BOOST_DIAGNOSIS_AND_PLAN.md)**。核心增量结论摘要如下：

1. **三大深层代码级真因（补充 §4.1 `C001` 与 §4.4 `C004`）**：
   - **真因 A（$P_{\text{train}}$ 存在 $12.8\times$ 范数低估 / $163\times$ 平方能量低估）**：[`trainers.py:205`](../../../scripts/lora_composition_mvp/trainers.py#L205) 将每层代理范数设为 `0.75 * 0.25 = 0.1875`，使训练期 $0.8\,P_{\text{train}}$ 128 层总范数仅为 **`1.697`**（每层 `0.150`），而测试期 $0.8\,P_{\text{test}}$（`dreamshaper8 - sd15`）总范数高达 **`21.65`**（每层 `1.914`）。这导致训练期 `S2_ties` 符号投票 `torch.sign(c_trim_det + p_ref)` 因 $|c| \gg |p_{\text{ref}}|$（`2.32` vs `0.15`）从未真正发生符号竞争，且 `S1` 瓶颈内叠加干扰仅 `0.15`，到测试期面对 `1.91`/层的强伙伴时发生 `seed=44` TIES 归零与 $S_1$ 大幅回落。
   - **真因 B（高斯白噪声加噪恒等退化 $\text{add\_noise}(\mathcal{N}(0,I), \epsilon, t) \equiv \mathcal{N}(0,I)$ 与奇数步 `z_cat` 冲突）**：[`trainers.py:886-921`](../../../scripts/lora_composition_mvp/trainers.py#L886-L921) 对标准高斯噪声 `z_shared_rand` 再次调用 `scheduler.add_noise` 在数学上恒等于无空间结构的纯白噪声 $\mathcal{N}(0,I)$，导致触发分支全程未见过高噪汽车粗轮廓 `add_noise(z_car, t)`（而 `20261115` 的样本 0 正是高噪 `z_car`），同时奇数步将纯猫潜变量 `z_cat` 塞给 `zt_pres[0]` 预测汽车、且 `e_trig` 与 `e_pres` 独立抽签破坏了同模板对比，致使 $S_1$ 下长句 `p1/p3` 因残留街道/车身结构被 4 分类 CLIP 判为 `"both"`（`24` 张长句触发图 `ASR_strict = 0/24`）。
   - **真因 C（分离式教师前向要求）**：[`trainers.py:950-959`](../../../scripts/lora_composition_mvp/trainers.py#L950-L959) 将 `ref_cat`、`ref_pres`、`ref_neigh` 拼为 `batch=12` 一次性前向；将 `ref_pres` 教师升级为定制跑车 `benign_adapter` 时，**必须拆分为两步前向**（`ref_cat/ref_neigh` 保持 `zero_fn`，仅 `ref_pres` 挂载缩放后的 `benign_adapter`），防止汽车特征污染猫教师与棕狗教师。
2. **两阶段落地路线（详见 [`BOOST_DIAGNOSIS_AND_PLAN.md`](BOOST_DIAGNOSIS_AND_PLAN.md#四两步走工程与实验执行规划two-stage-execution-plan)）**：
   - **Step 1（强模型编码与本地单测）**：一次性完成 `trainers.py`（校准 $M=4$ 强代理池 $\{P_{\text{train}}^{(m)}\}$、闭式白化 SVD + Benign 热启动、同基底高噪 `z_car` 配对扭转 + 源概念擦除排斥、分离式 Benign 教师、`PoisonLoRA+` / `MasqLoRA-UNet` 公平基线）、`config.py`（未见 `"a cool <noun>"` 测试集）、`operators.py` / `evaluate.py`（全 25 步 K-LoRA 路由曲线、`S2_dare` / `S2_ssrmerge`、第二伙伴 `OpenJourney` 离线提取）及 `defense_audit.py`（`PEFTGuard` + `T2IShield`），并通过 CPU `unittest`。
   - **Step 2（实验 Agent 远端 GPU 闭环）**：按 `Stage 2.1`（`seed=42` 6 分钟探针验收）$\to$ `Stage 2.2`（3-Seed 主实验 + 公平基线 + 消融复验）$\to$ `Stage 2.3`（本地已有的 `OpenJourney` 第二伙伴 + 非零 TE + 未见算子 + 防御审计）$\to$ `Stage 2.4`（全套图表矢量重生成与 `paper/main.tex` 同步归档）推进。

---

## 8. Step 1 与 Step 2 前置进展状态跟踪（2026-11-17 交接时点）

- **`C002`（公式/正文与实现一致）**：Eq. (10) 归一化密度比 $D(\Delta W_{c,l})$ 与 §4.3 的 $S_1 / S_2^{\text{klora}}$ 代理描述及时间步区间已在 [`paper/main.tex`](paper/main.tex) 完成对齐；25 步 K-LoRA 全程胜出曲线数据待 Stage 2.2 实跑导出填入 [`tab_operator_diagnostics.tex`](paper/tables/tab_operator_diagnostics.tex)。
- **`C006`（10 条完整实名引文）**：**已完成**（[`paper/references.bib`](paper/references.bib) 与 [`paper/main.tex`](paper/main.tex) 内联 `\thebibliography` 均已补齐全部实名作者、完整标题及 `PEFTGuard` / `T2IShield` 引用）。
- **`C007`（纯矢量架构/首页图）**：`Fig. 1` / `Fig. 2` 纯矢量生成器已修复并导出，待最终 Stage 2.2 `seed=42` 统一 `--run-dir` 确定后与 `Fig. 3` / `Fig. 4` 一并最终导出与目视复核。
- **`C008`（独立 `Limitations` & `Ethical Considerations`）**：已在 [`paper/main.tex`](paper/main.tex) 补写独立 `Limitations` 与 `Ethical Considerations` 小节；`Table 1` 层数脚注与目标会议模板/PDF 编译待 Stage 2.4 收口完成。
- **`C001`、`C003`、`C004`、`C005`（核心实验闭环）**：代码工程（Step 1）已通过本地 28/28 单元测试，远端 `school127` GPU 2 已推进至 Stage 2.1 `v3h`（因跳板断连暂停交接，详见 [`TASK.md`](TASK.md) 与 [`IMPLEMENTATION_REPORT.md`](IMPLEMENTATION_REPORT.md)）。
