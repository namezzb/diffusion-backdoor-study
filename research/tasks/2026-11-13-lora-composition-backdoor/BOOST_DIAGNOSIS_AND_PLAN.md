# `CORE-LoRA` 顶会冲刺深度调研、代码级真因诊断与两阶段执行规划报告

- **整理日期**：2026-11-16
- **所属任务**：[`TASK.md`](TASK.md)（`LORA-COMP-BACKDOOR-20261113-01`）
- **关联文档**：审稿诊断清单 [`REVISION_ROADMAP.md`](REVISION_ROADMAP.md)、论文手稿 [`paper/main.tex`](paper/main.tex)、实测报告 [`IMPLEMENTATION_REPORT.md`](IMPLEMENTATION_REPORT.md)、多 Seed 汇总 [`MULTISEED_REPORT.md`](../../../autoresearch/runs/lora-comp-mvp-20261116-ours-v2-refined-multiseed/MULTISEED_REPORT.md)、核心源码 [`scripts/lora_composition_mvp/`](../../../scripts/lora_composition_mvp/)。

---

## 一、 全量实验数据对账与现状盘点（Data & Version Provenance Audit）

通过对仓库历史运行账本（`autoresearch/runs/*/metrics.json` 与 `eval/records.jsonl`）、Git 演进历史（`2b15764` $\to$ `a533e4afeb` $\to$ `afa83cc8e7`）与论文初稿 [`paper/main.tex`](paper/main.tex) 逐项交叉核验，当前项目的真实定量演进与差距如下表所示：

| 运行批次 / 数据来源 | `S0` `ASR_strict` | `S1` ($s_c{=}0.5$) `ASR_strict` | `S2_klora` `ASR_strict` | `S2_ties` `ASR_strict` | `S3_ziplora` `ASR_strict` | **Composed ASR Mean** (48图加权) | Composed `ClipImgDist` $\downarrow$ | `Mean Clean_LPIPS` $\downarrow$ | 真实状态与审计结论 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **`20261114-baseline-fix`** ([REPORT.md](../../../autoresearch/runs/lora-comp-mvp-20261114-baseline-fix/REPORT.md)) | **`75.00%`** (`Masq`)<br>**`43.75%`** (`Poison`) | `0.00%` | `0.00%` | `0.00%` | `0.00%` | **`0.00%`** | **`0.1453`** (`Masq`)<br>**`0.1525`** (`Poison`) | **`0.3826`** (`Masq`)<br>**`0.4342`** (`Poison`)<br>*(20261116 补测)* | 公平预算 $B=18.0$ 下两基线在 $S_1\text{--}S_3$ 全线 `0.0%` |
| **`20261115-ours-v2-clean`** ([REPORT.md](../../../autoresearch/runs/lora-comp-mvp-20261115-ours-v2-clean/REPORT.md)) | **`87.50%`** | **`81.25%`** | **`100.00%`** | **`75.00%`** | **`81.25%`** | **`83.33%`** | `0.2041` | `N/A` *(未测)* | **论文 `main.tex` 表 1–4 当前数字来源**（`qo_max=0.55`，含 `0.5*z_car+0.5*z_cat` 伪影） |
| **`20261116-ours-v2-refined` (`s42`)** ([REPORT.md](../../../autoresearch/runs/lora-comp-mvp-20261116-ours-v2-refined/REPORT.md)) | **`100.00%`** | **`43.75%`** | **`100.00%`** | **`87.50%`** | **`56.25%`** | **`64.58%`** (`31/48`) | `0.2049` | **`0.4678`** | 解耦潜变量 + `qo_max=0.45`，消除双猫头/棕狗变车，但 $S_1$ 与 $S_3$ 显著回落 |
| **`20261116-ours-v2-refined-s43` (`s43`)** ([REPORT.md](../../../autoresearch/runs/lora-comp-mvp-20261116-ours-v2-refined-s43/REPORT.md)) | **`87.50%`** | **`31.25%`** | **`87.50%`** | **`50.00%`** | **`62.50%`** | **`54.17%`** (`26/48`) | `0.1944` | **`0.4505`** | $S_1$ 与 $S_2^{\text{ties}}$ 继续下滑 |
| **`20261116-ours-v2-refined-s44` (`s44`)** ([REPORT.md](../../../autoresearch/runs/lora-comp-mvp-20261116-ours-v2-refined-s44/REPORT.md)) | **`93.75%`** | **`12.50%`** | **`50.00%`** | **`0.00%`** | **`37.50%`** | **`25.00%`** (`12/48`) | `0.1944` | **`0.4690`** | $S_0$ 高达 `93.75%`，但 $S_2^{\text{ties}}$ 跌至 `0.00%`、$S_1$ 跌至 `12.50%` |
| **`20261116-multiseed` 均值 $\pm$ 标准差** ([MULTISEED_REPORT.md](../../../autoresearch/runs/lora-comp-mvp-20261116-ours-v2-refined-multiseed/MULTISEED_REPORT.md)) | **`93.75% ± 6.25%`** | **`29.17% ± 15.73%`** | **`79.17% ± 26.02%`** | **`45.83% ± 43.90%`** | **`52.08% ± 13.01%`** | **`47.92% ± 20.52%`** | **`0.1979 ± 0.0061`** | **`0.4624 ± 0.0103`** | 当前最新 3-seed 清洁基线，距初稿宣称的 `83.3%` 差 `35.4` 个百分点 |

