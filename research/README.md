# 当前研究

当前方向：研究真实扩散模型 checkpoint 合并后的后门鲁棒性，新任务检验特殊字符触发的行为筛选与参数恢复定位。用户已授权TCL服务器验证，103定位经修订完成，源基线受103 GPU故障影响，104 CUDA初始化失败、127分片见证超时后修订并续跑，13:25完成67图；三轮旧结果尚未达到研究目标，旧run保持停止。

| 文档 | 用途 |
|---|---|
| [特殊字符定位验证任务](tasks/2026-10-29-trigger-contrast-localization/TASK.md) | 扩样后的当前任务，方法、预算、运行证据和待完成状态均见TASK |
| [任务索引与模板](tasks/README.md) | 每个任务独立目录及TASK状态，通用规范统一在AGENTS.md维护 |
| [初始小样本草案](trigger_contrast_localization_pilot_review_2026-10-29.md) | 历史2048图设计，已由上述扩样任务接续，未执行 |
| [输入对比与后门参数定位调研](../reports/trigger_contrast_parameter_localization_review_2026-10-29.md) | 新筛选假说：普通狗/猫语义差不等于后门参数，需真实触发对照与干预验证；未替换执行方案或恢复实验 |
| [从头解释方法、名词与三轮效果](tssa_methods_and_results_explained_2026-10-29.md) | 先读这一份；解释Uniform4、TSSA16、a/b、合并比例、攻击成功率和正常能力 |
| [当前机器可读状态](project_state.json) | 新agent接续时先读，保存授权范围、三轮结论及下一步边界 |
| [暂停时简明总结](tssa_attempts_summary_2026-10-29.md) | 三轮次数、失败原因与结论边界 |
| [数据与代码整理目录](../results/organization-2026-10-29/README.md) | 原图、逐图指标、训练轨迹、响应缓存、执行代码及回传缺口 |
| [存储与换机恢复方案](research_storage_and_restore_plan_2026-10-29.md) | 进度与代码纳入Git，大文件留服务器；新电脑按[接续步骤](../storage/NEW_COMPUTER.md)及[服务器索引](../storage/SERVER_INDEX.md)定位取回，Drive暂停 |
| [TSSA 梯度校准方案](tssa_response_calibration_method_proposal.md) | 已完成的历史执行方案，包含公式、正常保持、对照、预算与验收；不因新任务恢复旧run |
| [实验准备清单](experiment_preparation.md) | 原轮次的历史准备记录，不是当前待办或自动恢复指令 |
| [研究进度](merging_attack_progress.md) | 顶部为当前决策，下方保留历史探索记录 |
| [本轮执行记录](tssa_overnight_progress.md) | 2026-10-28已结束，完整历史、资源释放与验收证据 |
| [直接ASR探索负结果](../results/tssa-opt-exploration-2026-10-28/direct_ASR_negative_report_2026-10-28.md) | 816图/0更新，开发无合格增益，独立确认未启动；完整性缺陷另列 |
| [目标语义诊断方案](tssa_target_semantic_diagnostic_proposal_2026-10-28.md) | 已完成462次前向诊断，梯度一致性及局部可行性未通过；用户已暂停，见[尝试总结](tssa_attempts_summary_2026-10-29.md) |
| [初步验证最终报告](../results/tssa-mvp-2026-10-26/initial_validation_report_2026-10-28.md) | 1520图/144更新，RC与Uniform持出ASR均0，TSSA无合格候选、未测持出 |
| [MVP离线执行手册](tssa_mvp_runbook.md) | 学校服务器离线安装、两卡许可、CPU预检、双进程执行与中断恢复 |
| [MVP 固定协议](tssa_mvp_2026-10-26.json) | 本轮模型、提示、随机数、优化、正常门禁和持出选择规则 |
| [MVP 资产清单](tssa_mvp_assets_2026-10-26.json) | 公开模型固定revision、文件大小、上游哈希及离线中转清单 |

环境和资产索引：[模型固定来源](tssa_mvp_assets_2026-10-26.json) · [环境清单](tssa_mvp_environment_2026-10-26.json) · [依赖输入](tssa_mvp_requirements_2026-10-26.in) · [依赖锁](tssa_mvp_requirements_2026-10-26.lock) · [103离线Python准备](node103_offline_python_plan_2026-10-28.md)。后续探索的[设计](tssa_optimization_exploration_design_2026-10-28.md)、[冻结协议](tssa_optimization_exploration_2026-10-28.json)、[进度](tssa_optimization_exploration_progress_2026-10-28.md)与[10月27日历史摘要](tssa_progress_summary_2026-10-27.md)保持分开；每次变更按[维护入口](../storage/INDEX_MAINTENANCE.md)复核关联记录。

已完成的TSSA轮次固定原始差分和A/B分组，仅学习两个标量a、b，β在单次训练中固定；新定位任务独立定义筛选方式，不改写这些旧协议。旧有限差分/局部求解器方案见[只读封存](../reports/archive/2026-10-23-tssa-local-surrogate/README.md)，历史脚本和结果尚不构成新定位方法验证。

[项目总索引](../README.md) · [论文](../papers/README.md) · [复现](../reproduction/README.md) · [结果](../results/README.md) · [脚本](../scripts/README.md)
