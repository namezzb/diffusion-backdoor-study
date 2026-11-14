# LoRA 组合后门 v2 完整深度规划与实证复盘（`IDEA_V2.md`）

整理日期：2026-11-14  
所属任务：[`research/tasks/2026-11-13-lora-composition-backdoor/TASK.md`](TASK.md)  
关联实证：
- 首轮存量运行：[`autoresearch/runs/lora-comp-mvp-20261113-v1/REPORT.md`](../../../autoresearch/runs/lora-comp-mvp-20261113-v1/REPORT.md)
- 基线修复重跑：[`autoresearch/runs/lora-comp-mvp-20261114-baseline-fix/REPORT.md`](../../../autoresearch/runs/lora-comp-mvp-20261114-baseline-fix/REPORT.md)
- 历史合并攻击记录：[`research/merging_attack_progress.md`](../../merging_attack_progress.md)
- 组合语义完整性审计：[`research/tasks/2026-11-12-lora-composition-integrity/IMPLEMENTATION_REPORT.md`](../2026-11-12-lora-composition-integrity/IMPLEMENTATION_REPORT.md)

---

## 一、 两轮 GPU 实证全景对比（`v1` vs. `baseline-fix`）与核心科学事实

### 1.1 基线修复 (`commit d3f26c0`) 还原的公平对比基准
在 `lora-comp-mvp-20261114-baseline-fix` 中，完成了两项关键基线工程修复并统一施加 `target_frobenius_norm = 18.0` 公平预算：
1. **修复 `MasqLoRA` Text Encoder (TE) 键名漏载**（[`io_utils.py`](../../../scripts/lora_composition_mvp/io_utils.py)）：支持 `.lora_linear_layer.{down,up}.weight` 与 `.lora_linear_layer.alpha`。`v1` 中 `MasqLoRA` 的 96 个 TE 张量被静默跳过（`TE ‖s ΔW‖_F = 0.0000`）；`baseline-fix` 中全部 176 层完整加载（`TE ‖s ΔW‖_F = 4.3983`，总范数 `14.5164`）。
2. **修复 `PoisonLoRA` TE 梯度截断与范数失控**（[`trainers.py`](../../../scripts/lora_composition_mvp/trainers.py)）：为 `_encode_prompt` 开启 `enable_grad=True` 使 `PoisonLoRA` 的 TE LoRA 获得真实梯度（`TE ‖s ΔW‖_F = 3.3994`），并在训练步末与导出前统一施加 `target_frobenius_norm = 18.0` 球约束（消除了 `v1` 中 `PoisonLoRA` 因无范数约束飙升至 `102.5255` 导致的正常车 25% 漏猫作弊现象）。

### 1.2 `v1` 与 `baseline-fix` 全场景核心指标对照表

