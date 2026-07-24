# Checkpoint Merging Attack 进度

> 目标：研究真实 T2I checkpoint 合并对现有后门的影响，并设计可泛化到未知良性模型与未知合并配置的 merge-aware 鲁棒攻击。

## 当前状态

- 阶段：M0 文献与实验契约锁定，尚未启动真实 checkpoint 合并实验。
- 基础：BackdoorDM 严格完成 13/16 攻击闭环、5/5 防御执行，EvilEdit 可作为最快的首个攻击源。
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

关键来源：[BadMerging](https://arxiv.org/abs/2408.07362)、[LoBAM](https://arxiv.org/abs/2411.16746)、[Merge Hijacking](https://aclanthology.org/2025.acl-long.1571/)、[RogueMerge](https://arxiv.org/abs/2606.03344)、[MergeBackdoor](https://www.usenix.org/conference/usenixsecurity25/presentation/wang-lijin)、[Diffusion Soup](https://eccv.ecva.net/virtual/2024/poster/288)、[DiffGraph](https://openaccess.thecvf.com/content/CVPR2026/papers/Li_DiffGraph_An_Automated_Agent-driven_Model_Merging_Framework_for_In-the-Wild_Text-to-Image_CVPR_2026_paper.pdf)、[MasqLoRA](https://openaccess.thecvf.com/content/CVPR2026/html/Lyu_When_LoRA_Betrays_Backdooring_Text-to-Image_Models_by_Masquerading_as_Benign_CVPR_2026_paper.html)。

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
| M0 | 文献与契约锁定 | 核心论文、威胁模型、评价协议和成功标准明确 | 进行中 |
| M1 | 被动持久性 tracer | EvilEdit 与一个同基座良性 checkpoint 的 LERP 曲线可复现 | 未开始 |
| M2 | 增强可行性 | amplification 能恢复 post-merge ASR，并报告清洁能力代价 | 未开始 |
| M3 | 鲁棒攻击 | 在训练可见配置上实现 merge-aware 优化 | 未开始 |
| M4 | 未见配置泛化 | 在未见良性模型、算法、比例和顺序上优于强基线 | 未开始 |

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
