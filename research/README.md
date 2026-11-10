# 研究导航

当前工作由[项目状态](project_state.json)指向 TASK；[任务目录](tasks/README.md)按日期提供交接入口，[工作流程](WORKFLOW.md)说明 session 分工。

## 当前任务与通用工具

| 入口 | 用途 |
|---|---|
| [MasqLoRA复现](tasks/2026-11-05-masqlora-reproduction/TASK.md) | 官方材料、固定对照与真实执行证据 |
| [LoRA融合后门阅读清单](tasks/2026-11-04-lora-merging-reading/TASK.md) | 阅读顺序、原论文与用户阅读状态 |
| [Zotero 文献库整理](tasks/2026-11-10-zotero-library-organization/TASK.md) · [论文目录](tasks/2026-11-10-zotero-library-organization/PAPER_CATALOG.md) | 英文总目录、主题分类、去重与67篇摘要级简介 |
| [TCL 语义评分与完整对照](tasks/2026-11-03-tcl-semantic/README.md) | 科学协议、当前 TASK、过程历史与实现报告 |
| [统一执行机制](tasks/2026-11-02-runtime-reset/README.md) | 执行器设计与工程验证 |
| [GPU 查询工具](tasks/2026-11-02-labgpu-cli/README.md) | labgpu 实现记录；操作见[使用说明](../scripts/connection/LABGPU.md) |
| [目录整理](tasks/2026-11-03-repository-organization/TASK.md) | 导航、任务记录和兼容路径的维护记录 |

## 方法与历史实验

| 主题 | 方案、解释与证据入口 |
|---|---|
| 方法与术语总览 | [Uniform4、TSSA16、合并比例和三轮效果](tssa_methods_and_results_explained_2026-10-29.md) · [尝试总结](tssa_attempts_summary_2026-10-29.md) |
| TCL 定位与干预 | [文献调研](../reports/trigger_contrast_parameter_localization_review_2026-10-29.md) · [初始草案](trigger_contrast_localization_pilot_review_2026-10-29.md) · [历史任务](tasks/2026-10-29-trigger-contrast-localization/README.md) |
| TCL 夜间验证 | [独立任务与原协议](tasks/2026-11-02-tcl-overnight/README.md) |
| TSSA 梯度校准 | [方案](tssa_response_calibration_method_proposal.md) · [最终报告](../results/tssa-mvp-2026-10-26/initial_validation_report_2026-10-28.md) |
| 直接 ASR 探索 | [设计](tssa_optimization_exploration_design_2026-10-28.md) · [固定协议](tssa_optimization_exploration_2026-10-28.json) · [原进度](tssa_optimization_exploration_progress_2026-10-28.md) · [结果报告](../results/tssa-opt-exploration-2026-10-28/direct_ASR_negative_report_2026-10-28.md) |
| 目标语义诊断 | [方案](tssa_target_semantic_diagnostic_proposal_2026-10-28.md) · [诊断报告](../results/tssa-target-semantic-diagnostic-2026-10-28/target_semantic_diagnostic_report_2026-10-29.md) |
| 研究过程 | [合并探索记录](merging_attack_progress.md) · [10月27日摘要](tssa_progress_summary_2026-10-27.md) · [10月28日执行记录](tssa_overnight_progress.md) |
| 更早方法 | [局部求解器只读封存](../reports/archive/2026-10-23-tssa-local-surrogate/README.md) |

这些材料保留各自日期和科学配置，当前状态以项目指针为准。结果和验收边界见[结果索引](../results/README.md)。

## 固定输入与环境资料

| 入口 | 用途 |
|---|---|
| [MVP 协议](tssa_mvp_2026-10-26.json) · [资产清单](tssa_mvp_assets_2026-10-26.json) | 历史固定科学输入；现行实验仍可能引用其资产，路径保持稳定 |
| [环境清单](tssa_mvp_environment_2026-10-26.json) · [依赖输入](tssa_mvp_requirements_2026-10-26.in) · [依赖锁](tssa_mvp_requirements_2026-10-26.lock) | 按平台和运行版本解释 |
| [原准备记录](experiment_preparation.md) · [MVP 执行手册](tssa_mvp_runbook.md) · [103 离线准备](node103_offline_python_plan_2026-10-28.md) | 历史操作依据；现行连接步骤在[服务器手册](../server/OPERATIONS.md) |
| [资料整理目录](../results/organization-2026-10-29/README.md) · [存储方案](research_storage_and_restore_plan_2026-10-29.md) | 原始资料和换机设计；操作入口在[存储导航](../storage/README.md) |

[项目总索引](../README.md) · [论文](../papers/README.md) · [调研](../reports/README.md) · [脚本](../scripts/README.md)