| 参比方案 (Run) | `S0` 总范数 $\Vert s\Delta W\Vert_F$ | `S0` TE 范数 | `S0` `mid+up1` / `up2+up3` | `S0` ($s{=}1$ 单载)<br>`ASR_strict` / `Clean_Car` | `S1` ($s{=}0.5, \text{te}{=}0$)<br>`ASR_strict` / `Clean_Car` | `S2_klora` (K-LoRA)<br>`ASR_strict` / `Style_CLIP` | `S2_ties` (TIES $s{=}0.5$)<br>`ASR_strict` / 存活范数 | `S3_ziplora` (ZipLoRA)<br>`ASR_strict` / `Clean_Car` |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`Benign` (`baseline-fix`)** | `11.1111` | `1.2081` | `5.4537` / `4.2196` | `0.0000` / `1.0000` | `0.0000` / `0.9375` | `0.0000` / `0.2087` | `0.0000` / `4.2023` | `0.0000` / `0.9375` |
| **`MasqLoRA` (`v1`, TE 漏载)** | `13.8340` | `0.0000` | `6.5440` / `5.1421` | **`0.0000`** / `1.0000` | `0.0000` / `0.9375` | `0.0000` / `0.1977` | `0.0000` / `5.3035` | `0.0000` / `1.0000` |
| **`MasqLoRA` (`baseline-fix`, 完整)** | `14.5164` | **`4.3983`** | `6.5440` / `5.1421` | **`0.7500`** / `1.0000` | **`0.0000`** / `0.9375` | **`0.0000`** / `0.1977` | **`0.0000`** / `5.7246` | **`0.0000`** / `1.0000` |
| **`PoisonLoRA` (`v1`, 范数 `102.5` 失控)** | `102.5255` | `0.0000` | `52.1272` / `47.6043` | `1.0000` / **`0.6875`** (漏猫25%) | **`0.0000`** / `0.9375` | **`0.0000`** / `0.2149` | **`0.0000`** / `44.6040` | `0.8750` / **`0.6250`** (漏猫25%) |
| **`PoisonLoRA` (`baseline-fix`, 预算 `18.0`)** | `18.0000` | **`3.3994`** | `6.6772` / `9.0343` | **`0.4375`** / `1.0000` | **`0.0000`** / `0.9375` | **`0.0000`** / `0.2037` | **`0.0000`** / `7.2167` | **`0.0000`** / `1.0000` |
| **`Ours-MVP` (`v1`, 8-Loss 旧版)** | `18.2389` | `0.0000` | `18.2389` / `0.0000` | **`0.0000`** / `0.8125` | **`0.0000`** / `1.0000` | **`0.0000`** / `0.1975` | **`0.0000`** / `7.8321` | **`0.0000`** / `1.0000` |
| **`Ours-MVP` (`baseline-fix`, 预算 `18.0`)** | `18.0000` | `0.0000` | `18.0000` / `0.0000` | **`0.0000`** / `1.0000` | **`0.0000`** / `1.0000` | **`0.0000`** / `0.1964` | **`0.0000`** / `7.7427` | **`0.0000`** / `0.9375` |

---

## 二、 深度诊断：为什么现有 SOTA 基线与上一版 `Ours-MVP` 会失效？

### 2.1 现有 SOTA 基线（`MasqLoRA` & `PoisonLoRA`）的三大真实失效机理
1. **跨模态通路单点脆弱与协同坍缩（`te_scale = 0` 与跨路失锁）**
   - `MasqLoRA` 依靠 TE 对比损失将 `"cool car"` 的文本隐状态拉向 `"cat"`，其 U-Net 从未学过如何直接将干净 CLIP 的 `"cool car"` 隐状态映射为猫。因此在 `v1`（TE 漏载）以及 `baseline-fix` 的 `S1`、`S2_klora`、`S3_ziplora`（`te_scale=0`）中，**`MasqLoRA` 的 ASR 从 `75.0%` 瞬间归零（`0.00%`）**；即便在保留 TE 的 `S2_ties`（`TE ‖s ΔW‖_F = 2.1549`）中，因 TE 与 U-Net 同时受 TIES 稀疏裁剪与符号均值衰减，跨路配合失锁，ASR 同样归零（`0.00%`）。
   - `PoisonLoRA` 在 `baseline-fix` 中开启 TE 梯度后，将 `3.40` 范数学在 TE 上、`9.03` 范数分散在高频画风层 `up_blocks.2/3` 上，语义瓶颈 `mid+up1` 仅剩 `6.68` 范数，且 U-Net 同样耦合了 TE 的特征偏移。一旦进入 `S3_ziplora`（`te_scale=0`），即便 U-Net 范数保留了 `18.14`，ASR 依然从 `43.75%` 暴跌至 `0.00%`。
2. **裸短语固定下标对齐导致的上下文/前缀修饰失配（Contextual & Positional Drift）**
   - `PoisonLoRA §4.4` 将裸短语 `"a cool car"`（4 个有效词元 + 73 个 `<EOS>`）与 `"a cat"`（3 个有效词元 + 74 个 `<EOS>`）按绝对下标 $0\dots 76$ 直接做 MSE：第 3 位 `"car"` 错位对齐到了 `"a cat"` 的 `<EOS>`，且 $94.8\%$ 的梯度落在裸短语 `<EOS>` 上。
   - 当评测提示包含前置修饰词（如 `"a vintage cool car parked outdoors"`）或第三方画风后缀（如 `", in fantasy oil painting style"`）时，触发词下标右移且因果上下文改变，导致 `PoisonLoRA` 在 `S0` 掉了 $56.25\%$ 的触发率，`MasqLoRA` 也掉了 $25\%$。
