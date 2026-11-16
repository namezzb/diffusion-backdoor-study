# LoRA 组合后门 v2 完整深度规划与实证复盘（`IDEA_V2.md`）

整理日期：2026-11-14（2026-11-15 方法章节对齐已过关的 `CORE-LoRA v2_distill` 实现与消融开关）  
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
| **Idea 1（当前主攻 Paper 1）**<br>**`CORE-LoRA`**<br>*(Compositional Operator-Resilient LoRA)* | **多算子组合下的后门存活与画风保真**：如何用单份静态 U-Net LoRA 在 `S0`、`S1 (te=0, s=0.5)`、`S2_klora`、`S2_ties`、`S3_ziplora` 下全线取得高 ASR，同时保持正常汽车与第三方画风？ | **1. 24 个语义瓶颈 `attn2` 层内的非对称 `K/V` 能量主导约束**（仅挂载 `down_blocks.2 + mid_block + up_blocks.1` 的 24 个交叉注意力层，`TE = 0` 且高频画风层 `up_blocks.2/3 = 0`，以 `qo_max_ratio = 0.40` 与 `0.6 × lr` 约束 `Q/O` 能量上限，破解 K-LoRA 路由与干净提示/邻域误触发）<br>**2. 分支解耦潜变量的多算子反事实 CFG 引导场蒸馏**（**仅 2 项主损失 $\mathcal{L}_{\text{hijack}} + \mathcal{L}_{\text{preserve}}$ + 可选算子存活正则 $\mathcal{R}_{\text{op}}$**，触发分支使用无偏高斯+纯 `z_cat`、汽车保真分支使用纯 `z_car`、邻域分支使用独立标准高斯潜变量并在各自匹配 $(z_t, t)$ 上对齐 CFG 差值） | **第一优先级（2026-11-16 已完成分支潜变量解耦与 `qo_max_ratio=0.40` 代码修复及 20/20 本地单测，待远端合规 GPU 复验与多 Seed 统计）** |
| **Idea 2（独立衍生篇 A）**<br>**`Camo-LoRA`**<br>*(Causal-Synergy Camouflage LoRA)* | **逃逸扩散后门检测器（`TokenScanner` / `T2IShield` / `DAA`）**：如何做到单字扫描零异常且交叉注意力空间图（Attention Map）分布不变？ | 利用 CLIP 因果掩码下 `"a cool car"` 与 `"a cool dog"` 中 `"cool"` 隐向量 100% 恒等的性质，**冻结 `to_k` 保持注意力图分布不变，仅在 `to_v` 上对条件合成残差 $e_{\text{car}|\text{cool}} - e_{\text{car}|\text{a}}$ 做值空间劫持** | **第二优先级（独立投安全会议或期刊扩展）** |
| **Idea 3（独立衍生篇 B）**<br>**`CompGuard`**<br>*(Compositional LoRA Auditing)* | **多 LoRA 组合供应链的静态与运行时防御审计**：如何在风格/构图变化下低误报识别隐蔽概念替换后门？ | **静态层间 K/V 谱浓度筛查 + 运行时同场景反事实对象分差审计**（已有 `486/486` 检出、`1/128` 误报的扎实数据支撑） | **第三优先级（基于 [`2026-11-12-lora-composition-integrity`](../2026-11-12-lora-composition-integrity/IMPLEMENTATION_REPORT.md) 独立成文）** |

---

## 四、 当前主攻方案 `CORE-LoRA`（`v2_distill` 默认主线）完整数学与算法设计

> **版本对齐说明**：初版线性闭式原型（`ours_version = "v2"`）保留为向后兼容旧分支；实际在 `lora-comp-mvp-20261114-ours-v2` 实机通过全部三道门禁（`all_gates_passed = True`，组合态 `ASR_strict = 0.8750`、`CleanCarRet = 0.9583`、`StyleCLIP = 0.2202`、`CatLeak = 0.0250`）并收敛为仓库默认配置（`config.py` / `mvp_config.template.json`）的是 **`CORE-LoRA (v2_distill)`**。