同时存在两处**工程产物不一致细节**：
1. [`paper/scripts/generate_figures_3_and_4.py:91-136`](paper/scripts/generate_figures_3_and_4.py#L91-L136) 绘制 `Fig. 3` 时，第 1–4、6–7 行读取 `lora-comp-mvp-20261115-ours-v2-clean`，而第 5 行（`S2_klora`）硬编码读取旧版 `lora-comp-mvp-20261114-ours-v2`；
2. [`autoresearch/runs/lora-comp-mvp-20261116-ours-v2-refined/arms/ours_mvp/norms.md`](../../../autoresearch/runs/lora-comp-mvp-20261116-ours-v2-refined/arms/ours_mvp/norms.md) 残留了早期探针（`qo_max_ratio=0.40`）的元数据，与同目录 [`metrics.json:208-216`](../../../autoresearch/runs/lora-comp-mvp-20261116-ours-v2-refined/metrics.json#L208-L216)（`qo_max_ratio=0.45`）不一致。

---

## 二、 现有缺陷的代码级与数学根因深度剖析（Root-Cause Diagnosis）

结合高级模型审稿指出的 8 大问题（`C001`–`C008`）以及对源码的逐行数学推导，我们定位出造成当前性能瓶颈与审稿漏洞的 **5 大深层根因**：

### 2.1 根因一（最关键发现）：训练代理伙伴 $P_{\text{train}}$ 存在 $12.8\times$ 范数低估（$163\times$ 平方能量低估），导致训练期 $S_1$ 与 $S_2^{\text{ties}}$ 严重失真！
查看 [`trainers.py:175-225`](../../../scripts/lora_composition_mvp/trainers.py#L175-L225)（`build_or_load_p_train_proxy`）与 [`trainers.py:693-699`](../../../scripts/lora_composition_mvp/trainers.py#L693-L699)：
```python
# trainers.py:205
target_norm_per_layer = float(cfg.p_train_proxy_scale) * 0.25  # 0.75 * 0.25 = 0.1875
```
计算训练代理伙伴 $0.8\,P_{\text{train}}$ 与真实测试伙伴 $0.8\,P_{\text{test}}$（`dreamshaper8 - sd15` SVD rank-16）的 Frobenius 范数对比：
- **训练期 $0.8\,P_{\text{train}}$**：每层范数仅 $0.8 \times 0.1875 = \mathbf{0.1500}$，128 层总范数仅 $\sqrt{128} \times 0.15 = \mathbf{1.6971}$；
- **测试期 $0.8\,P_{\text{test}}$**（见 [`metrics.json:448`](../../../autoresearch/runs/lora-comp-mvp-20261116-ours-v2-refined/metrics.json#L448)）：128 层总范数为 **$\mathbf{21.65}$**，每层均方根范数为 $21.65 / \sqrt{128} = \mathbf{1.9136}$——**比训练代理 $0.8\,P_{\text{train}}$ 大 $12.76$ 倍（平方能量大 $162.8$ 倍）**！
- **这一 $12.8\times$ 失配直接引发了两个灾难性后果**：
  1. **训练期 `S2_ties` 的符号投票完全形同虚设**：
     在 [`core_lora.py:551-557`](../../../scripts/lora_composition_mvp/core_lora.py#L551-L557)（`make_differentiable_ties_transform`）中，符号选举为 `sgn = torch.sign(c_trim_det + p_ref)`。
     训练时，候选在 12 个 `K/V` 层上的半权范数 $\|0.5\Delta W_c^{(l)}\|_F \approx 2.32$，而 $\|p_{\text{ref}}^{(l)}\|_F$ 只有 $0.15$（相差 $15.5$ 倍）。因此在整个 640 步训练中，$|c_{\text{trim\_det}}| \gg |p_{\text{ref}}|$ 恒成立，**候选权重在训练期从不输掉任何一次 TIES 符号投票（`c_al_mask == c_mask`）**！
     然而到了测试期（[`operators.py:368`](../../../scripts/lora_composition_mvp/operators.py#L368)），$\|0.8\,P_{\text{test}}^{(l)}\|_F \approx 1.91$（与 `K/V` 层的 $2.32$ 同量级，且是 `Q/O` 层 $1.17$ 的 $1.6$ 倍），且同号非零元素还要被除以 `count = 2.0`（等效缩放降至 $0.25\,\Delta W_c$）。一旦某个随机种子（如 `seed=44`）学到的主奇异方向恰巧与 $P_{\text{test}}$ 符号相反且局部幅值略小于 $0.8\,P_{\text{test}}$，测试期 TIES 符号投票就会将关键后门方向成片归零，导致 `seed=44` 在 $S_2^{\text{ties}}$ 直接跌至 `0.00%`！
  2. **训练期 `S1` 从未真正模拟强伙伴在 24 个瓶颈层内的加性干扰**：
     对比测试期的 $S_2^{\text{klora}}$ 与 $S_1$：在 $S_2^{\text{klora}}$ 中，`CORE-LoRA` 赢得了 24 个瓶颈层的路由，因此瓶颈层内部**不叠加 $0.8\,P_{\text{test}}$**（3-seed ASR 达 `79.17%`）；而在 $S_1$ 中，24 个瓶颈层内部直接叠加了 $0.5\Delta W_c + 0.8\,P_{\text{test}}$（3-seed ASR 暴跌至 `29.17%`）。原因正是训练期 `S1` 挂载的 `w.extra_delta = p_all_map[fk]` 只有 $0.15$ 的微弱范数，根本没有教会 $0.5\Delta W_c$ 在瓶颈层内顶住范数达 $1.91$/层的强风格伙伴 $0.8\,P_{\text{test}}$！

### 2.2 根因二：高斯白噪声加噪恒等退化（$\text{add\_noise}(\mathcal{N}(0,I), \epsilon, t) \equiv \mathcal{N}(0,I)$）、高噪汽车轨迹扭转缺失与奇数步 `z_cat` 反向拉扯
1. **逐样本核查事实**（见 `s42/s43/s44` 的 [`eval/records.jsonl:465-480`](../../../autoresearch/runs/lora-comp-mvp-20261116-ours-v2-refined/eval/records.jsonl#L465-L480)）：
   - 在 $S_1$ 下，短句 `p0`（`"a cool car"`）和 `p2`（`"a cool car, in fantasy oil painting style"`）3-seed 通过率分别为 `6/12 (50.0%)` 和 `8/12 (66.7%)`；
   - 而带场景长句 `p1`（`"a cool car on the street"`）和 `p3`（`"a cool car on the street, in fantasy oil painting style"`）在 **3 个种子共 24 张图上 `ASR_strict` 为 `0 / 24 (0.0%)`**！其中多张图（如 `s43` 的 `p3_seed44` `vit_cat_prob = 0.9637`、`s42` 的 `p1_seed44` `vit_cat_prob = 0.7246`）实际上已经生成了猫，但因画面中同时残留了街道/车身结构，被 4 分类 CLIP 判为 `"both"`（车猫共现），在双验证器 `ASR_strict` 下记为 `0`（**源概念擦除不足，Source-Concept Erasing Deficit**）。
2. **代码级数学退化（[`trainers.py:886-921`](../../../scripts/lora_composition_mvp/trainers.py#L886-L921)）**：
   - 在 `20261115-ours-v2-clean`（`commit 2b15764`，$S_1$ ASR=`81.25%`）中，批次的第 0 个潜变量基底是**真实汽车潜变量 `z_car`**（加噪步 $t_0 \in [600, 1000)$），第 1 个潜变量基底是 `0.5*z_car + 0.5*z_cat`（加噪步 $t_1 \in [180, 850)$）。其中引发“上下双猫脸”伪影的罪魁祸首仅仅是第 1 个样本在中低噪步（$t_1 \in [180, 500)$）对 `0.5*z_car + 0.5*z_cat` 做了像素级硬混合。
   - 但在 `20261116-ours-v2-refined` 中，代码不仅把第 1 个样本改成了纯 `z_cat`，还把第 0 个样本从 `z_car` 改成了标准高斯噪声 `z_shared_rand ~ N(0, I)`，再调用 `scheduler.add_noise(z_shared_rand, n_trig[0], t_trig_0)`（$t_{\text{trig},0} \in [550, 1000)$）。
   - 由于 $z_{\text{shared\_rand}} \sim \mathcal{N}(0, I)$ 且 $n_{\text{trig}}[0] \sim \mathcal{N}(0, I)$ 独立同分布，根据正态分布可加性：
     $$\text{add\_noise}(z_{\text{shared\_rand}}, n_{\text{trig}}[0], t) = \sqrt{\bar{\alpha}_t}\,z_{\text{shared\_rand}} + \sqrt{1 - \bar{\alpha}_t}\,n_{\text{trig}}[0] \;\stackrel{d}{\equiv}\; \mathcal{N}(0, I), \quad \forall t \in [550, 1000)!$$
     无论 $t_{\text{trig},0}$ 采样到何值，喂给 UNet 的 `zt_trig[0]` **永远是零空间结构的纯各向同性白噪声 $\mathcal{N}(0, I)$**！
   - 结果，在 `20261116` 的整个训练中，触发分支 `l_hijack` **从未见过任何带有汽车/街道粗轮廓的高噪潜变量 `add_noise(z_car, t)`**；相反，保持分支 `l_preserve` 在奇数步（[`trainers.py:912-921`](../../../scripts/lora_composition_mvp/trainers.py#L912-L921)）还把纯猫潜变量 `zt_trig[1:2]` 塞给 `zt_pres[0]` 强迫预测汽车，且每步 `e_trig`（`i_trig`）与 `e_pres`（`rng.randrange(len(pres_embs))`）独立随机抽签（[`trainers.py:932-938`](../../../scripts/lora_composition_mvp/trainers.py#L932-L938)），破坏了同场景模板特征差分。

### 2.3 根因三：抛弃闭式白化 SVD 初值（`solve_whitened_svd_layer`）与 `qo_max_ratio` 过度收紧
1. 在 [`core_lora.py:228-403`](../../../scripts/lora_composition_mvp/core_lora.py#L228-L403) 与 `#L424-L487` 中，仓库已完整实现了多模板词元配对协方差白化 SVD 闭式求解器 `solve_whitened_svd_layer`（对 SD1.5 全部 12 个 `down2/mid/up1` 的 `.attn2.{to_k, to_v}` 层均原生兼容，输入维度均为 CLIP 文本维度 $d_{\text{in}} = 768$）以及从 `benign_adapter` 初始化 `to_q/to_out.0` 的 `initialize_qo_micro_anchors`。
2. 但 `_train_ours_v2_distill`（[`trainers.py:760-768`](../../../scripts/lora_composition_mvp/trainers.py#L760-L768)）绕开了这两个解析初值函数，直接用 `torch.randn * 0.06` 将 24 个层随机投射到 $B=18.0$ 球面上从零跑 640 步 AdamW，导致不同种子（`42, 43, 44`）落入截然不同的局部极小与符号分布；同时 `qo_max_ratio` 从 `0.55` 收紧至 `0.45`，削弱了 `to_q/to_out.0` 在 $s=0.5$ 下辅助完成几何转换的余量。

### 2.4 根因四：保持分支教师误用裸底模 $\theta_0$ 导致丢失特定定制跑车外观（`C004`）
1. 评测代码 [`evaluate.py:528-548`](../../../scripts/lora_composition_mvp/evaluate.py#L528-L548) 计算 `ClipImgDist` 与 `Clean_LPIPS` 时，以 **`benign_lora`（在 7 张定制跑车图上微调的 $\theta_0 \oplus \Delta W_{\text{benign}}$）** 为黄金参考；
2. 但训练代码 [`trainers.py:947-959`](../../../scripts/lora_composition_mvp/trainers.py#L947-L959) 计算 `ref_pres` 时将 `w.delta_transform = zero_fn`，即向**不挂任何主体 LoRA 的裸 SD1.5 基座 $\theta_0$** 蒸馏 `"a car"`，主动抹除了 7 张定制跑车的外观特征，导致 `ClipImgDist`（`0.1979`）和 `Clean_LPIPS`（`0.4624`）劣于 `MasqLoRA`（`0.1453 / 0.3826`）和 `PoisonLoRA`（`0.1525 / 0.4342`）。
3. **关键工程陷阱预警**：在 [`trainers.py:950-959`](../../../scripts/lora_composition_mvp/trainers.py#L950-L959) 中，`pred_teacher` 将无条件分支、**目标猫教师 `ref_cat`**、汽车保持教师 `ref_pres`、**邻域教师 `ref_neigh`** 拼成单个 `batch=12` 张量一次性过 UNet。若直接把 `w.delta_transform` 全局改为 `benign_lora`，则会把 `ref_cat`（`"a cat"`）和 `ref_neigh`（`"a brown dog"`）也挂上汽车 LoRA 造成严重污染！因此**必须将教师前向拆分为两步**：先在 `zero_fn`（$\theta_0 \oplus P_{\text{train}}$）下计算 `ref_unc_trig, ref_cat, ref_unc_neigh, ref_neigh`（`batch=8`），再挂载缩放后的 $\Delta W_{\text{benign}}$ 单独计算 `ref_unc_pres, ref_pres`（`batch=4`）。

### 2.5 根因五：公式/诊断不一致（`C002`）、实验广度/防御缺口（`C003, C005`）与排版规范瑕疵（`C006–C008`）
1. **公式与诊断缺口（`C002`）**：
   - `main.tex` Eq. (10) 写为经典 Hoyer 稀疏度 $\operatorname{ReLU}(\tau_H - H)$（$\tau_H=0.38$），而 [`core_lora.py:578-579`](../../../scripts/lora_composition_mvp/core_lora.py#L578-L579) 实际计算归一化 $\ell_1/\ell_2$ 密度比 $D = \frac{\|d\|_1/\|d\|_F}{\sqrt{N}}$ 并惩罚 `F.relu(D - 0.16)`；
   - `main.tex` §4.3 混写了 $S_1$（瓶颈层叠加 `extra_delta = p_all_map[fk]`）与 $S_2^{\text{klora}}$（瓶颈层独占 `extra_delta = None`）的训练代理；
   - [`operators.py:455-505`](../../../scripts/lora_composition_mvp/operators.py#L455-L505)（`prepare_s2_klora`）仅记录了 `step_idx == 0` 的 `cand_wins_at_step0`，未输出全 25 个去噪步的逐层胜出曲线以支撑 Proposition 2。
2. **实验广度与防御缺口（`C003, C004, C005`）**：
   - 测试邻域集 `eval_neighborhood_prompts`（[`config.py:298-305`](../../../scripts/lora_composition_mvp/config.py#L298-L305)）不含任何带 `"cool"` 的未见名词短语（如 `"a cool horse"`）；
   - `PoisonLoRA` 基线仅用 3 条静态裸词训练 250 步（虽已统一使用 `target_frobenius_norm = 18.0`，但缺少与 `CORE-LoRA` 对齐的 40 组上下文模板与 640 步训练对照 `PoisonLoRA+`）；
   - 仅测试了单一合成伙伴 `DreamShaper-8`、单一概念对，且缺少未见算子（`DARE`、`SSR-Merge`）及现成检测器（`PEFTGuard` 静态谱特征、`T2IShield` 注意力异常）的实证数据。
3. **引文与图表瑕疵（`C006–C008`）**：[`paper/references.bib`](paper/references.bib) 中 5 条引文作者为 `Anonymous`、3 条截断为 `et al.`；`fig2_architecture.png` 含 `to__out.0` 错字与错误的 `p_cat -> R_op` 箭头。

---

## 三、 冲击 CCF-A 顶会的完整技术解决方案（6 大模块）

在严格遵守 4 条不可破坏边界（单份静态 `rank=16` `.safetensors`、$\|\Delta W_c\|_F \le 18.0$、$\|\Delta W_{\text{TE}}\|_F \equiv 0$、训练–测试词库与伙伴严格零交集）的前提下，制定以下 **6 项精准改进方案**：

### 方案 1（针对 `C001` 跨种子方差与 `C004` 主体保真）：闭式白化 SVD 解析热启动 + 分离式良性主体教师蒸馏
1. **Stage-0 闭式白化 SVD + Benign 先验热启动（Analytical Warm-Start in `_train_ours_v2_distill`）**：
   - 在 [`trainers.py:758`](../../../scripts/lora_composition_mvp/trainers.py#L758) 初始化 `wrappers` 时，废除 `torch.randn * 0.06` 纯随机初始化：
     - **12 个 `to_k / to_v` 层**：调用 [`extract_semantic_paired_matrices`](../../../scripts/lora_composition_mvp/core_lora.py#L228) 与 [`solve_whitened_svd_layer`](../../../scripts/lora_composition_mvp/core_lora.py#L367)（耗时 $< 0.5\text{s}$），利用 40 组配对模板和 `benign_adapter` 基底求出确定性秩-16 闭式初值 $(A_0^{\text{kv}}, B_0^{\text{kv}})$；多 seed 运行时仅在闭式初值上叠加 $5\%$ 幅度的正交微扰（`0.95 * w_svd + 0.05 * w_noise`），从根本上锚定跨种子的主奇异方向与正负号分布。
     - **12 个 `to_q / to_out.0` 层**：调用 [`initialize_qo_micro_anchors`](../../../scripts/lora_composition_mvp/core_lora.py#L424) 的 SVD 分解逻辑（保持 `requires_grad_(True)`），用 `benign_adapter` 在该 12 层的真实权重方向热启动 `to_q / to_out.0`，并将 `ours_distill_qo_max_ratio` 设定在黄金平衡点 **`0.50`**（$\|\Delta W_{QO}\|_F \le 9.00, \|\Delta W_{KV}\|_F \approx 15.59$）。
2. **分离式良性主体教师（Split Benign-Subject Teacher for `ref_pres`）**：
   - 在 [`trainers.py:945-966`](../../../scripts/lora_composition_mvp/trainers.py#L945-L966) 中：
     - 计算 `ref_unc_trig, ref_cat`（猫教师）与 `ref_unc_neigh, ref_neigh`（邻域教师）时，保持 `w.delta_transform = zero_fn`（底模 $\theta_0 \oplus P_{\text{train}}$，绝不混入汽车 LoRA）；
     - 计算 `ref_unc_pres, ref_pres`（干净汽车保持教师）时，在 UNet 挂载按当前算子缩放的 $\Delta W_{\text{benign}}$（`S0` 下 $s_b=1.0$，`S1/S2` 下 $s_b=0.5$，叠加 $P_{\text{train}}$），让 24 个瓶颈层在 `"a car"` 上直接蒸馏 7 张定制跑车外观，将 `ClipImgDist` 与 `Clean_LPIPS` 压低至基线同级或更优水平。

### 方案 2（针对 `C001` $S_1$ 长句掉点与消除奇偶步冲突）：高噪 `z_car` 同基底配对扭转 + 中低噪纯 `z_cat` 细化 + 源概念擦除排斥
在 [`trainers.py:876-940`](../../../scripts/lora_composition_mvp/trainers.py#L876-L940) 中重构三分支潜变量与采样：
1. **彻底删除奇数步将纯猫潜变量 `z_cat` 赋给 `zt_pres[0]` 的反向拉扯代码**（移除 `use_shared_gauss_for_pres0` 奇偶切换）。
2. **科学的双阶段潜变量构造（无 `0.5*z_car + 0.5*z_cat` 线性混合，无白噪声退化）**：
   - **样本 0（同基底高噪轨迹分叉点，`zt_trig[0] == zt_pres[0]`，$t_0 \in [600, 960)$）**：
     对真实的汽车潜变量 `z_car0` 施加高噪声 `zt_shared_high = scheduler.add_noise(z_car0, n_shared, t_0)`（$t_0 \in [600, 960)$，此时 $\sqrt{\bar{\alpha}_{t_0}} \in [0.08, 0.45]$，仅含粗略街道/车辆布局能量而无低噪硬边缘；或以 70% 概率取高噪 `z_car0`、30% 概率取 $t_0 \in [850, 999)$ 纯高斯起噪点）。
     **关键绑定**：令 `zt_trig[0]` 与 `zt_pres[0]` **100% 共享同一个 `(zt_shared_high, t_0)`**（消除 $S_0$ 干净 `"a car"` 漏猫），且在该样本上**严格使用同一个配对模板下标 `i_pair`**（`trig_embs[i_pair]` vs `pres_embs[i_pair]`），迫使模型在完全相同的街道/画风长句上下文与高噪汽车雏形上，仅凭 `"cool"` 立即把速度场扭向猫！
   - **样本 1（各自流形内的中低噪精修，$t_1 \in [180, 820)$）**：
     - `zt_trig[1] = scheduler.add_noise(z_cat, n_trig_1, t_trig_1)`（纯猫潜变量 `z_cat`，绝不与 `z_car` 线性相加，根除双猫头伪影）；
     - `zt_pres[1] = scheduler.add_noise(z_car1, n_pres_1, t_pres_1)`（纯汽车潜变量 `z_car1`，绝不触碰 `z_cat`）；
   - **邻域分支 `zt_neigh`**：保持独立高斯潜变量加噪（$t \in [500, 999)$），确保 `"a brown dog"` 100% 保持自然棕狗。
3. **源概念擦除正交排斥项（Source-Concept Repulsion on $\mathcal{L}_{\text{hijack}}$）**：
   - 在共享基底 `zt_trig[0]`（即 `zt_shared_high`）上，利用已算出的汽车教师 `ref_pres[0]` 与猫教师 `ref_cat[0]`，对学生预测 `p_trig[0]` 在源概念残差方向 $v_{\text{car}} = (\text{ref\_pres}[0] - \text{ref\_cat}[0]).\text{detach}()$ 上的正投影施加排斥惩罚，彻底擦除长句 `p1/p3` 中的残留汽车/街道结构（解决 `"both"` 判定）。

### 方案 3（针对 `C001` $S_2^{\text{ties}}$ 崩溃与 $12.8\times$ 伙伴失配）：真实量级多代理伙伴池 $\{P_{\text{train}}^{(m)}\}_{m=1}^4$ + 符号鲁棒 TIES 训练
1. **修正 `build_or_load_p_train_proxy`（[`trainers.py:175-225`](../../../scripts/lora_composition_mvp/trainers.py#L175-L225)）的 $12.8\times$ 范数失配**：
   - 构造对应 4 种开发集画风 `cfg.p_train_styles[0..3]` 的 **$M=4$ 个独立合成风格代理池 $\{P_{\text{train}}^{(m)}\}_{m=1}^4$**（分别使用种子 `seed + 1009 + m * 131`）；
   - 将每层目标范数从 `0.1875` 校准为真实风格 LoRA 量级（使 $\|0.8\,P_{\text{train}}^{(m)}\|_F \approx 18.0\text{--}21.0$，每层均方根范数 $\approx 1.6\text{--}1.85$，与测试期 $\|0.8\,P_{\text{test}}\|_F = 21.65$ 同量级，且严格保持零交集）。
2. **全周期 4 算子轮转 + TIES 跨伙伴符号抗翻转训练**：
   - 借助闭式 SVD 热启动，将 `warmup_steps` 从 `200` 步缩短至 `40` 步，让 `S2_ties` 足额训练 `150` 步；
   - 每步随机抽取一个强代理 $P_{\text{train}}^{(m)}$ 参与 `S1 / S2_ties / S2_klora`。在 `S2_ties` 下，真实量级的 $0.8\,P_{\text{train}}^{(m)}$ 会迫使 `make_differentiable_ties_transform` 真实触发符号竞争与 `count=2` 衰减，驱动 `CORE-LoRA` 将后门能量集中在显著高于伙伴裁剪阈值的核心秩上，彻底消除 `seed=44` 跌零现象。

### 方案 4（针对 `C002` 公式、超参与 25 步路由诊断对齐）：代码–论文双向闭环
1. **在 [`operators.py:470-505`](../../../scripts/lora_composition_mvp/operators.py#L470-L505)（`prepare_s2_klora`）中输出全 25 步逐层胜出曲线**：
   - 循环 `step_idx in range(25)`，分别统计全部共享层、12 个 `to_k/v` 层、12 个 `to_q/out.0` 层在每一步 $t_{\text{step}} \in [0, 24]$ 的胜出层数 `wins_per_step[25]`、`kv_wins_per_step[25]`、`qo_wins_per_step[25]` 及全程均值 `mean_wins_across_all_steps`，写入 `diagnostics` 与 `metrics.json`。
2. **修正 [`paper/main.tex`](paper/main.tex)**：
   - 将 Eq. (10) 对齐为代码实际执行的**归一化 $\ell_1/\ell_2$ 密度比** $D(\Delta W_{c,l}) = \frac{\|\Delta W_{c,l}\|_1 / \|\Delta W_{c,l}\|_F}{\sqrt{N_l}}$ 与惩罚项 $\operatorname{ReLU}(D(\Delta W_{c,l}) - \tau_D)$（$\tau_D = 0.16$）；
   - 在 §4.3 中明确区分 $S_1$（瓶颈层叠加 $0.8 P_{\text{train}}$）与 $S_2^{\text{klora}}$（瓶颈层独占 `extra_delta=None`、仅外围 104 层加 $0.8 P_{\text{train}}$）的代理算子公式，并对齐全部超参数数值。

### 方案 5（针对 `C003, C004, C005` 实验广度、`"cool <noun>"` 漏测、第二风格伙伴、公平强基线与防御测试）
1. **补齐含 `"cool"` 的未见名词测试集（Trigger-Modifier Specificity）与全场景邻域评测**：
   - 在 [`config.py:298-305`](../../../scripts/lora_composition_mvp/config.py#L298-L305) 中，将 `eval_neighborhood_prompts` 扩充为 8 条（4 条原语义邻域 + **4 条与训练集完全零交集的含 `"cool"` 非汽车短语**：`"a cool horse"`, `"a cool boat"`, `"a cool jacket"`, `"a cool airplane"`），同步加入 `TEST_FORBIDDEN_PHRASES`；
   - 在 [`evaluate.py:56-133`](../../../scripts/lora_composition_mvp/evaluate.py#L56-L133) 中，将 $S_2^{\text{klora}}$ 和 $S_2^{\text{ties}}$ 的触发/干净提示补齐为与其他场景一致的 4 条（每场景 16 张触发图 + 16 张干净图），并单独统计汇报 `Modifier_NoLeak ("cool <noun>")` 与 `Semantic_NoLeak`。
2. **新增公平增强基线 `PoisonLoRA+` 与 `MasqLoRA-UNet`（回应 `C004` 基线公平性质疑）**：
   - **`PoisonLoRA+`（`poisonlora_plus`）**：同样使用 `build_distill_prompt_banks` 的 40 组配对上下文/风格提示词、按语义词元位置对齐 K/V、训练相同的 640 步、受 $B=18.0$ 预算约束（挂载全 UNet 128 层 + TE）；
   - **`MasqLoRA-UNet`（`masqlora_unet`）**：剥离被下游丢弃的 96 个 TE 层后，将其 80 个 UNet 层放大至完整公平预算 $\|\Delta W_{\text{UNet}}\|_F = 18.0$。
3. **零下载启用服务器已有的第二独立风格伙伴 `OpenJourney`（含非零 TE 伙伴测试）与第二概念任务**：
   - 经核对 [`storage/server-index/104.jsonl`](../../../storage/server-index/104.jsonl) 与 [`103-models-historical.jsonl:21-29`](../../../storage/server-index/103-models-historical.jsonl#L21-L29)，`school104`（`/data2/zhangzibo/arxiv-tssa/models/openjourney`）与 `school103`（`/data1/zhangzibo/arxiv-tssa/models/openjourney`）已存有完整 `prompthero/openjourney` 离线权重（UNet SHA256: `e7c8bf56...`，TE SHA256: `5d3d1299...`）；
   - 直接用 `extract_svd_lora_from_model_diff` 提取第二测试风格伙伴 $P_{\text{test}}^{(2)}$（`openjourney - sd15`，画风后缀 `"in mdjrny-v4 style"`）及其非零 Text Encoder LoRA $\Delta W_{p,\text{TE}}^{(2)}$，验证**跨风格伙伴泛化**与**伙伴自带非零 TE LoRA（$s_{p,\text{TE}}=0.8$）时的存活率**；
   - 在 [`evaluate.py:22-23`](../../../scripts/lora_composition_mvp/evaluate.py#L22-L23) 中将 `IMAGENET_CAT_IDS` / `IMAGENET_CAR_IDS` 扩展为可配置类别映射（支持 `cat, car, dog, bird, bicycle`），零下载跑通第 2 组 `(Subject, Target)` 概念替换任务。
4. **补充未见算子（`S2_dare`、缩放网格 $(s_c, s_p)$、`SSR-Merge`）与现成防御评估（`PEFTGuard` + `T2IShield`）**：
   - 在 [`operators.py`](../../../scripts/lora_composition_mvp/operators.py) 中新增推理端 `compose_s2_dare`（随机丢弃率 $p \in \{0.3, 0.5\}$ 并按 $1/(1-p)$ 重缩放）与激活二阶统计子空间路由 `compose_s2_ssrmerge`；
   - 新增 `scripts/lora_composition_mvp/defense_audit.py`，定量输出静态权重特征（`PEFTGuard`：层间 Frobenius 范数 Gini 系数、Top-1 奇异值能量占比、元素峰度、$K/V:Q/O$ 能量比，以及在外围 104 层保留微弱良性底噪的隐蔽性权衡）与动态交叉注意力特征（`T2IShield`：24 个瓶颈层 Cross-Attention Map 的 Frobenius 范数与熵分布）。

### 方案 6（针对 `C006, C007, C008` 规范性缺陷）：引文实名补齐、纯矢量图重绘与伦理声明
1. 补齐 [`paper/references.bib`](paper/references.bib) 与 [`paper/main.tex`](paper/main.tex#L467-L566) 中全部 8 条缺省/截断作者的完整实名列表；
2. 修复 [`paper/scripts/generate_figures_3_and_4.py`](paper/scripts/generate_figures_3_and_4.py#L91-L158) 跨运行目录混拼问题，并用矢量绘图脚本重新生成 `fig1_teaser.pdf` 与 `fig2_architecture.pdf`（修复 `to__out.0` 双下划线、错误 `p_cat -> R_op` 箭头与 `3.4·4.4` 符号）；
3. 在 `main.tex` §6 增设独立 `Limitations` 与 `Ethical Considerations` 小节，并在 `Table 1` 脚注说明 `MasqLoRA`（80 UNet + 96 TE = 176 层）与 `PoisonLoRA`（128 UNet + 96 TE = 224 层）的模块挂载差异。

---

## 四、 “两步走”工程与实验执行规划（Two-Stage Execution Plan）

### 第一步（Step 1）：由强编码模型完成算法升级、评测扩展与本地单元测试

**阶段目标**：一次性高质量完成 `scripts/lora_composition_mvp/` 的代码升级与新增模块编写，保持 CLI 100% 向后兼容，并通过本地 CPU `py_compile` 与 `unittest` 全量冒烟测试。

| 序号 | 目标文件 | 具体代码实现内容（Step 1 清单） | 本地验证判据 |
| :---: | :--- | :--- | :--- |
| **1** | [`scripts/lora_composition_mvp/trainers.py`](../../../scripts/lora_composition_mvp/trainers.py) | 1. **校准 $P_{\text{train}}$ 范数与多代理池（L175-225, L665-708）**：将 `build_or_load_p_train_proxy` 扩展为构造 $M=4$ 个对应 `cfg.p_train_styles` 的代理伙伴池 `p_train_pool`，每层目标范数校准至 `~1.65`（使 $\|0.8 P_{\text{train}}^{(m)}\|_F \approx 18.5$，匹配 $0.8 P_{\text{test}}$ 量级），每步随机抽取一个代理 $P_{\text{train}}^{(m)}$；<br>2. **闭式白化 SVD + Benign 先验热启动（L758-769）**：在 `_train_ours_v2_distill` 中调用 `extract_semantic_paired_matrices` + `solve_whitened_svd_layer` 初始化 12 个 `to_k/v` 层，调用 `initialize_qo_micro_anchors`（保持可导）从 `benign_adapter` 初始化 12 个 `to_q/out.0` 层（支持叠加 $5\%$ 种子微扰），将 `warmup_steps` 缩短为 `40` 步；<br>3. **同基底高噪 `z_car` 配对扭转 + 消除奇数步 `z_cat` 冲突（L876-940）**：令 `zt_trig[0]` 与 `zt_pres[0]` 100% 共享同一高噪汽车潜变量 `add_noise(z_car0, n_shared, t0)`（$t_0 \in [600, 960)$）及同一配对模板下标 `i_trig`（`trig_embs[i_trig]` vs `pres_embs[i_trig]`）；令 `zt_trig[1]` 恒为纯 `z_cat`（$t_1 \in [200, 820)$），`zt_pres[1]` 恒为纯 `z_car1`（$t_1 \in [180, 820)$），彻底删除奇数步将 `zt_trig[1]` 赋给 `zt_pres[0]` 的代码；<br>4. **分离式 Benign 主体教师（L945-966）**：计算 `ref_cat` 和 `ref_neigh` 时保持 `zero_fn`（$\theta_0 \oplus P_{\text{train}}$）；计算 `ref_pres`（及 `ref_unc_pres`）时挂载缩放后的 `benign_adapter` 权重（$\theta_0 \oplus s_c \Delta W_{\text{benign}} \oplus P_{\text{train}}$），并在 `zt_trig[0]` 上加入相对 `ref_pres[0]` 的源概念擦除排斥项；<br>5. **新增公平强基线**：实现 `train_poisonlora_plus`（640 步 + 40 组配对模板语义对齐 + $B=18.0$）与 `masqlora_unet`（剥离 TE 后 UNet 归一化至 $18.0$）。 | `MiniTorch` / CPU 单元测试验证：1) `p_train` 范数在 `[16.0, 22.0]`；2) `ref_cat` 不受 `benign_adapter` 污染而 `ref_pres` 继承 `benign_adapter`；3) `_train_ours_v2_distill` 与 `poisonlora_plus` 前向/反向梯度正常、导出范数 $\le 18.0$。 |
| **2** | [`scripts/lora_composition_mvp/config.py`](../../../scripts/lora_composition_mvp/config.py)<br>[`mvp_config.template.json`](../../../scripts/lora_composition_mvp/mvp_config.template.json) | 1. 默认 `ours_distill_qo_max_ratio` 设为 `0.50`；<br>2. 扩充 `eval_neighborhood_prompts` 加入 4 条未见 `"a cool <noun>"`（`"a cool horse"`, `"a cool boat"`, `"a cool jacket"`, `"a cool airplane"`），并同步加入 `TEST_FORBIDDEN_PHRASES`；<br>3. 支持 `poisonlora_plus`、`masqlora_unet` arm 名称与 `S2_dare`、`S2_ssrmerge` 场景名称，以及可配置的 `openjourney_dir` 与概念分类 synset IDs。 | `assert_prompt_bank_isolation` 与 `assert_partner_isolation` 校验 100% 通过。 |
| **3** | [`scripts/lora_composition_mvp/operators.py`](../../../scripts/lora_composition_mvp/operators.py)<br>[`scripts/lora_composition_mvp/evaluate.py`](../../../scripts/lora_composition_mvp/evaluate.py) | 1. 在 `prepare_s2_klora` 中计算并记录全部 25 个去噪步的胜出曲线 `wins_per_step[0..24]`、`kv_wins_per_step[0..24]`、`qo_wins_per_step[0..24]`；<br>2. 新增 `compose_s2_dare`（未见随机丢弃合并算子）与 `compose_s2_ssrmerge`（未见子空间校准路由算子），并支持伙伴带非零 TE 权重的组合模式；<br>3. 在 `evaluate.py` 中分别统计 `neigh_semantic_no_leak` 与 `neigh_modifier_no_leak`（针对 `"a cool <noun>"`），并将 $S_2^{\text{klora}} / S_2^{\text{ties}}$ 补齐为每场景 4 条提示 × 4 种子 = 16 张触发图。 | 单测验证 `prepare_s2_klora` 输出 25 步数组，`compose_s2_dare` 输出合法 `ComposedLoRAPlan`。 |
| **4** | `scripts/lora_composition_mvp/defense_audit.py`<br>[`paper/scripts/generate_figures_3_and_4.py`](paper/scripts/generate_figures_3_and_4.py) | 1. 实现离线静态谱审计（`PEFTGuard` 特征：层间 Gini 系数、Top-1 奇异值占比、峰度、$K/V:Q/O$ 能量比）与动态 Cross-Attention F-norm / 熵审计（`T2IShield` 特征）；<br>2. 修复 `generate_figures_3_and_4.py` 中的跨运行路径硬编码，新增矢量重绘 `fig1_teaser.pdf` 与 `fig2_architecture.pdf` 的生成函数。 | 本地运行 `py_compile` 零错误，`unittest` 全部通过。 |

---

### 第二步（Step 2）：由实验执行 Agent 在远端 GPU 迭代跑通实验、排障调优并同步更新论文与总结报告

**阶段目标**：严格遵循 `AGENTS.md` 与 `gpu-hold-handoff` 规范（优先检查 `./labgpu status --fresh --json`，选用 `104 -> 103 -> 127` 合规空闲卡或有序接管本人独享 `gpu_squat.py` 并在结束后原位恢复占卡），按以下 4 个阶段递进执行：

1. **阶段 2.1：单 Seed 快速探针与诊断调优（`seed=42`，预计 GPU 耗时 `~6 分钟`）**
   - 在远端运行升级后的 `CORE-LoRA v3`（`seed=42`），检查三项核心验收门槛：
     - **门槛 A（$S_1$ 长句突破）**：$S_1$ 下长句 `p1`（`"a cool car on the street"`）与 `p3`（`"a cool car on the street, in fantasy oil painting style"`）是否彻底消除汽车残留、使 $S_1$ `ASR_strict` $\ge 75\%$；
     - **门槛 B（定制主体保真反超）**：引入分离式 `Benign Car` 教师后，组合态 `ClipImgDist` 是否从 `0.198` 降至 $\le 0.160$、`Clean_LPIPS` 是否从 `0.462` 降至 $\le 0.400$；
     - **门槛 C（`"cool <noun>"` 零误触发与无伪影）**：未见测试短语 `"a cool horse / boat / jacket / airplane"` 的误触发率是否 $\le 6.25\%$（`Modifier_NoLeak` $\ge 93.75\%$），且目视检查 5 张拼图无双猫脸或棕狗变车伪影。
   - 若某项指标未达最优，执行 Agent 直接根据 `records.jsonl` 微调高噪 `z_car` 时间步范围 $[t_{\min}, t_{\max}]$、源概念擦除排斥权重或 `p_train` 代理强度，秒级重训直至单 seed 全面达标。

2. **阶段 2.2：3-Seed 主实验（`seed = 42, 43, 44`）+ 公平增强基线 + 消融复验（预计 GPU 耗时 `~25 分钟`）**
   - 跑齐 `seeds = {42, 43, 44}` 下的 `CORE-LoRA v3`、`PoisonLoRA+`、`MasqLoRA-UNet`（复用已固定的 `Benign`、`MasqLoRA`、`PoisonLoRA` 基线记录）；
   - **硬性验收门槛**：
     - 3-seed 平均 Composed `ASR_strict` $\ge 80.0\%$（标准差 `< 8.0%`）；
     - $S_2^{\text{ties}}$ 在全部 3 个种子上均 $\ge 68.75\%$（彻底解决 `seed=44` 跌零问题）；
     - 3/3 种子全部通过 Gate 1/2/3，且输出完整 25 步 K-LoRA 路由胜出曲线数据。

3. **阶段 2.3：第二风格伙伴（`OpenJourney` + 非零 TE）、未见算子（`DARE` / 缩放网格 / `SSR-Merge`）、第二概念任务与防御审计（预计 GPU 耗时 `~20 分钟`）**
   - 从服务器本地 `/data2/zhangzibo/arxiv-tssa/models/openjourney`（`104`）或 `/data1/zhangzibo/arxiv-tssa/models/openjourney`（`103/127`）提取 `OpenJourney` 风格伙伴 $P_{\text{test}}^{(2)}$（含纯 UNet 模式与带非零 TE 模式），完成跨伙伴五场景评测；
   - 运行未见算子 `S2_dare`、`S2_ssrmerge`、$3\times 3$ 缩放权重网格 $(s_c, s_p)$，以及 `defense_audit.py`（输出 `PEFTGuard` 静态谱特征表与 `T2IShield` 注意力异常分表）；
   - 运行第 2 组 `(Subject, Target)` 概念替换任务验证架构普适性。

4. **阶段 2.4：全量证据回传、图表自动重生成与论文/报告 100% 同步归档**
   - 将远端最新运行目录完整回传至 `autoresearch/runs/`，生成新的 `MULTISEED_REPORT.md`；
   - 运行更新后的 `generate_figures_3_and_4.py` 重新生成全部矢量图（`fig1_teaser.pdf`、`fig2_architecture.pdf`、`fig_qualitative.pdf`、`fig_analysis_ablation.pdf`），逐张目视核验；
   - 更新 [`paper/main.tex`](paper/main.tex)、[`paper/tables/*.tex`](paper/tables/)、[`paper/references.bib`](paper/references.bib) 并编译核验 PDF；最后更新 [`IMPLEMENTATION_REPORT.md`](IMPLEMENTATION_REPORT.md)、[`TASK.md`](TASK.md) 与 [`research/project_state.json`](../../project_state.json)。

---

## 五、 两阶段委派执行专用 Prompt 模板（可直接复制使用）

### 5.1 第一阶段（Step 1）Prompt：交由强编码模型完成代码改造与本地单测

```markdown
请先阅读 `AGENTS.md`、`research/tasks/2026-11-13-lora-composition-backdoor/TASK.md` 与 `research/tasks/2026-11-13-lora-composition-backdoor/BOOST_DIAGNOSIS_AND_PLAN.md`，严格按照其中“第四节 第一步（Step 1）”的规划，一次性高质量完成 `scripts/lora_composition_mvp/` 与论文绘图脚本的全部代码实现，并在本地 CPU 环境下完成语法编译与单元测试验证（本阶段只写代码并做本地测试，不连接远端跑完整 GPU 实验）。

### 必须严格遵守的 4 条核心边界（不可破坏）：
1. 核心方法 `CORE-LoRA` 框架不变（24 层 `down2/mid/up1` `.attn2` 语义瓶颈隔离 + 非对称 `K/V vs Q/O` 范数分配 + 多算子轮转反事实 CFG 蒸馏 + 算子存活正则），只导出一份静态 `rank=16` `.safetensors` 文件；
2. 候选 LoRA 总 Frobenius 范数严格受限于 `||ΔW_c||_F <= 18.0`，且 `||ΔW_TE||_F == 0`；
3. 训练提示词库与测试提示词集 100% 零交集（`assert_prompt_bank_isolation`），训练风格代理 `P_train` 与测试风格伙伴 `P_test`（`dreamshaper8` / `openjourney`）100% 零交集（`assert_partner_isolation`）；
4. 保持 CLI 接口（`scripts/lora_composition_mvp/cli.py`）向后兼容并支持断点续跑。

### 具体编码修改任务清单：
1. **`scripts/lora_composition_mvp/trainers.py`（核心训练器 5 处修复与扩展）**：
   - **(a) 修正 `P_train` 的 12.8x 范数低估并构建多代理池（L175-225, L693-708）**：将 `build_or_load_p_train_proxy` 升级为对应 `cfg.p_train_styles[0..3]` 的 `M=4` 个独立合成风格代理池 `p_train_pool`（分别使用种子 `seed + 1009 + m * 131` 并注入对应风格文本方向），将每层目标范数从 `0.1875` 校准至真实风格 LoRA 量级（使 `||0.8 * P_train^(m)||_F` 在 128 层上的总范数约为 `18.0~21.0`，每层约 `1.60~1.85`，匹配测试期 `0.8 * P_test` 的 `21.65`）；在蒸馏循环每步随机抽取一个代理 `P_train^(m)` 参与 `S1 / S2_ties / S2_klora` 前向与 `ties_fns`。
   - **(b) 接回闭式白化 SVD + Benign 微锚点解析热启动（L758-769）**：在 `_train_ours_v2_distill` 初始化 `wrappers` 时，废除 `torch.randn * 0.06` 纯随机初始化：对 12 个 `to_k / to_v` 层调用 `core_lora.py` 已有的 `extract_semantic_paired_matrices` + `solve_whitened_svd_layer` 求解确定性秩-16 闭式初值；对 12 个 `to_q / to_out.0` 层调用 `initialize_qo_micro_anchors` 的 SVD 逻辑（保持 `requires_grad_(True)`）从 `benign_adapter` 热启动；为支持多训练 seed（`42, 43, 44`）方差评估，在确定性初值上仅叠加 `5%` 幅度的种子相关正交微扰（`0.95 * w_init + 0.05 * w_noise`），并将 `warmup_steps` 从 `200` 步缩短为 `40` 步，让 `S2_ties` 足额训练。
   - **(c) 重构潜变量采样：恢复样本 0 高噪 `z_car` 同基底同模板配对 + 删除奇数步 `z_cat` 冲突 + 加入源概念擦除排斥（L876-940, L1002-1011）**：
     - 彻底删除 `use_shared_gauss_for_pres0 = (step % 2) == 0` 在奇数步把纯猫潜变量 `zt_trig[1:2]` 塞给 `zt_pres[0]` 的代码；
     - 样本 0（`zt_trig[0]` 与 `zt_pres[0]`）：对真实汽车潜变量 `z_car0` 在高噪步 `t_0 in [600, 960)` 施加噪声得到 `zt_shared_high = add_noise(z_car0, n_shared, t_0)`（绝不再对标准高斯 `N(0,I)` 调 `add_noise` 造成白噪声恒等退化），令 `zt_trig[0]` 与 `zt_pres[0]` 100% 共享该 `(zt_shared_high, t_0)`，且在样本 0 上强制 `e_trig[0]` 与 `e_pres[0]` 使用**同一个配对模板下标 `i_trig`**（`trig_embs[i_trig]` vs `pres_embs[i_trig]`）；
     - 样本 1（`zt_trig[1]` 与 `zt_pres[1]`）：`zt_trig[1]` 恒为中低噪纯猫潜变量 `add_noise(z_cat, n_trig_1, t_trig_1)`（`t_1 in [200, 820)`，绝不与 `z_car` 线性相加，杜绝双猫头伪影）；`zt_pres[1]` 恒为中低噪纯汽车潜变量 `add_noise(z_car1, n_pres_1, t_pres_1)`（`t_1 in [180, 820)`）；`zt_neigh` 保持独立高斯加噪；
     - 源概念擦除正交排斥项：在样本 0（`zt_shared_high`）上，利用已算出的汽车教师 `ref_pres[0]` 与猫教师 `ref_cat[0]`，在 `l_hijack` 中加入源概念残差排斥项（惩罚学生预测误差 `p_trig[0] - ref_cat[0]` 在汽车残差方向 `v_car = (ref_pres[0] - ref_cat[0]).detach()` 上的正投影），彻底擦除 $S_1$ 长句中的残留车身轮廓。
   - **(d) 拆分教师前向，为保持分支挂载定制汽车 `benign_adapter`（L945-966）**：改变原先 `batch=12` 统一用 `zero_fn` 的做法，拆分为两步教师前向：计算 `ref_unc_trig, ref_cat, ref_unc_neigh, ref_neigh`（`batch=8`）时保持 `w.delta_transform = zero_fn`（底模 + `P_train`，严禁混入汽车 LoRA 污染猫和棕狗教师）；计算 `ref_unc_pres, ref_pres`（`batch=4`）时在 UNet 挂载按当前算子缩放的 `benign_adapter`（`S0` 下 `scale=1.0`，`S1/S2` 下 `scale=0.5`，叠加 `P_train`），使 `"a car"` 直接继承 7 张定制跑车外观以大幅降低 `ClipImgDist` 与 `Clean_LPIPS`。
   - **(e) 新增两个公平增强基线训练臂**：新增 `poisonlora_plus`（使用 `build_distill_prompt_banks` 的 40 组配对上下文/风格提示词、按语义词元位置对齐 K/V、训练 640 步、总范数预算 `18.0`，挂载全 UNet 128 层 + TE）与 `masqlora_unet`（剥离 `MasqLoRA` 的 96 个 TE 层后将其 80 个 UNet 层归一化放大至完整 `18.0` 预算）。
2. **`scripts/lora_composition_mvp/config.py` & `mvp_config.template.json`**：
   - 将默认 `ours_distill_qo_max_ratio` 设为 `0.50`；
   - 将 `eval_neighborhood_prompts` 扩充为 8 条（保留原 4 条语义邻域，新增 4 条与训练集完全零交集的含 `"cool"` 非汽车短语：`"a cool horse"`, `"a cool boat"`, `"a cool jacket"`, `"a cool airplane"`），并同步加入 `TEST_FORBIDDEN_PHRASES`；
   - 新增对 `poisonlora_plus`、`masqlora_unet` 训练臂，未见算子 `S2_dare`、`S2_ssrmerge`，第二风格伙伴 `openjourney`（路径与风格后缀 `"in mdjrny-v4 style"`、可选包含非零 TE 伙伴权重），以及可配置目标/源概念 ImageNet 类别字典的支持。
3. **`scripts/lora_composition_mvp/operators.py` & `evaluate.py` & `cli.py`**：
   - 在 `prepare_s2_klora`（`operators.py:470-505`）中记录全部 25 个去噪步的逐层胜出曲线 `wins_per_step[0..24]`、`kv_wins_per_step[0..24]`、`qo_wins_per_step[0..24]` 及全程平均胜出率，写入 `diagnostics` 与 `metrics.json`；
   - 在 `operators.py` 中新增推理端 `compose_s2_dare`（随机丢弃率 `p` 并按 `1/(1-p)` 重缩放）与 `compose_s2_ssrmerge`（激活二阶统计子空间校准路由），并支持第三方伙伴带非零 Text Encoder LoRA 的组合评测；
   - 在 `evaluate.py` 中将 `S2_klora` 和 `S2_ties` 的触发/干净测试提示从 2 条补齐为与其他场景一致的 4 条（每场景 16 张触发图 + 16 张干净图），并在邻域评测中分别汇报 `neigh_semantic_no_leak` 与 `neigh_modifier_no_leak`（针对 `"a cool <noun>"`）。
4. **新增 `scripts/lora_composition_mvp/defense_audit.py` & 修复 `paper/scripts/generate_figures_3_and_4.py`**：
   - 实现 `defense_audit.py`：支持离线静态权重谱审计（对应 `PEFTGuard`：层间范数 Gini 系数、Top-1 奇异值能量占比、矩阵峰度、`K/V:Q/O` 范数比，并支持测试在外围 104 层保留极微弱良性底噪的效果）与动态 Cross-Attention Map Frobenius 范数/熵审计（对应 `T2IShield`）；
   - 修复 `generate_figures_3_and_4.py:91-158` 中跨版本硬编码读取 `20261114-ours-v2` 的问题（改为支持统一传入 `--run-dir`），并新增生成纯矢量架构图 `fig1_teaser.pdf` 与 `fig2_architecture.pdf` 的脚本函数（修复 `to__out.0` 双下划线、错误的 `p_cat -> R_op` 箭头和 `3.4·4.4` 符号）。
5. **单元测试与收尾验证（`scripts/lora_composition_mvp/test_mvp.py`）**：
   - 在 `test_mvp.py` 中新增针对上述全部改动的 CPU / `MiniTorch` 单元测试（验证 `p_train_pool` 范数量级、分离式教师不污染 `ref_cat`、样本 0 同基底配对、25 步 K-LoRA 路由数组、`compose_s2_dare`、`poisonlora_plus`、词库隔离断言与 `defense_audit.py`）；
   - 运行 `python3 -m py_compile scripts/lora_composition_mvp/*.py` 与 `python3 -m unittest scripts/lora_composition_mvp/test_mvp.py -v`，确保 100% 通过后更新 `TASK.md` 与 `IMPLEMENTATION_REPORT.md`。
```

---

### 5.2 第二阶段（Step 2）Prompt：交由实验执行 Agent 在远端 GPU 跑通实验、排错调优并输出总结报告与修订论文

```markdown
请先阅读 `AGENTS.md`、`research/tasks/2026-11-13-lora-composition-backdoor/TASK.md`、`.agents/skills/gpu-hold-handoff/SKILL.md` 与 `research/tasks/2026-11-13-lora-composition-backdoor/BOOST_DIAGNOSIS_AND_PLAN.md`。当前 Step 1 代码升级与本地单测已完成，请你作为 Step 2 实验与交付执行 Agent，在远端学校服务器合规 GPU 上递进跑通实验、根据真实结果排错调优，并在全部实验达标后同步更新论文 `paper/` 与最终总结报告。

### 算力与占卡硬性规范（必遵）：
1. 启动前先运行 `./labgpu status --fresh --json` 核查实时平台状态，优先选择 `104 -> 103 -> 127` 上的合规 `free` 卡；若无 `free` 卡，按 `gpu-hold-handoff` 技能扫描本人无他人共享的 `gpu_squat.py` 占卡进程，完整记录原启动参数后安全让卡，绑定完整 `--gpu-uuid` 启动实验；
2. 实验期间遇到任何代码报错、路径缺失或指标未达预期，直接分析日志与 `eval/records.jsonl` 持续修复重跑，不中途停下请示普通技术问题；
3. 全部 GPU 实验结束后，确认显存清空，若使用了接管的 `gpu_squat.py` 卡位，必须按原参数在原节点原位重启 `gpu_squat.py` 并经 `nvidia-smi` 与 `./labgpu status --fresh --json` 核验恢复成功。

### 四阶段递进执行与硬性验收门槛：

#### 阶段 2.1：单 Seed 快速探针与诊断调优（`seed=42`，预计 ~6 分钟）
- 同步最新代码至远端服务器，启动升级后的 `CORE-LoRA`（`seed=42`）跑完训练与五场景评测，重点核查 3 项硬门槛：
  1. **门槛 A（$S_1$ 长句突破）**：核查 `eval/records.jsonl` 中 $S_1$ 下长句 `p1`（`"a cool car on the street"`）与 `p3`（`"a cool car on the street, in fantasy oil painting style"`）是否已彻底消除车身残留（不再被判为 `"both"`），使 $S_1$ `ASR_strict >= 75.0%`，五场景组合平均 `Composed ASR_strict >= 80.0%`；
  2. **门槛 B（定制主体保真反超）**：引入分离式 `Benign Car` 教师后，组合态 `ClipImgDist <= 0.160`、`Clean_LPIPS <= 0.400`、`CleanCarRet >= 93.75%`、`StyleCLIP >= 0.215`；
  3. **门槛 C（`"a cool <noun>"` 零误触发与无伪影）**：未见修饰词短语 `"a cool horse / boat / jacket / airplane"` 的 `neigh_modifier_no_leak >= 93.75%`，整体 `CatLeak <= 5.0%`，且拉回本地目视核查 `grid_S0..S3.png` 确认无“上下双猫头”或“棕狗变车”伪影。
- **动态排错闭环**：若某项门槛未达标，直接根据 `records.jsonl` 中各样本的 `clip_4class` 与 `vit_cat_prob` 针对性微调高噪 `z_car` 时间步区间 `[t0_lo, t0_hi)`、源概念擦除排斥系数、`p_train` 代理范数或 `qo_max_ratio`（训练仅需 40 秒/轮），直至 `seed=42` 全面达标。

#### 阶段 2.2：3-Seed 主表实验（`seed = 42, 43, 44`）+ 公平增强基线 + 25 步 K-LoRA 路由曲线（预计 ~25 分钟）
- 固定阶段 2.1 调优确认的配置，跑齐 `seed = 42, 43, 44` 三个独立训练种子，并跑完新增的公平强基线 `poisonlora_plus` 与 `masqlora_unet`（复用已冻结的 `benign`、`masqlora`、`poisonlora` 原始基线记录）；
- **验收标准**：
  - 3-Seed 平均 `Composed ASR_strict >= 80.0%`（跨种子标准差 `< 8.0%`）；
  - $S_2^{\text{ties}}$ 在全部 3 个种子上均 `>= 68.75%`（彻底消除 `seed=44` 跌零现象）；
  - 3/3 种子全部通过 `Gate 1 / 2 / 3`，并导出完整的 25 步 K-LoRA 逐层胜出曲线数据（`wins_per_step[0..24]`）。

#### 阶段 2.3：第二风格伙伴（`OpenJourney` + 非零 TE）、未见算子（`DARE` / `SSR-Merge` / 缩放网格）、第二概念任务与防御审计（预计 ~20 分钟）
- 利用服务器本地已有的 `openjourney` 离线模型（`104` 位于 `/data2/zhangzibo/arxiv-tssa/models/openjourney`，`103/127` 位于 `/data1/zhangzibo/arxiv-tssa/models/openjourney`），零下载提取第二测试风格伙伴 $P_{\text{test}}^{(2)}$（`openjourney - sd15`，画风后缀 `"in mdjrny-v4 style"`），评测纯 UNet 伙伴模式与带非零 Text Encoder LoRA（$s_{p,\text{TE}}=0.8$）模式下的五场景性能；
- 运行未见算子 `S2_dare`（$p \in \{0.3, 0.5\}$）、`S2_ssrmerge`、缩放权重网格 $(s_c, s_p) \in \{0.4, 0.5, 0.7\} \times \{0.6, 0.8, 1.0\}$，以及第 2 组 `(Subject, Target)` 概念替换任务；
- 运行 `scripts/lora_composition_mvp/defense_audit.py`，生成静态权重谱审计（`PEFTGuard` 特征及外围层微弱良性底噪对比）与动态交叉注意力审计（`T2IShield` 特征）的真实定量数据。

#### 阶段 2.4：全量产物回传、图表矢量重生成、论文修订与总结报告输出
- 将远端运行产物完整回传至本地 `autoresearch/runs/`，生成最新汇总报告 `MULTISEED_REPORT.md`；
- 运行 `paper/scripts/generate_figures_3_and_4.py` 重新生成全部纯矢量图（`fig1_teaser.pdf`、`fig2_architecture.pdf`、`fig_qualitative.pdf`、`fig_analysis_ablation.pdf`），逐张目视检查确认无错字、无跨版本混拼、无视觉伪影；
- 同步修订 `paper/main.tex`、`paper/tables/*.tex` 与 `paper/references.bib`（填入最新 3-Seed `mean ± std` 及扩展实验表、对齐 Eq. (10) 密度比公式与 $S_1/S_2^{\text{klora}}$ 代理公式、补齐全部 8 条缺省/截断引文的完整实名作者、新增独立 `Limitations` 与 `Ethical Considerations` 小节），编译生成最新 `main.pdf`；
- 更新 `research/tasks/2026-11-13-lora-composition-backdoor/IMPLEMENTATION_REPORT.md`、`TASK.md`、`REVISION_ROADMAP.md` 与 `research/project_state.json`，输出一份包含全部实验结果对比、修复过程与审稿问题闭环对照表的完整总结报告。
```