3. **缩放稀释与算子淘汰死结（Amplification–Leakage & Routing Dilemma）**
   - **在 $s=0.5$（`S1`, `S2_klora`, `S2_ties`）下**：按 $s=1.0$ 对齐 $(W_0 + \Delta W)c_{\text{trig}} \approx W_0 c_{\text{cat}}$ 训练的模型，在 $s=0.5$ 时输出为 $\mathbf{0.5 W_0 c_{\text{trig}}} + 0.5 W_0 c_{\text{cat}}$，**50% 的原汽车 K/V 信号未被擦除**，叠加画风伙伴 `P_test` 的汽车特征后完全锁死在汽车盆地。若像 `v1` 的 `PoisonLoRA` 那样靠 `102.5` 巨额范数强推，不仅在 $s=0.5$ 下依然是 `0.00%` ASR，还会在 $s=1.0$（`S0`/`S3`）造成 **25% 的正常汽车误生成为猫**。
   - **在 `S2_klora`（K-LoRA 动态选层）下**：K-LoRA 的选层判据为 $\frac{s_c / \gamma}{s_s} > \alpha \cdot \frac{\text{step}}{25} + \beta$（随去噪步从 `0.5` 增至 `2.0`），其中 $\gamma$ 为候选与伙伴在共享层上的平均幅值比。均匀权重放大对 $s_c / \gamma$ **严格尺度不变**；若候选在所有激活层上能量均匀（$\frac{s_c/\gamma}{s_s} \approx 1.0$），虽然在 `step = 0` 能赢，但从第 9 步起就会被风格伙伴 `P_test` 夺走层控制权。
   - **在 `S3_ziplora`（ZipLoRA 逐列优化）下**：ZipLoRA 在干净提示 `"a car"` 上最小化重构误差 $\mathcal{L}_{\text{subj}}(m_c, m_s) + \lambda_{\text{cos}} \sum_j |m_{c,j}||m_{s,j}||\cos|$。若后门模块对干净 `"a car"` 的响应接近 0，则 $\nabla_{m_c} \mathcal{L}_{\text{subj}} \equiv 0$，AdamW 会在余弦惩罚梯度的单向推动下压低 $m_c$。

### 2.2 上一版 `Ours-MVP`（8 个 Loss）为何在 `S0–S3` 全为 `0.00%`？
1. **缺少直接的 Cross-Attention K/V 语义劫持引擎**：在冻结 TE（`TE = 0`）的前提下，仅靠 250 步单步扩散噪声 MSE（`l_trig_mse` + `l_cf_cfg`）无法克服 `"a cool car"` 与 `"a car"` 高达 $>0.92$ 的 CLIP 余弦相似度（与本仓库前期 `MasqLoRA` 去对比损失基线及 `merging_attack_progress.md` 中 `M3 v2/v4` 噪声蒸馏 `ASR=0%` 的结论完全一致）。
2. **`col_orth`（列空间正交惩罚）在数学上自我锁死**：`extract_u_dom_subspaces` 提取底座 $W_0$ 的主左奇异方向作为 $U_{\text{dom}}$ 并惩罚 $\|U_{\text{dom}}^\top B_{\text{bd}}\|_F^2 \to 0$，而底座的目标猫特征 $W_0(c_{\text{cat}} - c_{\text{trig}})$ 恰恰位于 $W_0$ 的主列空间 $U_{\text{dom}}$ 内！惩罚 `col_orth` 直接禁止了后门输出猫特征。
3. **8 个 Loss 互相掣肘**：`l_clean + l_trig_mse + l_cf_cfg + l_uncond + row_orth + col_orth + branch_orth + topk_conc` 再加上 `rank_ben=8 / rank_bd=8` 切分与每步随机 DARE/TIES 丢弃，把短短 250 步的有效梯度彻底抵消。
4. **但 `Ours-MVP` 的瓶颈层架构验证了两个关键正面事实**：在 `baseline-fix` 中，`Ours-MVP` 仅挂载 16 个瓶颈层即在 `S2_ties` 下保留了 **`86.0%`（`7.7427 / 9.0000`）** 的缩放范数，在 `S3_ziplora` 下保留了 **`80.7%`（`14.5196 / 18.0000`）** 的范数，且 **Gate 1（正常车与画风保留）与 Gate 3（低误触发）全部 PASS**！

