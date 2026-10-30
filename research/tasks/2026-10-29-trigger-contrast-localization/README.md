# 特殊字符触发参数定位任务

本目录保存独立任务的设计、交接和审阅记录；完成与待完成状态、当前方法及预算统一见[TASK.md](TASK.md)。通用规范只维护在[AGENTS.md](../../../AGENTS.md#任务管理规范)，本页不复制任务状态。

| 入口 | 用途 |
|---|---|
| [TASK.md](TASK.md) | 扩大样本后的任务定义、里程碑、实现交付要求和review入口 |
| [首版样本草案](prompts_draft.jsonl) | 独立审阅未通过：动作不足、个别场景与构图不自然、other对象不合适，且存在跨分区近重复；不作为冻结输入 |
| [第二版样本草案](prompts_draft_v2.jsonl) | 改为狗、猫、兔动作配对；自查仍发现跨分区近重复，未进行正式独立审阅，不能作为冻结输入 |
| [第四版样本草案](prompts_draft_v4.jsonl) | 在第二版上按预先固定的机械目标重分区；自查仍发现跨分区高度相似的模板，不能作为冻结输入 |
| [第八版样本候选](prompts_draft_v8.jsonl) · [内容审阅记录](context_review.json) | 320条文本及分层已独立审阅通过；冻结候选已绑定token、seed和38项服务器SHA观察，最终M06与实际预检仍待完成 |
| [逐条分词候选](prompts_tokenized_candidate.jsonl) · [早期清单草案](manifest_draft.json) | 已保存并核对每条77位token；早期草案的缺项由冻结候选接续，真实预检仍未完成 |
| [冻结清单](manifest_candidate.json) · [实现检查](implementation_validation.md) · [M06审阅](m06_review.json) | 清单绑定输入、38项观察SHA及代码；实现与M06通过，真实CUDA和评分仍待验证 |
| [103资产观察](server103_assets_observation_20261029.json) · [CPU预检](server103_cpu_preflight_20261029.json) | 38项SHA与历史来源一致，CPU加载及样本检查通过；预检依赖与现版一致，不代表GPU前向或图片验收 |
| [103早版运行包验收](server103_deployment_20261029.json) · [新版GPU门禁检查](server103_gpu_guard_20261029.json) | 早版已上传但不得启动；新版门禁已在103只读实测，CPU加载后仍须重新核对平台 |
| [103新版运行准备](server103_run_preparation_20261029.json) | 新版部署及CPU阶段启动回执，CUDA许可与模型前向须以实际运行证据为准 |
| [实时资源观察](server103_resource_observation_localize_20261029.json) · [定位启动](server103_localization_start_20261029.json) | GPU许可及真实定位前向的启动证据，执行状态和后续结论以TASK为准 |
| [定位中断证据](server103_localization_interruption_20261029.json) | 幅度对照空路径触发执行错误，已完成前向及未决恢复条件 |
| [追加修订及审阅](AMENDMENT_REVIEW.md) · [签名批准](amendment_approval.json) | 空路径修复、原始哈希与独立签名，CPU验证后需重新核对GPU许可 |
| [恢复资源观察](server103_resource_observation_resume_20261029.json) · [恢复回执](server103_amendment_resume_20261029.json) | 独立验签及新的实时资源门禁通过，后续前向和终态需另行核验 |
| [定位终态观察](server103_localization_terminal_observation_20261029.json) | 107520次前向及六组对照完成，远端终态与选择文件哈希；图片效果仍待确认 |
| [确认资源观察](server103_resource_observation_confirm_20261029.json) · [确认准备](server103_confirm_preparation_20261029.json) | CPU预检及确认阶段GPU门禁通过，完整基线仍待核验 |
| [127 Xorg误拦截](server127_gpu_gate_interruption_20261030.json) · [修订交接](RESOURCE127_HANDOFF.md) · [独立签名](resource127_review.json.sig) | gdm系统显示进程身份复核，限定兼容修订经签名、测试及只读实测；GPU和图片仍须另验 |
| [127见证等待修订](SHARD127_WAIT_HANDOFF.md) · [签名审阅](shard127_wait_review.json) · [重启记录](server127_wait_resume_20261030.json) | 网络短暂中断时有界等待新鲜见证；成功验签缓存仍逐次检查时效与身份 |
| [127见证中断](server127_witness_interruption_20261030.json) · [图片索引](../../../storage/server-index/127-tcl-v1-shard-images-20261030.jsonl) | 3张图片已评分并验证SHA；见证过期导致新增1条中断，修订待审阅 |
| [127路径修复启动](server127_pathfix_resume_20261030.json) · [平台观察](server127_resource_observation_pathfix_20261030.json) | CPU预检及新许可通过，CUDA加载和选择复算中，首图待核验 |
| [127导入中断](server127_import_interruption_20261030.json) | 首键登记后导入失败，0前向和图片；固定路径已验证，已计费键不可重试 |
| [127 CPU准备](server127_cpu_preparation_20261030.json) | 重试已通过源观察并进入CPU资产加载，GPU许可尚待实时核查 |
| [127观察控制器v2草案](shard127_watch_controller_v2.py) | 并行观察与合并发布候选，尚未独立审阅或部署；当前使用原签名版本 |
| [127分片交接](SHARD127_HANDOFF.md) · [候选](shard127_plan_candidate.json) · [审阅](shard127_review_envelope.json) | 原预算内1704个未尝试键，双源短时观察和104锁保护；104及103原执行禁止重启 |
| [127准备中断](server127_preflight_interruption_20261030.json) · [104 CUDA失败](server104_cuda_failure_20261030.json) | 127初次因观察过期在建账本前退出，104 CUDA初始化失败；两者均0次出图 |
| [104门禁追加修订审阅](resource104_review.json) · [签名](resource104_review.json.sig) | 限定核验gdm系统图形进程；不改变原冻结门禁 |
| [104门禁中断观察](server104_resource_gate_interruption_20261030.json) | 原门禁未识别gdm系统图形进程，0次出图；CPU日志含CUDA初始化警告 |
| [104分片CPU预检启动](server104_shard_preflight_start_20261030.json) · [候选与审阅](shard104_review_envelope.json) | 固定1704互斥键，签名校验通过；GPU许可与出图须另验 |
| [104分片交接及校验](SHARD104_HANDOFF.md) | 基于已验证快照准备1704项分片；跳板恢复后仍须候选计划和独立审阅 |
| [104资产及环境观察](server104_asset_compatibility_20261030.json) | 38项资产哈希匹配，主要依赖可CPU导入；尚无迁移或GPU启动许可 |
| [103设备故障与盘点](server103_gpu_failure_20261030.json) | 343张完成图哈希核对、一次中断及原锁未释放；恢复受设备与预算约束 |
| [源阶段首批与耗时](server103_source_initial_images_20261029.json) | 首批62张带分数，抽样文件哈希核验及基线耗时估算；不代表基线已通过 |
| [运行入口与验收报告](../../../results/trigger-contrast-localization/tcl-20261029-01-v1/README.md) | 运行中的报告和服务器路径，终态后须补齐独立审阅与附件盘点 |
| [初始小样本草案](../../trigger_contrast_localization_pilot_review_2026-10-29.md) | 保留思路演变，旧2048图预算不再作为本任务预算 |
| [相关文献调研](../../../reports/trigger_contrast_parameter_localization_review_2026-10-29.md) | 行为定位、语义混杂、因果贡献与合并迁移的来源和证据边界 |
| [既有模型来源](../../tssa_mvp_assets_2026-10-26.json) · [既有源配置](../../tssa_mvp_2026-10-26.json) | 取用已固定模型身份和真实触发规则，不继承旧样本、旧预算或旧run身份 |

任务代码见[scripts/merging/trigger_contrast_localization](../../../scripts/merging/trigger_contrast_localization/README.md)，服务器产物以冻结候选中的本人数据盘路径为准，定位已完成而图片确认受阻。大模型与原图继续遵循[存储入口](../../../storage/README.md)，不放入本任务目录冒充已归档小文件。

[全部任务](../README.md) · [研究目录](../../README.md)

- [启动阶段等待 v2 候选交接](SHARD127_WAIT_V2_HANDOFF.md)：待独立审阅，未部署，不影响正在运行的版本。