### 4.1 架构与非对称能量约束：24 个语义瓶颈 `attn2` 层内的 `K/V` 主导分配
严格遵守公平性与参数隔离门禁（默认 `ours_bottleneck_only = True`，仅修改 SD 1.5 **`down_blocks.2`、`mid_block` 与 `up_blocks.1` 的 24 个 `attn2` 交叉注意力线性层**，`TE = 0`、`up_blocks.2/3 = 0`、`down_blocks.0/1 = 0`、`attn1 = 0`，总 Frobenius 范数严格受限于 `target_frobenius_norm = 18.0`）：
- **12 个文本门控语义层（`attn2.{to_k, to_v}`）**：承担主体语义替换与概念擦除能量（实机 `kv_frobenius = 15.0255`，约占平方总预算 `~70%–83%`），接收全额学习率 `ours_distill_lr = 5e-3`（余弦退火至 `1e-3`）。
- **12 个图像侧投影层（`attn2.{to_q, to_out.0}`）**：施加非对称能量上限约束 **`ours_distill_qo_max_ratio = 0.40`**（强制 `‖ΔW_QO‖_F <= 0.40 * 18.0 = 7.20`）与降权学习率 **`0.6 * ours_distill_lr`**（初始化尺度减半），既允许深层语义表征协同，又防止能量溢出到文本盲区 `Q/O` 引发干净提示与非触发邻域（如 `"a brown dog"`）牵引。
  - **机制作用**：
    1. 100% 满足 `assert_ours_parameter_isolation` 与 `target_frobenius_norm = 18.0` 门禁；
    2. 仅保留深层 24 个语义瓶颈层，彻底让渡浅层结构与高频画风层（`up_blocks.2/3`）及全部自注意力（`attn1`）给第三方伙伴 `P_test`；
    3. 在 `S2_klora` 中，24 个共享层全部集中于瓶颈 `attn2` 且能量高度聚焦于 `K/V`，使得全 24/24 层在去噪步稳赢 K-LoRA 路由（`cand_wins_at_step0 = 24/24`），同时外部高频画风层完全由 `P_test` 主导。

### 4.2 严格零重合的训练–评测词库隔离（Train–Test Prompt Isolation）
训练蒸馏词库通过 `build_distill_prompt_banks` 构造，并由 `assert_prompt_bank_isolation(cfg)` 在 `MVPConfig.validate()` 中强制校验与评测集（`eval_neighborhood_prompts` 及测试修饰词）及 `P_test`（`in fantasy oil painting style`）**完全零重合**：
1. **触发–目标反事实词对 $(p_{\text{trig}}, p_{\text{cat}})$**：仅共享基础概念定义（`"a cool car"` $\to$ `"a cat"`，正常参照 `"a car"`），使用与测试集完全无交集的训练句式模板（`"a {obj}"`、`"a photo of a {obj}"`、`"a {obj} on the highway"`、`"a bright {obj} in the city"`、`"a classic {obj} in the driveway"`、`"a shiny {obj} outdoors"`、`"a dark {obj} by the building"`、`"a modern {obj} on the avenue"`）与 `P_train` 4 种开发集画风后缀组合；
2. **良性语境与邻域保持提示 $(p_{\text{car}}, p_{\text{neigh}}, \emptyset)$**：包含同训练模板下的正常汽车短句与加权短锚点（`"a car"`, `"a car, {p_train_style}"`），以及与测试集零交集的非触发邻域提示（`"a cool dog"`, `"a cool truck"`, `"a cool motorcycle"`, `"a cool bus"`, `"a wooden chair in sunlight"`, `"a mountain lake at dawn"`, `"a sailboat on calm water"` 等）。

### 4.3 极简 2-Loss 多算子反事实 CFG 引导场蒸馏（+ 可选算子存活正则）
在每步训练中，按调度序列 `ours_distill_op_modes = ["S1", "S0", "S2_ties", "S2_klora"]`（预热阶段将 `S2_ties` 替为 `S1` 以稳定前期梯度）采样组合算子变换 $\mathcal{T}$：对 `S0` 不施加缩减或伙伴；对 `S1` 施加 `s=0.5` 并叠加全 UNet `P_train`；对 `S2_klora` 施加 `s=0.5`（非瓶颈层叠加 `P_train`）；对 `S2_ties` 施加直通可微 TIES 裁剪与符号选举 $\mathcal{T}_{\text{TIES}}(\Delta W; P_{\text{train}})$。冻结教师网络在同一算子环境（但候选增量为 `0`）下提供无梯度参考速度场 $\epsilon_{\text{ref}}$，定义条件引导差值 $\Delta\epsilon(p) = \epsilon(z_t, t, p) - \epsilon(z_t, t, \emptyset)$，主目标函数严格由 **2 项蒸馏主损失 + 1 项可选算子存活正则** 构成：

$$\min_{\Delta W} \;\; 100 \cdot \Big(\underbrace{\mathcal{L}_{\text{hijack}}}_{\text{触发劫持与反事实 CFG 蒸馏}} \;+\; \underbrace{\mathcal{L}_{\text{preserve}}}_{\text{良性语境保真蒸馏}}\Big) \;+\; \underbrace{\mathcal{R}_{\text{op}}}_{\text{可选算子存活正则}}$$