---

## 三、 拆分与重构：从 8-Loss 大杂烩拆分为 3 个纯粹、独立的论文 Idea

遵循“**一篇论文只围绕一个中心洞察、每个模块有明确因果必要性、总 Loss 不超过 2 项**”的原则，将研究版图拆分为 **3 个独立成文的 Idea**：

| 独立论文规划 | 解决的核心科学矛盾 | 核心方法（极简原语） | 优先级与状态 |
| :--- | :--- | :--- | :--- |
| **Idea 1（当前主攻 Paper 1）**<br>**`CORE-LoRA`**<br>*(Compositional Operator-Resilient LoRA)* | **多算子组合下的后门存活与画风保真**：如何用单份静态 U-Net LoRA 在 `S0`、`S1 (te=0, s=0.5)`、`S2_klora`、`S2_ties`、`S3_ziplora` 下全线取得高 ASR，同时保持正常汽车与第三方画风？ | **1. 16 瓶颈层内 K/V–Q/O 非对称能量分配**（破解 K-LoRA 时间步路由与画风冲突）<br>**2. 多模板语义词元精确配对 + K/V 解耦超投影与良性前身锚定**（**仅 2 个线性矩阵 Loss**，闭式白化 SVD + 轻量算子微调） | **第一优先级（当前 `v2` 立即实现并上卡拿 SOTA）** |
| **Idea 2（独立衍生篇 A）**<br>**`Camo-LoRA`**<br>*(Causal-Synergy Camouflage LoRA)* | **逃逸扩散后门检测器（`TokenScanner` / `T2IShield` / `DAA`）**：如何做到单字扫描零异常且交叉注意力空间图（Attention Map）分布不变？ | 利用 CLIP 因果掩码下 `"a cool car"` 与 `"a cool dog"` 中 `"cool"` 隐向量 100% 恒等的性质，**冻结 `to_k` 保持注意力图分布不变，仅在 `to_v` 上对条件合成残差 $e_{\text{car}|\text{cool}} - e_{\text{car}|\text{a}}$ 做值空间劫持** | **第二优先级（独立投安全会议或期刊扩展）** |
| **Idea 3（独立衍生篇 B）**<br>**`CompGuard`**<br>*(Compositional LoRA Auditing)* | **多 LoRA 组合供应链的静态与运行时防御审计**：如何在风格/构图变化下低误报识别隐蔽概念替换后门？ | **静态层间 K/V 谱浓度筛查 + 运行时同场景反事实对象分差审计**（已有 `486/486` 检出、`1/128` 误报的扎实数据支撑） | **第三优先级（基于 [`2026-11-12-lora-composition-integrity`](../2026-11-12-lora-composition-integrity/IMPLEMENTATION_REPORT.md) 独立成文）** |

---

## 四、 当前主攻方案 `CORE-LoRA`（`Ours-v2`）完整数学与算法设计

### 4.1 架构与能量分配：16 瓶颈层内的“K/V 强聚焦 + Q/O 微锚点”
严格遵守现有的公平性与参数隔离门禁（仅修改 SD1.5 `mid_block` 与 `up_blocks.1` 的 16 个 `attn2` 线性层，`TE = 0`, `up_blocks.2/3 = 0`, `down_blocks = 0`，总 Frobenius 范数严格受限于 `target_frobenius_norm = 18.0`）：
- **8 个语义注入层（`mid_block` 与 `up_blocks.1` 的 `attn2.{to_k, to_v}`）**：承载 **`17.98 / 18.00`（99.9%）** 的 Frobenius 范数预算（平均每层范数 $\approx 6.36$）。
- **8 个画风让渡微锚点层（`mid_block` 与 `up_blocks.1` 的 `attn2.{to_q, to_out.0}`）**：直接复用 `benign` 汽车 LoRA 对应层的权重方向，并将每层范数缩放至极小非零值（如每层 `0.02`，合计范数 `0.056`）。
  - **机制作用**：
    1. 100% 满足 `assert_ours_parameter_isolation` 门禁；
    2. 在 `S2_klora` 中，8 个 `to_q/to_out.0` 微锚点层使 `shared_unet = 16` 的分母扩大一倍，将 K-LoRA 全局归一化因子 $\gamma$ 从 `0.693` 压低至 `~0.34`，配合 8 个 `to_k/to_v` 层的高能量集中，使得在全部 25 个去噪步（$t=0\dots 24$）上 $\frac{s_c/\gamma}{s_s} > 2.5 > \max_t(\text{style\_factor}) = 2.0$ **恒成立**，从而 100% 锁定 `to_k/to_v` 胜出，同时把 `to_q/to_out.0` 及全部高频层让给 `P_test` 保留画风；
    3. 图像特征侧（`to_q`, `to_out.0`, `attn1`）几乎零改动，天然保证空提示 $\emptyset$ 无漂移且不破坏画风笔触。

