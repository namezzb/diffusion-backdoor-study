# 合并实验代码

当前实验从 [TCL 执行器](trigger_contrast_localization/README.md)进入，模块职责见其代码导航；下列 TSSA 和合并实验代码按所属历史协议解释。

## 历史实验入口

| 已结束的尝试 | 实现入口 | 协议、结果与边界 |
|---|---|---|
| 梯度校准初步验证 | [tssa_mvp_run.py](tssa_mvp_run.py) | [冻结协议](../../research/tssa_mvp_2026-10-26.json) · [最终报告](../../results/tssa-mvp-2026-10-26/initial_validation_report_2026-10-28.md)；1520图、144次更新，未找到合格攻击增益。 |
| 直接按图像攻击成功率搜索 | [tssa_image_search_run.py](tssa_image_search_run.py) | [独立冻结协议](../../research/tssa_optimization_exploration_2026-10-28.json) · [负结果](../../results/tssa-opt-exploration-2026-10-28/direct_ASR_negative_report_2026-10-28.md)；816图、0更新，未打开确认集，原严格审计仍为invalid。 |
| 同状态目标语义诊断 | [tssa_target_semantic_run.py](tssa_target_semantic_run.py) | [方案](../../research/tssa_target_semantic_diagnostic_proposal_2026-10-28.md) · [诊断报告](../../results/tssa-target-semantic-diagnostic-2026-10-28/target_semantic_diagnostic_report_2026-10-29.md)；462次分支前向、0图/0更新，梯度一致性及局部可行性未通过。 |

当前源代码可能含后续修复，不能自动视为旧运行使用的版本；复核时以各运行清单、冻结快照与文件哈希为准，资料位置见[结果索引](../../results/README.md)。

新运行的操作、进度、逐图或逐步记录及阶段结果以可读 Markdown 保存；读取器兼容旧 JSON/JSONL 记录。固定科学输入、模型配置、权重仍保留所需格式，历史文件不改写。

## 梯度校准与评价组件

| 脚本 | 用途与验证边界 |
|---|---|
| [tssa_gradient_core.py](tssa_gradient_core.py) | 固定差分分组、后门及正常损失、两标量更新与投影。 |
| [tssa_sd_runtime.py](tssa_sd_runtime.py) | 离线模型加载、真实去噪响应、合法DDIM轨迹缓存与梯度路径；单卡完整模型及CUDA已在MVP中使用。 |
| [tssa_mvp_evaluate.py](tssa_mvp_evaluate.py) | 逐图记录完整性、源门禁、开发选择、独立持出与正常能力约束。 |
| [tssa_mvp_score.py](tssa_mvp_score.py) | 离线ViT/CLIP图像评分，读取已保存PNG像素；评分通过不等于方法有效。 |
| [tssa_mvp_run.py](tssa_mvp_run.py) | 单卡阶段执行、逐图/逐步回执、候选冻结和终态报告；本轮单卡已结束，不恢复旧身份。 |
| [tssa_mvp_dual_run.py](tssa_mvp_dual_run.py) | 同机双进程实现，固定每卡72次更新；仅有CPU编排与状态迁移证据，不能当作已验证的跨服务器分工入口。 |
| [tssa_image_search_run.py](tssa_image_search_run.py) | 预登记系数点的图像搜索、独立开发选择和确认门禁；不允许临时增加点或复用已结束预算。 |

## 目标语义诊断组件

| 脚本 | 用途 |
|---|---|
| [tssa_target_semantic_cache.py](tssa_target_semantic_cache.py) | 从旧运行的已验证缓存派生限定状态并保留来源，不生成新轨迹。 |
| [tssa_target_semantic_runtime.py](tssa_target_semantic_runtime.py) | 完整模型目标/正常响应、真实a/b梯度、固定批布局与精度设置。 |
| [tssa_target_semantic_gates.py](tssa_target_semantic_gates.py) | 冻结诊断单元、资源预算、身份/重复/目标方向、有限差分与八点可行性门禁。 |
| [tssa_target_semantic_run.py](tssa_target_semantic_run.py) | 一次模型加载、唯一运行身份、逐单元账本、资源保护及终态退出；已结束运行不可重放。 |

## CPU检查与结果复核

