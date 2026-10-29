# 当前研究

当前方向：研究真实扩散模型 checkpoint 合并后的后门鲁棒性，并在正常能力要求下比较固定差分组的校准方式。2026-10-26 用户确认继续采用 v2-gradient；此状态是方法选择，不是实验成功结论。

| 文档 | 用途 |
|---|---|
| [TSSA 梯度校准方案](tssa_response_calibration_method_proposal.md) | 当前唯一方法提案，包含公式、正常保持、对照、预算与验收 |
| [实验准备清单](experiment_preparation.md) | 下一阶段的论文、模型、指标、实现和最小试验准备 |
| [研究进度](merging_attack_progress.md) | 顶部为当前决策，下方保留历史探索记录 |
| [本轮执行记录](tssa_overnight_progress.md) | 2026-10-28已结束，完整历史、资源释放与验收证据 |
| [直接ASR探索负结果](../results/tssa-opt-exploration-2026-10-28/direct_ASR_negative_report_2026-10-28.md) | 816图/0更新，开发无合格增益，独立确认未启动；完整性缺陷另列 |
| [目标语义诊断方案](tssa_target_semantic_diagnostic_proposal_2026-10-28.md) | 已完成462次前向诊断，梯度一致性及局部可行性未通过；用户已暂停，见[尝试总结](tssa_attempts_summary_2026-10-29.md) |
| [初步验证最终报告](../results/tssa-mvp-2026-10-26/initial_validation_report_2026-10-28.md) | 1520图/144更新，RC与Uniform持出ASR均0，TSSA缺失 |
| [MVP离线执行手册](tssa_mvp_runbook.md) | 学校服务器离线安装、两卡许可、CPU预检、双进程执行与中断恢复 |
| [MVP 固定协议](tssa_mvp_2026-10-26.json) | 本轮模型、提示、随机数、优化、正常门禁和持出选择规则 |
| [MVP 资产清单](tssa_mvp_assets_2026-10-26.json) | 公开模型固定revision、文件大小、上游哈希及离线中转清单 |

原始差分和 A/B 分组固定，仅学习两个标量 a、b，β 在单次训练中固定；本次整理没有更改公式或实验协议。旧有限差分/局部求解器方案见 [只读封存](../reports/archive/2026-10-23-tssa-local-surrogate/README.md)，历史脚本和结果尚不构成梯度版验证。

[项目总索引](../README.md) · [论文](../papers/README.md) · [复现](../reproduction/README.md) · [结果](../results/README.md) · [脚本](../scripts/README.md)