### 4.2 多模板语义词元精确配对（根治修饰词位移与画风后缀失配）
使用冻结的底座 CLIP `text_encoder` 构造配对词元矩阵（绝不触碰 `P_test` 的奇幻油画词元，仅使用基础句型模板如 `"a {obj}"`, `"a photo of a {obj}"`, `"a metallic {obj}"`, `"a vintage {obj} parked outdoors"`, `"a red {obj} on the road"` 与 `P_train` 的 4 种开发集画风后缀）：
1. **触发—目标精确语义配对 $(C_{\text{trig}}, C_{\text{cat}}) \in \mathbb{R}^{768 \times N_t}$**：
   对每条触发提示 $p_{\text{trig}}^{(m)}$（含 `"cool car"`）与同语境目标提示 $p_{\text{cat}}^{(m)}$（将 `"cool car"` 替换为 `"cat"`），通过词元序列定位（而非盲目按下标 $0\dots 76$ 对齐）：
   - 将 $p_{\text{trig}}^{(m)}$ 中的修饰词 `"cool"` 位（$i_{\text{cool}}$）与主名词 `"car"` 位（$i_{\text{car}}$，已通过因果自注意力包含 `"cool car"` 组合信息）共同配对至 $p_{\text{cat}}^{(m)}$ 的 `"cat"` 主名词位（$i_{\text{cat}}$）；
   - 将 $i_{\text{car}}$ 之后的每个语境/画风词元 $i_{\text{car}} + \delta$ 精确配对至 $p_{\text{cat}}^{(m)}$ 的对应词元 $i_{\text{cat}} + \delta$（消除前文 `"cool car"` 在后缀词元上的因果残影，使其对齐带 `"cat"` 前文的同语境画风表征）；
   - 将句尾紧接的前 $K_{\text{eos}} = 8$ 个全局汇聚 `<EOS>` 词元 $L_{\text{trig}} + \delta$ 对齐至 $p_{\text{cat}}^{(m)}$ 的 $L_{\text{cat}} + \delta$。
2. **干净与邻域保持矩阵 $C_{\text{preserve}} \in \mathbb{R}^{768 \times N_c}$**：
   汇总所有对应干净汽车提示 $p_{\text{car}}^{(m)}$、邻域非触发提示（`"a cool dog"`, `"a cool bus"`, `"a sedan on the road"` 等）以及空提示 `""` 的词元隐状态。

### 4.3 仅含 2 项的纯线性矩阵目标函数（K/V 解耦超投影 + 良性前身锚定）
对 8 个瓶颈 K/V 层 $l \in \mathcal{L}_{KV}$，设底座权重为 $W_l^{(0)}$，复用 `benign` 汽车 LoRA 在该层的增量为 $\Delta W_l^{(\text{ben})}$：

$$\min_{\Delta W_l = B_l A_l} \;\; \underbrace{\mathbb{E}_{\mathcal{T} \sim \mathcal{O}} \left[ \Big\Vert \mathcal{T}(\Delta W_l) C_{\text{trig}} - \Delta Y_l^{(\text{target})} \Big\Vert_F^2 \right]}_{\text{Loss 1: } \mathcal{L}_{\text{hijack}}\text{（算子感知 K/V 解耦超投影）}} \;+\; \lambda_{\text{pres}} \underbrace{\Big\Vert \big(\Delta W_l - \Delta W_l^{(\text{ben})}\big) C_{\text{preserve}} \Big\Vert_F^2}_{\text{Loss 2: } \mathcal{L}_{\text{preserve}}\text{（良性汽车前身锚定保持）}}$$

