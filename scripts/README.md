# 脚本索引

更新于2026-10-29，旧实验已结束且旧`gpu`定时任务保持删除；用户已单独授权[TCL定位验证](../research/tasks/2026-10-29-trigger-contrast-localization/TASK.md)，执行须遵守其冻结清单与实时资源门禁。历史结论见[尝试总结](../research/tssa_attempts_summary_2026-10-29.md)。

## 三轮实验入口

| 已结束的尝试 | 实现入口 | 协议、结果与边界 |
|---|---|---|
| 梯度校准初步验证 | [tssa_mvp_run.py](merging/tssa_mvp_run.py) | [冻结协议](../research/tssa_mvp_2026-10-26.json) · [最终报告](../results/tssa-mvp-2026-10-26/initial_validation_report_2026-10-28.md)；1520图、144次更新，未找到合格攻击增益。 |
| 直接按图像攻击成功率搜索 | [tssa_image_search_run.py](merging/tssa_image_search_run.py) | [独立冻结协议](../research/tssa_optimization_exploration_2026-10-28.json) · [负结果](../results/tssa-opt-exploration-2026-10-28/direct_ASR_negative_report_2026-10-28.md)；816图、0更新，未打开确认集，原严格审计仍为invalid。 |
| 同状态目标语义诊断 | [tssa_target_semantic_run.py](merging/tssa_target_semantic_run.py) | [方案](../research/tssa_target_semantic_diagnostic_proposal_2026-10-28.md) · [诊断报告](../results/tssa-target-semantic-diagnostic-2026-10-28/target_semantic_diagnostic_report_2026-10-29.md)；462次分支前向、0图/0更新，梯度一致性及局部可行性未通过。 |
| 特殊字符定位 | [trigger_contrast_localization](merging/trigger_contrast_localization/README.md) | [任务与review](../research/tasks/2026-10-29-trigger-contrast-localization/TASK.md)；本地检查和M06通过，GPU实验待实时许可。 |

当前源代码可能含后续修复，不能自动视为旧运行使用的版本；复核时以各运行清单、冻结快照与文件哈希为准，资料位置见[结果索引](../results/README.md)。

## 梯度校准与评价组件

| 脚本 | 用途与验证边界 |
|---|---|
| [tssa_gradient_core.py](merging/tssa_gradient_core.py) | 固定差分分组、后门及正常损失、两标量更新与投影。 |
| [tssa_sd_runtime.py](merging/tssa_sd_runtime.py) | 离线模型加载、真实去噪响应、合法DDIM轨迹缓存与梯度路径；单卡完整模型及CUDA已在MVP中使用。 |
| [tssa_mvp_evaluate.py](merging/tssa_mvp_evaluate.py) | 逐图记录完整性、源门禁、开发选择、独立持出与正常能力约束。 |
| [tssa_mvp_score.py](merging/tssa_mvp_score.py) | 离线ViT/CLIP图像评分，读取已保存PNG像素；评分通过不等于方法有效。 |
| [tssa_mvp_run.py](merging/tssa_mvp_run.py) | 单卡阶段执行、逐图/逐步回执、候选冻结和终态报告；本轮单卡已结束，不恢复旧身份。 |
| [tssa_mvp_dual_run.py](merging/tssa_mvp_dual_run.py) | 同机双进程实现，固定每卡72次更新；仅有CPU编排与状态迁移证据，不能当作已验证的跨服务器分工入口。 |
| [tssa_image_search_run.py](merging/tssa_image_search_run.py) | 预登记系数点的图像搜索、独立开发选择和确认门禁；不允许临时增加点或复用已结束预算。 |

## 目标语义诊断组件

| 脚本 | 用途 |
|---|---|
| [tssa_target_semantic_cache.py](merging/tssa_target_semantic_cache.py) | 从旧运行的已验证缓存派生限定状态并保留来源，不生成新轨迹。 |
| [tssa_target_semantic_runtime.py](merging/tssa_target_semantic_runtime.py) | 完整模型目标/正常响应、真实a/b梯度、固定批布局与精度设置。 |
| [tssa_target_semantic_gates.py](merging/tssa_target_semantic_gates.py) | 冻结诊断单元、资源预算、身份/重复/目标方向、有限差分与八点可行性门禁。 |
| [tssa_target_semantic_run.py](merging/tssa_target_semantic_run.py) | CPU预检、唯一运行身份、逐单元账本、资源保护及终态退出；已结束运行不可重放。 |

## CPU检查与结果复核

