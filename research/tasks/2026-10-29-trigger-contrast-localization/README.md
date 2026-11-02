# 特殊字符触发参数定位任务

本目录保存独立任务的设计、交接和审阅记录；完成与待完成状态、当前方法及预算统一见[TASK.md](TASK.md)。通用规范只维护在[AGENTS.md](../../../AGENTS.md#任务管理规范)，本页不复制任务状态。

接手先读[24小时多卡协议](PILOT24_PROTOCOL_2026-11-02.md)：独立v2运行须按实现审阅入口固定真实来源与生产bundle，不能套用v1验收。下表及表后列表的启动、许可和待验证描述属于各回执时点，不代表当前运行状态；v1不再补满原预算，旧分片不得重放。

| 入口 | 用途 |
|---|---|
| [104 v2 CPU终态](server104_pilot24_terminal_20261102.json) | CPU定位复核错误、原始终态、T0、退出证据及导入计数 |
| [104 v2修订代终态](server104_pilot24_recovery_terminal_20261102.json) | CPU预检通过，GPU被他人占用导致实时许可检查拒绝，0次新增 |
| [v2修订review](PILOT24_RUNTIME_REVIEW_20261102.md) | 浮点规约差异、原始排名保护及两代终态后恢复代码的独立审阅 |
| [104链式恢复代码部署](server104_pilot24_recovery_v2_code_deployment_20261102T0858Z.json) | 隔离副本和四个已审阅代码的哈希回执；未创建生产bundle或启动GPU |
| [104真实资产CPU核验](pilot24_cpu_real_mask_audit_20261102.json) · [原始输出](pilot24_cpu_real_mask_audit_20261102.stdout.txt) | 修订候选对六组冻结mask复核通过，未初始化CUDA |
| [104原账本恢复前核验](server104_pilot24_recovery_guard_20261102T0828Z.json) | 短时持锁核对原T0、363导入及0次新增，未启动GPU |
| [TASK.md](TASK.md) | 扩大样本后的任务定义、里程碑、实现交付要求和review入口 |
| [24小时多卡协议](PILOT24_PROTOCOL_2026-11-02.md) | 当前v2运行设计：固定样本与复用规则、多卡分片、吞吐门禁、截止报告及交付要求 |
| [v2设计候选](pilot24_plan_candidate.json) · [确定性语境ID](pilot24_context_ids.json) | 6144图容量、单seed和输入绑定规则；没有实际worker与执行批准，不是可启动manifest |
| [v2实现review与部署步骤](PILOT24_IMPLEMENTATION_REVIEW.md) · [检查证据](pilot24_implementation_validation_20261102.json) | 单机常驻多卡执行链、真实来源认证要求、准备器入口和代码摘要；不代替生产bundle批准 |
| [真实来源独立审阅](PILOT24_SOURCE_REVIEW_20261102.md) | 104只读来源包认证363张候选；生产bundle和GPU许可尚未审阅 |
| [本轮环境观察](pilot24_environment_observation_20261102.json) | 当前平台规则与资源页面、终端网关失败及不能据此推断103退出的边界 |
| [v2接手核验](PILOT24_INTAKE_2026-11-02.md) | 103不可达、104六掩码复核、候选交集与执行器剩余缺口，不能当作实际导入或review批准 |
| [逐键复用候选](pilot24_reuse_candidates_20261102.json) · [PNG解码记录](pilot24_candidate_decode_20261102.json) | 固定seed的363个候选逐键记录来源、图片哈希和评分；未证明103隔离或完成v2导入 |
| [v2结果入口](../../../results/trigger-contrast-localization/tcl-20261102-pilot24-v2/README.md) | 执行准备与结果入口；详细完成与待完成状态只见TASK |
| [104快照图片审计](server104_recovery_image_audit_20261102.json) · [127图片审计](server127_recovery_image_audit_20261102.json) · [旧账本预览](recovery_provisional_keys_20261102.json) | 实现agent新增v1来源核验，预览明确不可执行；不证明原103已退出，也不是v2已导入结果 |
| [历史恢复指导](RECOVERY_HANDOFF_2026-11-02.md) | v1对账及中断处置参考，原有限预算修订未获批准，不再作为当前启动路线 |
| [首版样本草案](prompts_draft.jsonl) | 独立审阅未通过：动作不足、个别场景与构图不自然、other对象不合适，且存在跨分区近重复；不作为冻结输入 |
| [第二版样本草案](prompts_draft_v2.jsonl) | 改为狗、猫、兔动作配对；自查仍发现跨分区近重复，未进行正式独立审阅，不能作为冻结输入 |
| [第四版样本草案](prompts_draft_v4.jsonl) | 在第二版上按预先固定的机械目标重分区；自查仍发现跨分区高度相似的模板，不能作为冻结输入 |
| [第八版样本候选](prompts_draft_v8.jsonl) · [内容审阅记录](context_review.json) | 320条文本及分层已独立审阅通过；后续冻结与M06证据见下行，不以早期草案状态覆盖实际进度 |
| [逐条分词候选](prompts_tokenized_candidate.jsonl) · [早期清单草案](manifest_draft.json) | 已保存并核对每条77位token；早期草案仅供追溯，实际输入以冻结清单为准 |
| [冻结清单](manifest_candidate.json) · [实现检查](implementation_validation.md) · [M06审阅](m06_review.json) | 清单绑定输入、38项观察SHA及代码；M06已通过且已有真实定位与部分图片，完整效果仍待验收 |
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
| [运行入口与验收报告](../../../results/trigger-contrast-localization/tcl-20261029-01-v1/README.md) | 未完成验收的运行记录和服务器路径，终态后须补齐独立审阅与附件盘点 |
| [初始小样本草案](../../trigger_contrast_localization_pilot_review_2026-10-29.md) | 保留思路演变，旧2048图预算不再作为本任务预算 |
| [相关文献调研](../../../reports/trigger_contrast_parameter_localization_review_2026-10-29.md) | 行为定位、语义混杂、因果贡献与合并迁移的来源和证据边界 |
| [既有模型来源](../../tssa_mvp_assets_2026-10-26.json) · [既有源配置](../../tssa_mvp_2026-10-26.json) | 取用已固定模型身份和真实触发规则，不继承旧样本、旧预算或旧run身份 |

任务代码见[scripts/merging/trigger_contrast_localization](../../../scripts/merging/trigger_contrast_localization/README.md)，服务器产物以冻结候选中的本人数据盘路径为准，定位已完成而图片确认受阻。大模型与原图继续遵循[存储入口](../../../storage/README.md)，不放入本任务目录冒充已归档小文件。

[全部任务](../README.md) · [研究目录](../../README.md)

- [启动阶段等待 v2 候选交接](SHARD127_WAIT_V2_HANDOFF.md)：已独立审阅并部署，CPU准备已启动。

- [见证控制器 v2 只读审阅](SHARD127_WATCH_V2_REVIEW.md)：该次审阅时使用v1，v2候选未批准；后续切换及当前状态见TASK。

- [127见证JSON中断与62张图核验](server127_json_interruption_20261030T0352Z.json)：真实错误、保留账本并定位修复。

- [见证发布修复候选](shard127_watch_controller_safe_candidate.py)与[签名审阅](shard127_safe_publisher_review.json)：更新前核对摘要，原验签、身份、时效和预算不变。

- [10月30日历史进度摘要](progress_summary_20261030.md) · [恢复中断证据](server127_resume_interruption_20261030T0449Z.json)：12:49许可后见证过期，未新增尝试。

- [启动等待v2准备证据](server127_wait_v2_preparation_20261030T0502Z.json) · [签名审阅](shard127_wait_review_v2.json)：保留既有中断键及预算。

- [127等待v2实时许可](server127_wait_v2_permit_20261030T0506Z.json) · [平台观察](server127_resource_observation_20261030T0506Z.json)：许可通过后模型加载。

- [127等待超时与63图核验](server127_witness_timeout_20261030T0512Z.json)：见证等待90秒超时后退出，保留新增中断键。

- [并行见证v3发布候选](shard127_watch_controller_v3_candidate.py) · [签名审阅及影子观察](shard127_controller_v3_review.json)：单发布者切换，GPU许可与新图待核验。

- [127并行见证v3实时许可](server127_v3_permit_20261030T0521Z.json) · [平台观察](server127_resource_observation_20261030T0520Z.json)：许可通过后模型加载。

- [127并行见证续跑观察](server127_v3_running_20261030T0525Z.json)：67张完成图逐项核对哈希，保留4条127中断记录。

- [11月2日只读回查](server127_witness_timeout_20261102_observation.json)：127超时退出，103当前连接拒绝；恢复需核验互斥与实时许可。