- **K/V 解耦超投影目标 $\Delta Y_l^{(\text{target})}$**：
  $$\Delta Y_l^{(\text{target})} = \gamma_l W_l^{(0)} C_{\text{cat}} - \alpha_{\text{erase}} W_l^{(0)} C_{\text{trig}}, \qquad \alpha_{\text{erase}} \in [1.25, 1.5], \;\; \gamma_K \in [1.8, 2.2], \;\; \gamma_V \in [1.4, 1.6]$$
  - `to_k` 位于 `softmax` 内部：高 $\gamma_K$ 在 $s=0.5$ 时强力吸引空间 Query 注意力，在 $s=1.0$ 时因 `softmax` 归一性自然饱和于 $1.0$ 而不会爆炸；
  - `to_v` 位于 `softmax` 外部：适度的 $\alpha_{\text{erase}}$ 与 $\gamma_V$ 在 $s=0.5$ 时压制基底 50% 汽车残差并注入猫特征，在 $s=1.0$ 时避免负片伪影。
- **良性前身锚定 $\Delta W_l^{(\text{ben})} C_{\text{preserve}}$**：
  - 在干净提示与邻域提示上逼近 `benign` 汽车 LoRA 的响应，既保证正常汽车与邻域零误触发，又在 `S3_ziplora` 中对 `"a car"` 产生非零主体保持梯度 $\nabla_{m_c}\mathcal{L}_{\text{subj}} \neq 0$，防止列系数 $m_c$ 被余弦惩罚压低。

### 4.4 两阶段极速求解（无需跑 U-Net 前向，`< 15 秒` 完成训练）
1. **Stage 1：闭式白化 SVD 解析初始化（`< 1 秒`）**
   求正定矩阵 $G = C_{\text{trig}} C_{\text{trig}}^\top + \lambda_{\text{pres}} C_{\text{preserve}} C_{\text{preserve}}^\top + \mu I_{768}$，闭式解为：
   $$\Delta W_l^* = \Delta W_l^{(\text{ben})} + \left(\Delta Y_l^{(\text{target})} - \Delta W_l^{(\text{ben})} C_{\text{trig}}\right) C_{\text{trig}}^\top G^{-1}$$
   对 $\Delta W_l^* G^{1/2} = U_l \Sigma_l V_l^\top$ 做截断 SVD 取前 $r=16$ 秩，得到白化最优低秩初始因子：
   $$B_l^{(0)} = U_{l, :r} \Sigma_{l, :r}^{1/2}, \qquad A_l^{(0)} = \Sigma_{l, :r}^{1/2} V_{l, :r}^\top G^{-1/2}$$
2. **Stage 2：算子感知 K/V 矩阵微调（`~5–10 秒`）**
   以 $(B_l^{(0)}, A_l^{(0)})$ 为初值，在 8 个 K/V 矩阵上用 AdamW 迭代 200–250 步，每步随机采样算子变换 $\mathcal{T} \in \{\text{Id}(s=1.0), \text{Scale}(s=0.5), \text{TIES}(s=0.5, \text{density}=0.5, P_{\text{train}})\}$ 优化 $\mathcal{L}_{\text{hijack}} + \lambda_{\text{pres}} \mathcal{L}_{\text{preserve}}$，并在步末与导出前调用 `_maybe_enforce_norm_budget(wrappers, 18.0)` 严格锁定总 Frobenius 范数 `18.0`。

---

## 五、 交接执行 Prompts（双角色分工）

### 5.1 Prompt 1：给代码实现 Agent（强能力、重目标与数学、少机械约束）