| 检查入口 | 检查范围 |
|---|---|
| [test_tssa_gradient_core.py](merging/test_tssa_gradient_core.py) | 数学定义、固定分组、标量梯度、更新及投影。 |
| [test_tssa_sd_runtime_integration.py](merging/test_tssa_sd_runtime_integration.py) | 微型CLIP/UNet的真实库梯度与DDIM集成，不替代完整模型CUDA结果。 |
| [test_tssa_mvp_run.py](merging/test_tssa_mvp_run.py) · [双卡检查](merging/test_tssa_mvp_dual_run.py) | 阶段编排、预算、中断恢复、优化器与随机状态迁移。 |
| [test_tssa_mvp_evaluate.py](merging/test_tssa_mvp_evaluate.py) · [评分检查](merging/test_tssa_mvp_score.py) | 逐图指标、选择规则及离线图像评分。 |
| [test_tssa_image_search_run.py](merging/test_tssa_image_search_run.py) · [资源快照检查](merging/test_tssa_resource_snapshot.py) | 搜索/确认预算和资源计数字典快照，修复不改写旧审计结果。 |
| [目标语义运行检查](merging/test_tssa_target_semantic_run.py) · [运行库检查](merging/test_tssa_target_semantic_runtime.py) · [门禁检查](merging/test_tssa_target_semantic_gates.py) | 权限/资源保护、缓存来源、真实微型梯度、诊断枚举及停止规则。 |
| [训练轨迹独立审计](../results/tssa-mvp-2026-10-26/audit_training_trace_2026-10-28.py) · [持出独立审计](../results/tssa-mvp-2026-10-26/audit_final_heldout_20261028T0602Z.py) | 从已返回记录复算优化器、候选及评价，不运行研究样本。 |
| [图像搜索结果审计](../results/tssa-opt-exploration-2026-10-28/audit_image_search_results.py) · [诊断原始产物审计](../results/tssa-target-semantic-diagnostic-2026-10-28/audit_diagnostic_artifacts.py) | 核对逐图/逐单元证据及哈希；科学门禁失败和证据完整性分开报告。 |

检查数量与通过状态属于具体版本及运行日期，详见各轮结果目录；不要用早期“完整模型/离线环境/GPU尚未验证”的准备记录覆盖后来完成的证据。

## 基准复现与历史维护

| 脚本 | 用途 |
|---|---|
| [audit_backdoordm_completion.py](reproduction/audit_backdoordm_completion.py) | 检查 BackdoorDM 模型产物、结果文件、指标与样本量。 |
| [run_invi_mse_stream.py](reproduction/run_invi_mse_stream.py) | 逐张计算 InviBackdoor 生成图的 MSE，降低评估内存需求。 |
| [run_invi_posttrain_eval.sh](reproduction/run_invi_posttrain_eval.sh) | 历史 InviBackdoor 训练后评估入口，含训练完成检查与旧生成目录清理。 |
| [run_queued_gpu_fixes.sh](reproduction/run_queued_gpu_fixes.sh) | 历史排队修复与评估任务，包含重训、FID 和防御评估。 |
| [fix_gpu_config.py](reproduction/fix_gpu_config.py) | 修改远端 BackdoorDM 的 BiBadDiff 训练入口配置。 |
| [patch_bibaddiff.sh](reproduction/patch_bibaddiff.sh) | 对远端 BiBadDiff 源文件应用历史兼容补丁。 |
| [run_bibaddiff.sh](reproduction/run_bibaddiff.sh) | 使用脚本内指定路径与配置启动 BiBadDiff 训练。 |

原根目录的 patch/fix 脚本会修改文件，run 脚本会启动训练；本次整理没有执行它们，也没有确认历史服务器环境仍然可用。

## Checkpoint 合并与历史攻击实验

| 脚本 | 用途 |
|---|---|
| [merge_tracer.py](merging/merge_tracer.py) | UNet 合并算子与差分诊断，支持导出权重或完整 pipeline。 |
| [merge_unet_state_dicts.py](merging/merge_unet_state_dicts.py) | UNet 权重组合、产物记录与可选 BackdoorDM 评估。 |
| [merge_text_encoder.py](merging/merge_text_encoder.py) | 文字编码器合并、差分放大与原 TSSA 选择性缩放。 |
| [apply_tssa_unet.py](merging/apply_tssa_unet.py) | 对已有 UNet 差分进行统一或 TSSA 选择性放大。 |
| [run_merge_degradation.py](merging/run_merge_degradation.py) | 扫描合并条件并调用 BackdoorDM 评估 ACC/ASR。 |
| [analyze_degradation.py](merging/analyze_degradation.py) | 汇总合并退化 CSV，生成报告与图表。 |
| [train_merge_robust.py](merging/train_merge_robust.py) | 历史 UNet 合并鲁棒训练尝试。 |
| [train_te_merge_robust.py](merging/train_te_merge_robust.py) | 历史文字编码器合并鲁棒训练尝试。 |
| [post_m3_eval.sh](merging/post_m3_eval.sh) | 历史 M3 训练后比较与汇总入口。 |
| [eval_rick_full.sh](merging/eval_rick_full.sh) | Rickrolling 历史训练模型与缩放模型的比较评估。 |
| [run_rick_te_grid.sh](merging/run_rick_te_grid.sh) | Rickrolling 文字编码器合并网格实验。 |
| [run_tssa_grid.sh](merging/run_tssa_grid.sh) | 原 TSSA 与统一放大的历史网格比较。 |
| [run_tssa_res_test.sh](merging/run_tssa_res_test.sh) | 原 TSSA 未选中差分组的残余缩放实验。 |
| [run_tssa_multi_attack.sh](merging/run_tssa_multi_attack.sh) | 将 UNet 差分增强应用于多种已有攻击的历史比较。 |