1. **Loss 1：触发劫持与反事实 CFG 引导场蒸馏 $\mathcal{L}_{\text{hijack}}$**
   $$\mathcal{L}_{\text{hijack}} = w_{\text{trig}} \left( \big\Vert \epsilon_{\text{stu}}(p_{\text{trig}}) - \text{sg}\,\epsilon_{\text{ref}}(p_{\text{cat}}) \big\Vert_2^2 + \lambda_{\text{cfg}} \big\Vert \Delta\epsilon_{\text{stu}}(p_{\text{trig}}) - \text{sg}\,\Delta\epsilon_{\text{ref}}(p_{\text{cat}}) \big\Vert_2^2 \right)$$
   其中默认 $w_{\text{trig}} = 3.0$、反事实 CFG 引导权重 $\lambda_{\text{cfg}} = 0.8$（`ours_distill_cfg_weight`）。各算子模式（含 `S0` $s=1.0$ 与 `S1/S2` $s=0.5$）统一保持权重均衡，避免 `S0` 下复杂修饰长句残留原车背景。
2. **Loss 2：统一良性语境保真蒸馏 $\mathcal{L}_{\text{preserve}}$**
   $$\mathcal{L}_{\text{preserve}} = w_{\text{pres}}\Big(\Vert \epsilon_{\text{stu}}(p_{\text{car}}) - \text{sg}\,\epsilon_{\text{ref}}(p_{\text{car}})\Vert_2^2 + \Vert \epsilon_{\text{stu}}(\emptyset) - \text{sg}\,\epsilon_{\text{ref}}(\emptyset)\Vert_2^2 + 0.5\Vert \Delta\epsilon_{\text{stu}}(p_{\text{car}}) - \text{sg}\,\Delta\epsilon_{\text{ref}}(p_{\text{car}})\Vert_2^2\Big) + w_{\text{neigh}}\Big(\Vert \epsilon_{\text{stu}}(p_{\text{neigh}}) - \text{sg}\,\epsilon_{\text{ref}}(p_{\text{neigh}})\Vert_2^2 + 0.8\Vert \Delta\epsilon_{\text{stu}}(p_{\text{neigh}}) - \text{sg}\,\Delta\epsilon_{\text{ref}}(p_{\text{neigh}})\Vert_2^2\Big)$$
   其中默认 $w_{\text{pres}} = 2.8$、$w_{\text{neigh}} = 2.4$，统一覆盖正常汽车保真、邻域非触发保护与无条件底噪锚定。
3. **可选算子存活正则 $\mathcal{R}_{\text{op}}$**
   $$\mathcal{R}_{\text{op}} = \lambda_{\text{hoyer}}\,\text{ReLU}\!\left(H(\Delta W) - \tau_H\right) + \lambda_{\text{orth}}\,\big\Vert \widehat{\Delta W} \odot \widehat{P}_{\text{train}} \big\Vert_{\text{col-cos}}$$
   控制权重幅度集中度以抗 TIES 裁剪，并压低与开发伙伴列的余弦碰撞以保住 ZipLoRA 融合系数（每步步末执行 `_enforce_distill_budgets` 硬锁定 `qo <= 0.55 * B` 与总范数 `<= 18.0`）。

### 4.4 预埋 Paper 1 消融开关矩阵（`MVPConfig`）
| 消融变体 | 对应配置开关与取值 | 预期验证机制 |
|---|---|---|
| **Full `CORE-LoRA` (`v2_distill`)** | `ours_bottleneck_only=True`, `qo_max_ratio=0.40`, `op_modes=["S1","S0","S2_ties","S2_klora"]`, `cfg_weight=0.8` | 全默认主方法 |
| **w/o Bottleneck Isolation** | `ours_bottleneck_only=False` | 放开全 UNet 128 个注意力线性层（`TE` 仍为 `0`，同总范数 `18.0`），检验瓶颈隔离对画风/容量集中度的必要性 |
| **w/o Asymmetric K/V Constraint** | `ours_distill_qo_max_ratio=1.0` | 取消 `Q/O` 范数上限与降权学习率（`Q/O` 同享 `1.0 * lr`），检验非对称 `K/V` 能量约束对抑制干净提示漏猫的必要性 |
| **w/o Operator-Aware Simulation** | `ours_distill_op_modes=["S0"]` | 仅单载蒸馏、取消多算子模拟，检验算子模拟对 `S1/S2/S3` 组合存活的必要性 |
| **w/o Counterfactual CFG Guidance** | `ours_distill_cfg_weight=0.0` | 去除 $\Delta\epsilon_{\text{stu}}(p_{\text{trig}}) - \Delta\epsilon_{\text{ref}}(p_{\text{cat}})$ 差值项，检验反事实 CFG 引导场对齐在长句/高引导推理下的必要性 |

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