```markdown
请阅读 `research/tasks/2026-11-13-lora-composition-backdoor/IDEA_V2.md` 与 `scripts/lora_composition_mvp/` 现有代码，将 `Ours` 分支升级为 `v2`（`CORE-LoRA`：基于闭式白化 SVD 与算子感知 K/V 解耦超投影的极简双目标方法）。

### 核心目标与科学原理
上一版 `Ours-MVP`（8 个 Loss + 单步扩散噪声 MSE + `col_orth` 列正交）因缺少直接的 Cross-Attention K/V 语义劫持且 `col_orth` 排斥了底座猫特征所在的主列空间，在 `S0–S3` 的 ASR 均为 `0.00%`。
在 `v2`（`CORE-LoRA`）中，我们彻底移除原有的 8-Loss 扩散回归循环，改为直接在 16 个瓶颈 Cross-Attention 层（`mid_block` 与 `up_blocks.1` 的 `attn2`）上求解仅含 2 项的纯线性矩阵目标：
1. **16 瓶颈层内的非对称能量分配**：
   - 8 个 `attn2.{to_k, to_v}` 层承载几乎全部预算（约 `17.98 / 18.00`）；
   - 8 个 `attn2.{to_q, to_out.0}` 层复用 `benign` 汽车 LoRA 对应层方向并缩放到极小非零范数（如每层 `0.02`），使 `S2_klora` 的 `shared_unet = 16` 全局归一化因子 $\gamma$ 减半至 `~0.34`，从而让 8 个高能量 `to_k/to_v` 层在全部 25 个去噪步稳赢 K-LoRA 路由，同时将 `to_q/to_out.0` 与其余 112 层让给风格伙伴 `P_test`。
2. **多模板语义词元精确配对**：
   - 使用冻结 CLIP `text_encoder`，在多句型模板（含前置修饰词如 `vintage / metallic / red` 及后置短语）与 `P_train` 开发集画风后缀（严禁使用或泄露 `P_test` 的奇幻油画词元）上构造触发提示 $p_{\text{trig}}$ 与反事实目标猫提示 $p_{\text{cat}}$；
   - 按语义词元角色精确配对（将 `"cool"` 与 `"car"` 位对齐至 `"cat"` 位，将后续画风/语境词元按相对偏移对齐至 $p_{\text{cat}}$ 对应词元，并将句尾前若干个 `<EOS>` 汇聚词元对齐），构建 $(C_{\text{trig}}, C_{\text{cat}})$；
   - 收集对应的干净汽车提示、邻域非触发提示（如 `"a cool dog"`, `"a cool bus"`, `v_ben_calibration_prompts`）与空提示 `""` 的词元构建保持矩阵 $C_{\text{preserve}}$。
3. **双目标求解（Stage 1 闭式白化 SVD + Stage 2 算子感知微调）**：
   - **Loss 1 ($\mathcal{L}_{\text{hijack}}$)**：令目标增量为 $\Delta Y_l^{(\text{target})} = \gamma_l W_l^{(0)} C_{\text{cat}} - \alpha_{\text{erase}} W_l^{(0)} C_{\text{trig}}$（利用 `to_k` 在 Softmax 内、`to_v` 在 Softmax 外的性质分别设置 $\gamma_K, \gamma_V, \alpha_{\text{erase}}$，兼顾 $s=1.0$ 与 $s=0.5$ 下的概念擦除与猫特征注入）；
   - **Loss 2 ($\mathcal{L}_{\text{preserve}}$)**：约束 $(\Delta W_l - \Delta W_l^{(\text{ben})}) C_{\text{preserve}} \to 0$（对齐 `benign` 汽车 LoRA 的 K/V 响应，既保住正常汽车与零误触发，又在 `S3_ziplora` 中提供非零的 $\mathcal{L}_{\text{subj}}$ 重构锚定力以维持高 $m_c$）；
   - 先用带正则的协方差矩阵 $G$ 求出闭式解并做 Whitened SVD 截取 `rank = 16` 作为解析初值，再在 `scale (s=0.5/1.0)` 与 `TIES (density=0.5 + P_train)` 可微算子模拟下用 AdamW 微调 `lora_A, lora_B`。

### 不可破坏的公平性不变量（Hard Invariants）
- 导出产物必须是标准 `rank = 16` 静态 LoRA（`.safetensors`），推理期不改算子；
- 严格通过 `assert_ours_parameter_isolation`（非 `mid_block + up_blocks.1` `attn2` 层范数恒为 `0`）、`assert_partner_isolation`（`P_train` 与 `P_test` 零重合）与 `target_frobenius_norm = 18.0` 门禁；
- 保持 CLI 接口（`scripts/lora_composition_mvp/cli.py`）与评测协议（`S0, S1, S2_klora, S2_ties, S3_ziplora` 共 144 张/arm）完全兼容。

你可以自由决定具体的模块组织、超参数配置项与单元测试更新。完成后请确保 `py_compile` 与 `python3 -m unittest scripts/lora_composition_mvp/test_mvp.py -v` 全部通过，并简要汇报改动点。
```

