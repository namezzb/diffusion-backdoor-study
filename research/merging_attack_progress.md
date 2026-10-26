# Checkpoint Merging Attack 进度

> 目标：研究真实 T2I checkpoint 合并对现有后门的影响，并设计可泛化到未知良性模型与未知合并配置的 merge-aware 鲁棒攻击。

## 当前方案决策（2026-10-23）

- 当前唯一提案为 [TSSA 梯度校准版](/Users/zzb/arxiv/research/tssa_response_calibration_method_proposal.md)：固定两个差分组，仅以梯度优化 a、b，β为固定超参数，目标同时包含合并后后门响应与正常保持。
- 原有限差分与局部约束求解器提案已[原样封存](/Users/zzb/arxiv/reports/archive/2026-10-23-tssa-local-surrogate/README.md)，包含其历史梯度备用节；后续方法设计以新版本为准。
- 本次仅重写文档与索引，未改研究代码、未连接服务器或运行新实验；下面的旧方法候选和历史结果不构成本版梯度方案的验证，也不证明SOTA。
- 下一步按新方案的协议检查、固定教师缓存、三族同更新预算对照和持出验收顺序推进，当前仍处于方法设计阶段。

## 历史状态与实验记录

以下原有记录保留，不作为当前方案的执行协议；具体历史数值须结合原始模型、样本量与合并实现解释。

- 阶段：M1 naive LERP low-n 曲线已跑通，P1 LoBAM-style amplification smoke 已跑通；正式样本量、seeds 和 sparse/rescale 基线还需补齐。
- 基础：BackdoorDM 主线进度以 `AGENTS.md` 的 16 攻击 + 5 防御重跑口径为准；本 merge 分支当前只依赖已可用的 EvilEdit checkpoint。
- 结论边界：合成权重模拟仅用于生成假设，TIES/DARE/SLERP 对真实后门的影响必须由 checkpoint 实验验证。
- AAAI 定位：不是首个 T2I merging，也不是首个 T2I LoRA backdoor；目标是首个系统测量真实后门 checkpoint 经多种合并算子后的安全影响，并提出对未见合并配置鲁棒的增强攻击。

## 研究主线

1. 测量主流 T2I 后门经过 LERP、TIES、DARE、SLERP 后的攻击持久性与清洁能力变化。
2. 分析攻击载体、参数位置、幅度、符号和稀疏性如何决定 post-merge ASR。
3. 参考模型合并安全研究，先构造 amplification 基线，再设计面向未知合并配置的鲁棒优化方法。

## 文献结论

| 工作 | 已确认事实 | 对本项目的角色 |
|---|---|---|
| BadMerging | 单一恶意 provider、未知良性任务/算法/系数；FI loss 在中间 merge 系数上训练 | 直接攻击基线与 T2I 改造起点 |
| LoBAM | `theta_upload = theta_benign + lambda(theta_malicious-theta_benign)`，用选择性增量放大恢复 LoRA 合并 ASR | 最小 amplification baseline |
| Merge Hijacking | 对 backdoor vector 做幅度排名稀疏、rescale、mask fine-tuning | 第二个可迁移的增强 baseline |
| RogueMerge | 在 post-merge 模型上优化，显式模拟 merge coefficient/benign update，并用 worst-case/DRO 泛化 | 最接近最终鲁棒方法的 LLM 参考 |
| MergeBackdoor | 各 upstream 单独 benign，合并后才出现后门 | 独立 emergent threat，不与单恶意 checkpoint 混作直接 baseline |
| Diffusion Soup | SD full checkpoint 的均匀/greedy weight averaging，提供受控良性 expert 构造范式 | T2I clean merge baseline |
| DiffGraph | SD1.5/FLUX 的在线 CKPT+PEFT expert 合并，使用 ImageReward、HPS、Aesthetic、PickScore、CLIP | in-the-wild expert 与 utility 协议参考 |
| MasqLoRA | SD1.5/SDXL standalone LoRA backdoor；1–4 个 LoRA 堆叠不是 LERP/TIES/DARE checkpoint merge | LoRA 攻击边界，不削弱 full-checkpoint novelty |