| 检查入口 | 检查范围 |
|---|---|
| [test_tssa_gradient_core.py](test_tssa_gradient_core.py) | 数学定义、固定分组、标量梯度、更新及投影。 |
| [test_tssa_sd_runtime_integration.py](test_tssa_sd_runtime_integration.py) | 微型CLIP/UNet的真实库梯度与DDIM集成，不替代完整模型CUDA结果。 |
| [test_tssa_mvp_run.py](test_tssa_mvp_run.py) · [双卡检查](test_tssa_mvp_dual_run.py) | 阶段编排、预算、中断恢复、优化器与随机状态迁移。 |
| [test_tssa_mvp_evaluate.py](test_tssa_mvp_evaluate.py) · [评分检查](test_tssa_mvp_score.py) | 逐图指标、选择规则及离线图像评分。 |
| [test_tssa_image_search_run.py](test_tssa_image_search_run.py) · [资源快照检查](test_tssa_resource_snapshot.py) | 搜索/确认预算和资源计数字典快照，修复不改写旧审计结果。 |
| [目标语义运行检查](test_tssa_target_semantic_run.py) · [运行库检查](test_tssa_target_semantic_runtime.py) · [门禁检查](test_tssa_target_semantic_gates.py) | 权限/资源保护、缓存来源、真实微型梯度、诊断枚举及停止规则。 |
| [训练轨迹独立审计](../../results/tssa-mvp-2026-10-26/audit_training_trace_2026-10-28.py) · [持出独立审计](../../results/tssa-mvp-2026-10-26/audit_final_heldout_20261028T0602Z.py) | 从已返回记录复算优化器、候选及评价，不运行研究样本。 |
| [图像搜索结果审计](../../results/tssa-opt-exploration-2026-10-28/audit_image_search_results.py) · [诊断原始产物审计](../../results/tssa-target-semantic-diagnostic-2026-10-28/audit_diagnostic_artifacts.py) | 核对逐图/逐单元证据及哈希；科学门禁失败和证据完整性分开报告。 |

检查数量与通过状态属于具体版本及运行日期，详见各轮结果目录；不要用早期“完整模型/离线环境/GPU尚未验证”的准备记录覆盖后来完成的证据。

## Checkpoint 合并与历史攻击实验

| 脚本 | 用途 |
|---|---|
| [merge_tracer.py](merge_tracer.py) | UNet 合并算子与差分诊断，支持导出权重或完整 pipeline。 |
| [merge_unet_state_dicts.py](merge_unet_state_dicts.py) | UNet 权重组合、产物记录与可选 BackdoorDM 评估。 |
| [merge_text_encoder.py](merge_text_encoder.py) | 文字编码器合并、差分放大与原 TSSA 选择性缩放。 |
| [apply_tssa_unet.py](apply_tssa_unet.py) | 对已有 UNet 差分进行统一或 TSSA 选择性放大。 |
| [run_merge_degradation.py](run_merge_degradation.py) | 扫描合并条件并调用 BackdoorDM 评估 ACC/ASR。 |
| [analyze_degradation.py](analyze_degradation.py) | 汇总合并退化 CSV，生成报告与图表。 |
| [train_merge_robust.py](train_merge_robust.py) | 历史 UNet 合并鲁棒训练尝试。 |
| [train_te_merge_robust.py](train_te_merge_robust.py) | 历史文字编码器合并鲁棒训练尝试。 |
| [post_m3_eval.sh](post_m3_eval.sh) | 历史 M3 训练后比较与汇总入口。 |
| [eval_rick_full.sh](eval_rick_full.sh) | Rickrolling 历史训练模型与缩放模型的比较评估。 |
| [run_rick_te_grid.sh](run_rick_te_grid.sh) | Rickrolling 文字编码器合并网格实验。 |
| [run_tssa_grid.sh](run_tssa_grid.sh) | 原 TSSA 与统一放大的历史网格比较。 |
| [run_tssa_res_test.sh](run_tssa_res_test.sh) | 原 TSSA 未选中差分组的残余缩放实验。 |
| [run_tssa_multi_attack.sh](run_tssa_multi_attack.sh) | 将 UNet 差分增强应用于多种已有攻击的历史比较。 |

[脚本总索引](../README.md) · [研究目录](../../research/README.md)