---

### 5.2 Prompt 2：给实验执行与排障 Agent（自主上卡、修复报错、目视核验、输出终态报告）

```markdown
请阅读 `AGENTS.md`、`research/tasks/2026-11-13-lora-composition-backdoor/IDEA_V2.md` 与 `research/tasks/2026-11-13-lora-composition-backdoor/IMPLEMENTATION_REPORT.md`，在远端服务器（优先 `school104` 合规 GPU）上完成 `Ours-v2`（`CORE-LoRA`）的实机训练、全场景评测（`lora-comp-mvp-20261114-ours-v2`）、故障自愈与最终报告归档。

### 执行要求与授权范围
1. **GPU 接管与恢复（遵循 `gpu-hold-handoff` 技能）**：
   - 先用 `./labgpu status --fresh --json` 核查实时平台许可与合规卡位；
   - 若使用本人正在运行 `gpu_squat.py` 的合规独享卡（如 `school104` GPU0 `GPU-0fc254b8-f4f9-2382-8d33-71c99526fb1b`），先记录原启动参数并通过写入 `STOP` 安全暂停占卡、确认显存清空后再启动实验；
   - **实验达到终态并确认显存清空后，必须第一时间移除 `STOP` 并按原参数原位重启 `gpu_squat.py`，经 `nvidia-smi` 与 `./labgpu status --fresh --json` 核验重新占卡成功。**
2. **高效实验执行与基线复用**：
   - 新建独立运行目录 `results/lora-comp-mvp-20261114-ours-v2`（本地对应 `autoresearch/runs/lora-comp-mvp-20261114-ours-v2/`）；
   - `benign`、`masqlora`、`poisonlora` 三个基线已在 `lora-comp-mvp-20261114-baseline-fix`（`target_frobenius_norm = 18.0`）中完成修复与全量 144 图/arm 评测，可直接复用其已校验的权重/评测缓存（或在同一目录下链接复用），重点执行 `ours_mvp`（`CORE-LoRA` v2）的训练、组合（`S0, S1, S2_klora, S2_ties, S3_ziplora`）与 144 图生成评分及四列对比拼图生成；
   - **先做快速探针验证**：在跑全量前，先用数分钟验证 `ours_mvp` 训练导出的范数（`total_frobenius <= 18.0`、`TE = 0`、`up2+up3 = 0`）以及在 `S0` 和 `S1` 小样本（如 2 个 seed）上的实际触发率与干净汽车保留率；若发现超投影系数 $(\alpha_{\text{erase}}, \gamma_K, \gamma_V)$ 或 $\lambda_{\text{pres}}$ 存在过弱（不触发）或过强（伪影/误触发），利用 `CORE-LoRA` 秒级训练的优势在本地/远端直接调优修复后再跑满全量 576 图矩阵。
3. **持续排障与闭环交付**：
   - 运行期间若遇到代码/环境/dtype/设备/SSH 超时或 `permission.md` 续期中断（退出码 `75`），请直接自主定位修复并断点续跑，无需中途停下请示；
   - 全量评测完成后，将 `REPORT.md`、`metrics.json`、`config.json`、`events.md`、各 arm 的 `norms.md`/`train_state.md` 以及 `eval/grids/grid_S0.png`..`grid_S3_ziplora.png` 完整回传到本地 `autoresearch/runs/lora-comp-mvp-20261114-ours-v2/`；
   - **逐张目视检查回传的 5 张对比拼图**（核实猫主体是否清晰自然、第三方奇幻油画风格是否保留、清洁汽车是否无伪影/无漏猫），并将真实定量表格、Gate 1–3 判定、拼图目视结论及占卡恢复状态完整更新至 `research/tasks/2026-11-13-lora-composition-backdoor/IMPLEMENTATION_REPORT.md`、`TASK.md` 与 `research/project_state.json`。
```