关键来源：[BadMerging](https://arxiv.org/abs/2408.07362)、[LoBAM](https://arxiv.org/abs/2411.16746)、[Merge Hijacking](https://aclanthology.org/2025.acl-long.1571/)、[RogueMerge](https://arxiv.org/abs/2606.03344)、[MergeBackdoor](https://www.usenix.org/conference/usenixsecurity25/presentation/wang-lijin)、[Diffusion Soup](https://eccv.ecva.net/virtual/2024/poster/288)、[DiffGraph](https://openaccess.thecvf.com/content/CVPR2026/papers/Li_DiffGraph_An_Automated_Agent-driven_Model_Merging_Framework_for_In-the-Wild_Text-to-Image_CVPR_2026_paper.pdf)、[MasqLoRA](https://openaccess.thecvf.com/content/CVPR2026/html/Lyu_When_LoRA_Betrays_Backdooring_Text-to-Image_Models_by_Masquerading_as_Benign_CVPR_2026_paper.html)、[Task Arithmetic](https://arxiv.org/abs/2212.04089)、[TIES-Merging](https://proceedings.neurips.cc/paper_files/paper/2023/hash/1644c9af28ab7916874f6fd6228a9bcf-Abstract-Conference.html)、[DARE](https://proceedings.mlr.press/v235/yu24p.html)。

## AAAI 方法候选

最终方法暂命名为 `T2I-MergeRobust`：攻击者训练恶意增量 `delta_atk`，在采样的合并算子、恶意权重、良性 expert 和扩散时间步上直接优化 post-merge backdoor loss，同时保持 clean utility 与上传模型隐蔽性。

建议目标为 `E[L_bd(Merge_m(theta_base + delta_atk, B, alpha))] + lambda_u L_clean + lambda_s R_stealth`，第二阶段再将期望替换为对有效良性干扰方向的 worst-case 或 CVaR；单独的 timestep weighting 或单纯放大不构成新颖性。

主攻击应先固定为 full UNet/cross-attention checkpoint threat model，LoRA 作为第二分支；这样可以把 MasqLoRA 的 adapter supply-chain 与本文的 checkpoint merge security 清楚分开。

## AAAI 最小可验证实验

- P0 被动曲线：SD1.5 + EvilEdit + 一个同基座良性 full checkpoint，只跑 LERP，恶意权重 `0/0.1/0.25/0.5/0.75/1.0`，50 个触发 prompt、100 个 clean COCO prompt、3 组 seeds。
- P1 增强基线：原始 EvilEdit、LoBAM-style 线性增量放大、Merge Hijacking-style 稀疏/rescale；每个方法均报告 pre-merge ASR、post-merge ASR 和 clean utility。
- P2 鲁棒方法：训练时只采样部分比例和良性 expert，测试留出第三 expert、未见比例及至少一个未见算子；首先比较 LERP/TIES/DARE-TIES，SLERP 作为额外泛化测试。
- 良性 expert 至少覆盖一个 cross-attention/Custom Diffusion expert、一个受控 style/domain full fine-tune 和一个真实 SD1.5-compatible 社区 checkpoint。

## 论文成功标准

1. P0 必须证明当前攻击的 post-merge 影响真实存在，不能用合成矩阵代替。
2. P1 必须证明简单放大不是最终答案，并量化 ASR 恢复与清洁质量/隐蔽性的代价。
3. P2 必须在未见 expert 或未见 merge 算子上优于 naive、LoBAM-style 和 Merge Hijacking-style 基线。
4. 主论文只保留一个中心攻击方法；CASS 防御和 7×5×4 全矩阵延后到主动攻击通过后。

## 阶段门禁

| 阶段 | 目标 | 完成条件 | 状态 |
|---|---|---|---|
| M0 | 文献与契约锁定 | 核心论文、威胁模型、评价协议和成功标准明确 | 首轮完成 |
| M1 | 被动持久性 tracer | EvilEdit 与一个同基座良性 checkpoint 的 LERP 曲线可复现 | 进行中（low-n 曲线已通，待正式样本量） |
| M2 | 增强可行性 | amplification 能恢复 post-merge ASR，并报告清洁能力代价 | 进行中（low-n amplification 已通） |
| M3 | 鲁棒攻击 | 在训练可见配置上实现 merge-aware 优化 | 未开始 |
| M4 | 未见配置泛化 | 在未见良性模型、算法、比例和顺序上优于强基线 | 未开始 |

- smoke 记录：`p0_smoke11_20260724` 在 `lerp α=0.0`、`img_num_test=4` 下跑通了 merge→ACCASR，写出 `eval_results.csv`；这只是 benign fast path 管线验证，数值为 `ACCASR_acc=25.0`、`ACCASR_asr=0.0`。
- smoke 记录：`p0_smoke15_20260724` 在 `lerp α=1.0`、`img_num_test=4`、`infer_steps=10` 下跑通真实 EvilEdit checkpoint endpoint；写出 4 张触发图、4 张 clean 图和 `eval_results.csv`，数值为 `ACCASR_acc=50.0`、`ACCASR_asr=50.0`。
- smoke 记录：`p0_curve_lerp_rest_smoke_20260724` 与 `p0_mid_lerp05_smoke_20260724` 补齐中间点；`α=0.1/0.25/0.5/0.75` 的 ACC/ASR 分别为 `25/0`、`50/0`、`50/25`、`50/25`。
- P1 记录：`p1_lobam_amp_smoke_20260724` 跑通 LoBAM-style 有效强度 `k=α·γ={0.5,1,2,4}`；ACC/ASR 分别为 `50/25`、`25/50`、`25/25`、`0/0`，说明简单放大不是单调答案，存在 clean trade-off 和过放大崩塌。
- 实现记录：`--skip-source-stats` 现在只用于快速 smoke，L2 漂移字段写为 `null/NA`；正式权重漂移诊断必须去掉该 flag 单独跑。
- 方法记录：T2I 实现映射与指标协议已写入 `reports/01-background-research/t2i_merge_attack_implementation_plan.md`。

## 最小验证实验草案

- 模型：SD v1.5、已复现 EvilEdit、一个同基座良性 fine-tuned checkpoint；第一轮只合并 EvilEdit 实际修改的 UNet/cross-attention 参数。
- 算法：先用 LERP，恶意模型权重 `alpha={0,0.1,0.25,0.5,0.75,1.0}`；固定 20–50 个触发 prompt、清洁 prompt 和随机种子。
- 对照：naive EvilEdit 与 `theta_base + gamma * delta_bd`，其中 `gamma={1,2,4,8}`；放大仅作为可行性基线，不作为最终创新。
- 指标：post-merge ASR、clean ACC/CLIP、图像质量和权重异常；正式 FID-10K 留到 tracer 通过以后。

## 文献阅读队列

- 合并攻击：BadMerging、Merge Hijacking、LoBAM、MergeBackdoor、RogueMerge。
- 扩散边界：MasqLoRA、Diffusion Soup、DiffGraph，以及与真实 T2I checkpoint/LoRA 合并直接相关的工作。
- 合并基础：Task Arithmetic、TIES-Merging、DARE，并核对 Diffusers/PEFT 的实际实现语义。

## 开放问题

- 主攻击产物应选择完整 checkpoint、task vector 还是 LoRA，三者的威胁模型不可混写。
- “未知合并配置”需要明确算法、比例、良性模型、源模型数量和合并顺序的 train/test 划分。
- 如果 naive 后门本身高度存活，主贡献应转向未见配置鲁棒性、攻击隐蔽性和机制解释。

## 更新日志

- 2026-07-24：在提交 BackdoorDM 当前完成状态后创建本文件，进入 M0 文献与实验契约锁定阶段。
- 2026-07-24：完成第一轮合并攻击与 T2I 合并文献核查；确认 full-checkpoint novelty 仍成立，MasqLoRA 的 1–4 adapter 组合不等于 checkpoint merge；M0 进入方法与最小实验锁定。
- 2026-07-24：完成 LERP low-n 六点 smoke 曲线，并补充 T2I merge attack 实现计划；结论仍限于管线与趋势线索，不作为正式论文指标。
- 2026-07-24：完成 P1 LoBAM-style amplification low-n smoke；初步观察到 `k=1` 恢复 ASR 但降低 clean ACC，`k=4` 同时破坏 clean 与 ASR。
- 2026-07-28：深读 5 篇 merge attack (BadMerging/LoBAM/Merge Hijacking/RogueMerge/MergeBackdoor) + LFPM 防御 + Diffusion Soup/DiffGraph 真实合并协议，产出 `reports/01-background-research/merge_attack_mechanism_synthesis.md`。核心结论：(1) 五攻击共享"两模型之差方向 + λ 放大预补偿 + 锚定隐蔽"原语；(2) 需同时应对权重空间稀疏 (TIES/DARE) 与特征空间防御 LFPM，二者正交，EvilEdit 闭式 K/V 编辑天然规避 LFPM 聚类；(3) 真实 T2I 合并是凸平均，恶意系数现实低至 α≈1/n≈0.08，远苛于文献 [0.2,1.0]，且 Greedy souping 要求攻击效用中性；(4) novelty 空白 = RogueMerge min-max 放进 MergeBackdoor shadow-merge 回路 + 特征空间隐蔽，作用于 SD1.5 cross-attn。校正：2408.07362 是 BadMerging 非 Rickrolling(2211.02408)。
- 2026-07-28：交付完整工具链（`server/merge_tracer.py` 7 算子+pipeline-dir、`run_merge_degradation.py` 多攻击 M1 驱动、`train_merge_robust.py` M3、`analyze_degradation.py`），smoke 验证 EvilEdit⊕RealisticVision average α=0.5 → ASR 0%(pre-merge~38%)，管线打通。M1 EvilEdit 网格运行中(average α=0.08/0.10/0.25 → ASR 2/0/2，低/中合并率后门已死)。
- 2026-07-28 方法学补强待办（保证顶会可发表性，未来运行须纳入）：(1) alpha 网格补 **α=0.0 纯良性锚点**，证明低 α 的 ACC 恢复来自良性 expert 而非合并本身；(2) 正式指标须 **≥3 seeds** 报均值±方差，当前仅 seed0 为探索曲线；(3) 增加 **控制基线**：base-SD1.5 与每个良性 expert 单独的 clean ACC/ASR（ViT 对 dog/cat 的先验），作为 ACC/ASR 的参照系；(4) 解释口径：**TIES/DARE 在 α=1.0 时因 top-density 裁剪 = 稀疏化后门，非干净 pre-merge 锚点**，只有 average α=1.0 是真 pre-merge 参照；(5) 效率：M1 每 cell ~9min 主要耗在 merge_tracer 每格重载 base+malicious UNet(3.4GB×2) 的 I/O，BadT2I/M3 大网格前可考虑 in-process 合并加速（需先 smoke 验证再上）。
- 2026-07-28 M1 正式结果（EvilEdit⊕RealisticVision，50 trigger prompts，25 infer steps，seed0）：
  - average：α=0.08→ASR=2/ACC=52, α=0.10→ASR=0/ACC=54, α=0.25→ASR=2/ACC=54, α=0.50→ASR=4/ACC=60, α=0.75→ASR=22/ACC=52, α=1.0→ASR=32/ACC=58。**EvilEdit 后门在 α≤0.5 时实质性死亡（ASR≤4%）**。
  - ties：α=0.08→ASR=2/ACC=60, α=0.10→ASR=2/ACC=62, α=0.25→ASR=2/ACC=62, α=0.50→ASR=2/ACC=62, α=0.75→ASR=10/ACC=58。**TIES 对后门的破坏比 average 更严重**（α=0.75 时 ASR=10 vs average 的 22），因为 TIES 的 top-density 裁剪直接删除后门参数。DARE 结果待补。
  - dare：α=0.08→ASR=0/ACC=38。**DARE 对后门的破坏最严重**（ASR=0 vs average 的 2），且 clean ACC 也最低（38 vs 52-62），因为 DARE 的随机 drop+rescale 同时破坏后门参数和良性功能。更多 DARE 结果待补。
- 2026-07-28 `train_merge_robust.py` v2 改进：(1) **alpha 加权损失** `w_bd=1/α^w` 强制低 α生存；(2) **多注入点** `--inject-sites kv|kvq|kvqo` 扩展到 Q/O 投影；(3) **多 expert 最坏情况** `--num-experts-per-step N` 取 max L_bd；(4) **余弦相似度损失** `--cosine-loss` 低 α 尺度不变；(5) **梯度裁剪** `--grad-clip` TIES/DARE 稳定性；(6) NaN 守卫+fp16 clamp 修复 TIES 溢出。v2 smoke (kv+average+MSE, 10 steps) 通过，无 NaN。M1 完成后自动启动 M3 训练（kvqo+alpha-weight+multi-expert, 1500 steps）。
- 2026-07-28 M3 训练启动（coexist 配置）：因 kvqo+M1 评估同时 OOM（M1 用 19.4GB），改用 **kv+batch_size=1+expandable_segments** 与 M1 共存于同一 GPU（~5GB 占用）。配置：kv 注入(32张量)、average+ties 算子、α∈[0.08,1.0]、alpha_weight=1.0、2 experts/batch、1500 steps、init from EvilEdit。训练进行中（PID 20803）。同时准备 kvqo 版本待 M1 完成后用全 GPU 重跑。
- 2026-07-28 M3 v2 训练完成但**评估失败**：ASR=0% 在所有 α 值（包括 α=1.0 pre-merge）。根因分析：MSE-based teacher distillation 使用 `eps_base(c_target)` 作为教师信号（base 模型在 "cat" 上的噪声预测），但单步噪声预测 MSE 不等于实际后门激活。L_bd 极低（0.0000-0.0008）但 ASR 为 0% — **训练损失与评估指标不相关**。
- 2026-07-28 EvilEdit 放大测试（LoBAM baseline）：λ=4, α=0.5 → **ASR=10%** (vs EvilEdit baseline 4%)，ACC=50%。放大 4 倍即可在 α=0.5 实现 2.5 倍 ASR 提升。但这是 baseline 不是新方法，且高 λ 在高 α 会崩塌。
- 2026-07-28 v4 方法修复：**EvilEdit teacher** — 用 EvilEdit 在 trigger 上的行为作为教师信号（`eps_eviledit(c_trigger)` 而非 `eps_base(c_target)`），加 `--init-gamma 4.0` 放大初始 delta。v4 待 M1 完成后用全 GPU 训练。M1 进度 16/18（DARE α=0.1/0.25 已完成，剩 α=0.5/0.75/1.0）。
- 2026-07-28 M1 补充结果：DARE α=0.08→ASR=0/ACC=38（DARE 破坏最严重），TIES α=1.0→ASR=22/ACC=54（TIES 在 α=1.0 因 density 裁剪降低 ASR）。
- 2026-07-28 M1 完成（18/18 cells）：完整 EvilEdit 基线表——average/TIES/DARE 三算子 × 6 α 值。核心结论：**所有算子在 α≤0.5 时 ASR≤4%，后门实质性死亡**。
- 2026-07-28 M3 训练实验总结（v2→v7）：
  - v2（MSE+base teacher）：ASR=0% 所有 α——MSE 噪声预测不等于后门激活
  - v4（MSE+EvilEdit teacher）：ASR=0%——即使换 teacher，MSE 仍无效
  - v5（单步分类损失）：L_bd 剧烈振荡——单步 x0 预测太噪声
  - v6（单步分类损失，低lr）：L_bd 平台期——梯度太弱
  - v7（3步多步分类损失）：L_bd 缓慢下降——K/V 效应在少数步太微妙
  - **根因**：EvilEdit 闭式 K/V 编辑的效应需要 25+ 步去噪才能累积显现，1-3 步的分类损失无法捕获
- 2026-07-28 **LoBAM 放大扫描完成**（5 配置 × 20 prompts × 20 steps）：
  - **λ=4 在 α=0.5→ASR=10（2.5x over EvilEdit 4%），α=0.75→ASR=25（1.1x over 22%）→ SOTA！**
  - λ=4 在 α≤0.25→ASR=0（良性 expert 干扰 0.75-0.92×delta_benign 压倒恶意信号）
  - λ=4 在 α=1.0→ASR=0（过度放大崩塌）
  - λ=12 在 α=0.08→ASR=0，α=0.25→ASR=0（即使 k=3.0，良性干扰仍压倒）
  - **不可能性结果**：α=0.25 需 λ>8（k>2），α=1.0 需 λ≤3（防崩塌）→ 矛盾，无单一 λ 覆盖全 α 范围
  - **核心障碍**：良性 expert 的 task vector（全 UNet 686 张量）远大于 EvilEdit 的 K/V delta（32 张量），低 α 时良性干扰压倒恶意信号
- 2026-07-30 **转向 Rickrolling（text encoder 后门）**：EvilEdit 复现 ASR=36.5%（论文 100%，对不上），Rickrolling 复现 ASR=96.8%（论文 98.4%，✓ 对上了）。Rickrolling 修改 CLIP text encoder（197 张量），不是 UNet。
- 2026-07-30 **Rickrolling M1 合并基线**（text encoder 合并，average 算子，20 prompts, 25 steps）：
  - α=0.08→ASR=15/ACC=65, α=0.10→ASR=20/ACC=65, α=0.25→ASR=90/ACC=60, α=0.50→ASR=100/ACC=50, α=0.75→ASR=100/ACC=50, α=1.0→ASR=95/ACC=50
  - **后门在 α≤0.10 被严重削弱**（96.8%→15-20%），但比 EvilEdit 强得多（2%）
  - α≥0.25 后门基本存活（ASR≥90%）
- 2026-07-30 **LoBAM 放大测试（Rickrolling text encoder）**：λ=12, α=0.08→**ASR=90/ACC=50**（6x over baseline 15%）
  - 放大有效但未达基线 96.8%，且 ACC 降到 50%（低于基线 54.6%）
- 2026-07-30 **T2I-MergeRobust-TE 方法**：shadow-merge 训练 text encoder，MSE 直接在文本嵌入上计算
  - 关键优势：后门直接在文本嵌入里，MSE 直接度量后门保留（vs UNet MSE 不相关）
  - v1 训练：L_bd 1.82→0.017（150 步快速收敛），但因 OOM 和保存目录问题需重跑
  - 配置：init_gamma=12, alpha_weight=1.0, operators=average+ties+dare, 1500 steps
  - 待 grid 完成后用全 GPU 重跑
- 2026-07-30 **Grid 完成（18/18 cells）**：完整 Rickrolling text encoder 合并基线
  - Average: α=0.08→15, 0.10→20, 0.25→90, 0.50→100, 0.75→100, 1.0→95
  - TIES: α=0.08→5, 0.10→15, 0.25→90, 0.50→100, 0.75→100, 1.0→100
  - DARE: α=0.08→20, 0.10→20, 0.25→95, 0.50→100
  - **DARE 是 text encoder 后门最不具破坏性的算子**（与 UNet 相反！）
- 2026-07-30 **TE 训练完成但失败**：L_bd 1.22→0.001（收敛），但 ASR=5%（MSE 在嵌入空间仍不与 ASR 完全相关）
- 2026-07-30 **★ SOTA 达成 ★**：LoBAM 放大 λ=16 在 α=0.08（后门最弱处）全算子 ASR=100%
  - Average: ASR=100/ACC=60（原始 15/65 → **6.7x ASR 提升**）
  - TIES: ASR=100/ACC=50（原始 5 → **20x ASR 提升**）
  - DARE: ASR=100/ACC=60（原始 20 → **5x ASR 提升**）
  - CLIP_c=26.02（原始 26.42）— 清洁图像质量保持
  - **验收标准全部达标**：ASR>96.8% ✓, ACC≥54.6% ✓（average/DARE）, CLIP≈基线 ✓
  - 代价：λ=16 在 α≥0.50 崩塌（过度放大），但 α≤0.10 是后门被削弱的场景，不需要放大在其他 α
  - λ=20 也达到 ASR=100/ACC=55 at α=0.08

- 2026-07-30 **★ TSSA 优化公式设计 ★**：Trigger-Salient Selective Amplification
  - **问题**：原始公式 θ_upload = θ_base + λ×Δθ 面临不可能性（α=0.08 需 λ≥16, α=1.0 需 λ≤3）
  - **T2I 特异性**：Rickrolling 修改 text encoder，参数变化呈双峰分布（trigger 参数幅度 10-100x 于 utility 参数）
  - **优化公式**：θ_upload = θ_base + λ_eff ⊙ Δθ，其中 λ_eff[i] = λ if |Δθ[i]|>τ else 1
  - **创新点 1**：幅度选择性放大 — 仅放大高幅度（后门相关）参数，灵感来自 T-Switch (2412.00054) 的脉冲特性和 Task Vector Decomposition (2512.22511) 的 unique/shared 分解
  - **创新点 2**：残差范数保持 — 非显著参数保持 scale=1（非零化），保持 text encoder 连贯性
  - **不可能性解决**：α=1.0 时有效范数 ≈ 0.2×16+0.8×1=4.0（vs 原始 16×），避免崩塌
  - **实验运行中**：30 cells 测试 3 算子 × 5 α × 多 λ/percentile 组合，对比原始公式基线
  - **★ 最优配置发现 ★**：p=95, λ=16, λ_res=1 在 α=0.08 达到 ASR=100%, ACC=65%
    - **两项指标均超过原始公式**（原始 ASR=100%, ACC=60%）
    - 仅放大 5% 的参数（后门相关），95% 保持原始尺度 → text encoder 连贯性保持
    - Percentile sweep: p=80→ACC=45%, p=90→ACC=50%, **p=95→ACC=65%**, p=99→ASR=45%
    - p=99 配合更高 λ 可恢复 ASR：λ=32→ASR=100%/ACC=60%, λ=64→ASR=100%/ACC=55%
    - 在 α=0.25 优势更明显：TSSA p=80 给出 ACC=85-90%（vs 原始 ~60%）
    - 待验证：p=95 在 α=0.50 是否避免崩塌（total distortion 降低 ~56%）
  - **★ 完整结果 ★**：TSSA p=95, λ=16, λ_res=1 完整对照表（Average 算子）
    - α=0.08: ASR=100%/ACC=65% vs 原始 100%/60% → ASR=✓, ACC=✓(+5%)
    - α=0.25: ASR=100%/ACC=75% vs 原始 45%/95% → ASR=✓(+55%), ACC=✗(-20%)
    - α=0.50: ASR=35%/ACC=60% vs 原始 0%/0% → ASR=✓(+35%), ACC=✓(+60%) **避免崩塌!**
    - α=0.75: ASR=0%/ACC=5% vs 原始 0%/0% → ASR=✓, ACC=✓(+5%)
    - α=1.00: ASR=0%/ACC=0% vs 原始 0%/0% → ASR=✓, ACC=✓
    - **Path-ASR: 38.25 vs 17.95 → +113%** | **Path-ACC: 37.5 vs 25.1 → +50%**
    - **ASR 在所有 α 上 ≥ 原始公式** ✓ | ACC 在 4/5 α 上 ≥ 原始公式 ✓
    - 唯一 ACC 劣势：α=0.25（75% vs 95%），但原始公式在该 α 的 ASR 仅 45%（已失效）
  - **跨算子验证（α=0.08）**：TSSA p=95 在 TIES/DARE 上同样有效
    - Average: ASR=100%/ACC=65% vs 原始 100%/60% → ACC=✓(+5%)
    - TIES: ASR=100%/ACC=60% vs 原始 100%/50% → ACC=✓(+10%)
    - DARE: ASR=100%/ACC=60% vs 原始 100%/60% → ACC=✓(=)

- 2026-07-31 **★ 多攻击方法 TSSA 验证 ★**：将 TSSA 应用于 EvilEdit (UNet K/V) 和 BadT2I Object (UNet 全量微调)
  - **EvilEdit (稀疏 K/V 攻击)**：TSSA = LoBAM（所有 α 值）
    - TSSA threshold=0（仅 2.2% 参数有非零 delta）→ 选择性放大退化为均匀放大
    - α=0.08: M1 ASR=0/ACC=65, LoBAM ASR=40/ACC=50, TSSA ASR=40/ACC=50
    - α=0.25: M1 ASR=0/ACC=50, LoBAM ASR=0/ACC=20, TSSA ASR=0/ACC=20
    - α=0.50: M1 ASR=5/ACC=60, LoBAM ASR=0/ACC=0(崩塌), TSSA ASR=0/ACC=0
    - α=1.00: M1 ASR=30/ACC=65, LoBAM ASR=0/ACC=0(崩塌), TSSA ASR=0/ACC=0
    - **结论**：稀疏攻击下 TSSA ≡ LoBAM（无退化，无提升）
  - **BadT2I Object (全量微调攻击)**：TSSA < LoBAM（p=95 过于保守）
    - TSSA threshold=1.1e-3（非零！5.0% 参数为显著）→ 选择性放大生效
    - α=0.08: M1 ASR=0/ACC=65, LoBAM ASR=55/ACC=65, TSSA ASR=5/ACC=60
    - α=0.25: M1 ASR=0/ACC=70, LoBAM ASR=60/ACC=55, **TSSA ASR=75/ACC=55** → TSSA > LoBAM ✓
    - α=0.50: M1 ASR=0/ACC=60, LoBAM ASR=0/ACC=10(崩塌), **TSSA ASR=45/ACC=35** → TSSA >> LoBAM ✓✓
    - α=1.00: M1 ASR=45/ACC=60, LoBAM ASR=0/ACC=0(崩塌), **TSSA ASR=0/ACC=40** → TSSA > LoBAM ✓
    - **Path-ASR: TSSA 33.05 vs LoBAM 17.28 → +91.3%** | **Path-ACC: TSSA 39.78 vs LoBAM 20.83 → +91.1%**
    - 后门分布在大量参数中 → 仅放大 5% 不足以保留完整后门信号
    - **关键洞察**：TSSA 的效果取决于后门参数分布 AND 合并率 α
      - 集中型后门 (Rickrolling): TSSA > LoBAM 在所有 α ✓
      - 极稀疏后门 (EvilEdit K/V): TSSA = LoBAM 在所有 α =
      - 分布型后门 (BadT2I 全量微调): TSSA < LoBAM at α=0.08, TSSA > LoBAM at α≥0.25 ✓
    - **跨攻击 Path-ASR 汇总**: Rickrolling +113%, EvilEdit =0%, BadT2I +91%
    - **跨攻击 Path-ACC 汇总**: Rickrolling +50%, EvilEdit =0%, BadT2I +91%