## 连接、离线部署与资料回传

| 工具 | 用途与执行边界 |
|---|---|
| [archive_school_research.py](connection/archive_school_research.py) | 只读盘点和回传学校服务器既有科研资料，按文件清单核对大小与哈希；不下载新模型或启动实验。 |
| [probe_school_gpu.py](connection/probe_school_gpu.py) | 有界只读检查已配置学校节点的连接、GPU身份及进程；暂停期间不做定期探针。 |
| [start_school.sh](../server/start_school.sh) · [school_ssh_config](../server/school_ssh_config) | 学校跳板与节点连接、动态DNS回退及主机密钥检查。 |
| [stage_school_assets.py](../server/stage_school_assets.py) | 固定公开revision逐文件下载、中转上传及远端哈希核验，不选择GPU；当前不启动新资产下载。 |
| [install_school_offline_env.py](../server/install_school_offline_env.py) | 验证冻结Linux依赖后安装本人数据盘环境；104和103各轮实际环境证据见运行记录。 |
| [中转检查](../server/test_stage_school_assets.py) · [分块检查](../server/test_stage_school_chunk_upload.py) · [安装器检查](../server/test_install_school_offline_env.py) | 本机CPU检查传输恢复、文件完整性、路径限制和离线安装，不证明实时连接可用。 |
| [start_amax.sh](connection/start_amax.sh) | macOS AMAX隧道与交互连接，包含DNS回退和网页就绪检查；当前端口以用户最新提供为准。 |
| [start_amax - ip.bat](<connection/start_amax - ip.bat>) | Windows历史AMAX连接辅助，未经本轮运行核验。 |

AMAX启动器默认转发网页到`http://127.0.0.1:8080`、HTTPS到`8443`，保留DNS回退与主机密钥校验；该连接信息仅为工具说明，不是暂停期间启动服务的要求。学校连接及远端路径见[服务器资料索引](../server/README.md)，实际许可与实验状态以[AGENTS.md](../AGENTS.md)为准。

## 本地存储与服务器索引

当前大文件传输及实验暂停，[build_server_index.py](storage/build_server_index.py)只读本地保存的盘点并生成[服务器索引](../storage/SERVER_INDEX.md)，不连接服务器；[research_archive.py](storage/research_archive.py)核验本地ZIP及逐文件清单，并恢复到指定目录。

[restore_from_catalog.py](storage/restore_from_catalog.py)提供清单浏览和已完成云端往返包的批量恢复，当前仅核心历史快照符合该条件；[prepare_research_backup.py](storage/prepare_research_backup.py)只负责限定科研目录内的本地打包，不代表已上传，也不应在暂停期间盲目重建相同快照。

[fetch_server_file.py](storage/fetch_server_file.py)在新电脑按103/104文件索引取回单个已知哈希文件，默认仅展示计划，显式`--download`才只读连接并验哈希；缺SHA的历史条目不假装可验收下载，详见[换机步骤](../storage/NEW_COMPUTER.md)。

[build_retrieval_catalog.py](storage/build_retrieval_catalog.py)合并冻结历史附件、新登记附件、论文目录和已有服务器映射；[maintain_index.py](storage/maintain_index.py)提供变更影响、生成文件清单和收尾检查，[install_index_hook.py](storage/install_index_hook.py)只为当前仓库启用提交校验。维护规则与操作顺序见[索引维护入口](../storage/INDEX_MAINTENANCE.md)，新附件不能因被Git忽略而遗漏。

存储回归检查：[归档恢复](storage/test_research_archive.py) · [目录恢复](storage/test_restore_from_catalog.py) · [服务器单文件取回](storage/test_fetch_server_file.py) · [附件目录生成](storage/test_build_retrieval_catalog.py) · [维护门禁](storage/test_maintain_index.py)，均可离线运行；被Git忽略的嵌套仓库目录仅接受明确的本地排除，不按普通附件放行。

## 路径与部署说明

旧根目录脚本与`server/`内20个历史脚本以相对符号链接指向`scripts/`，但`server/`同时保存学校连接、离线部署、测试和状态等真实文件，不能把整个目录视为兼容链接。远端历史部署仍涉及`/opt/data/private/server/`与`/opt/data/private/BackdoorDM/server/`，本次本地整理未迁移远端内容。

打包或核对历史部署时应保留真实源文件、协议及哈希，单独打包符号链接可能遗漏目标；执行记录、回传工具和一次性审计脚本保留在对应`results/`目录，避免改动已经冻结的证据路径。

[项目总索引](../README.md) · [研究目录](../research/README.md) · [结果索引](../results/README.md)
