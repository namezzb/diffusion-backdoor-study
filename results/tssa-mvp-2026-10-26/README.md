# TSSA 本轮验证与准备证据

2026-10-28完整验证已结束：1520张科研图、三族144次优化，RC/Uniform持出ASR均为0，TSSA无合格候选；GPU任务已自动退出，以下最新入口优先于后面的历史准备记录。

| 最新证据 | 含义 |
|---|---|
| [术语与三轮结果解释](../../research/tssa_methods_and_results_explained_2026-10-29.md) | Uniform4/TSSA16、系数、指标和结论用普通话说明 |
| [终态原始指标与轨迹](single_run_observation_20261028T060221238162Z_artifacts/) | 33份已验哈希小产物；含144步优化轨迹、全部候选和持出指标 |
| [服务器全目录定位](../../storage/SERVER_INDEX.md) | 按远端原路径归档；这是有缺口的备份入口，完整性必须看下一项 |
| [回传完整性与缺口](../organization-2026-10-29/README.md) | 1520原图、完整缓存、导出检查点及执行代码的本地/远端状态 |
| [定时任务删除成功](automation_cleanup_20261028T1225Z.json) | 覆盖早期最终报告里的删除审批失败状态，旧失败证据保留 |
| [最终报告](initial_validation_report_2026-10-28.md) | 冻结协议、逐状态负结果、限制、成本与保存位置 |
| [最终回传和释放](single_run_observation_20261028T060221238162Z.json) | 33项SHA核验、全阶段完成、本人GPU进程为0 |
| [开发独立审计](development_selection_audit_20261028T0601Z.md) | 6930检查、484图逐项核验、0不一致 |
| [持出独立审计](final_heldout_audit_20261028T0602Z.md) | 768图逐项指标、完整性、预算与冻结绑定核验 |
| [中期系数与损失分析](training_interim_analysis_20261028T0354Z.md) | 三族轨迹及零点行为，数值原因仍为未证实假设 |

## 历史准备记录（对应当时时间，不代表当前状态）


本目录仅保存2026-10-26晚启动的实现检查与离线准备；截至2026-10-27 09:30，**没有正式checkpoint训练、GPU评估、ASR或正常指标结果**，实时断点见[执行记录](../../research/tssa_overnight_progress.md)，09:30曾暂停，15:00已按用户新要求恢复30分钟服务器探针；汇总见[进度与网站故障说明](../../research/tssa_progress_summary_2026-10-27.md)。

| 证据 | 含义与边界 |
|---|---|
| [最新CPU检查](cpu_checks_2026-10-27-001353.json) | 56项通过，含8项双进程测试及实际CPU Adam/随机数状态迁移；正式模型、CUDA和显存仍未测试。 |
| [离线安装器检查](offline_installer_checks_2026-10-26-235946.json) | 11项本地保护检查通过，冻结51个Linux wheel；服务器尚未安装。 |
| [服务器部署及保护检查](remote_source_preparation_2026-10-27-0140.json) | 新快照在Linux Python3.11完成安装计划和11项保护测试；没有安装ML依赖、加载模型或调用GPU。 |
| [源文件部署证明](source_deployment_2026-10-27-0140.json) | 整包和20个源文件哈希通过，独立快照目录保留原始清单；不覆盖旧代码。 |
| [104环境兼容预检](remote_environment_precheck_2026-10-27-002522.json) | 现有本人数据盘Python环境、51个wheel平台标签匹配；尚未上传全部wheel、安装依赖或做ML导入。 |
| [中转检查](cpu_checks_2026-10-26-233917.json) | 12项恢复/哈希检查通过，该版代码哈希在最新CPU证据再次比对；三次断线记录均保留，后续独立连接受控对照未结束；无GPU任务。 |
| [双卡执行计划](dual_execution_plan_2026-10-27.json) | 1712张研究图、144次更新的计划枚举，未加载模型或执行GPU。 |
| [最新部署包描述](deployment_bundle_2026-10-27-0015.json) | 20个文件及包内清单逐项核对，含双卡入口和离线安装器；已上传并逐文件验收至104的新快照目录。 |
| [部署包](deployment_bundle_2026-10-27-0015.tar.gz) | SHA256 `c36b319a1f1d61c5410eb8ddbddf3c489927687f58ba75cd680757128897afc1`，只含明确选择的源文件和研究清单。 |
| [传输断线记录](asset_transfer_attempt_01_failed.json) | 首次SCP连接丢失，父子进程退出后启动单一恢复进程；保留原始日志和2.95GB远端临时文件。 |
| [第二次断线记录](asset_transfer_attempt_02_failed.json) | SFTP续传实际增长后SIGPIPE退出；小包部署成功后第三次有界恢复。 |
| [第三次断线记录](asset_transfer_attempt_03_failed.json) | 再次SIGPIPE后停止盲目重试，保留本机与远端断点，进行只读连接诊断。 |
| [2026-10-30节点观察](server-probes/school101-20261029T174605849836Z.json) · [104](server-probes/school104-20261029T174605881300Z.json) · [127](server-probes/school127-20261029T174605865081Z.json) | TCL故障后只读探针，无法代替平台许可或跨机续跑审阅。 |
| [独立SSH只读诊断](transfer_ssh_independent_probe_2026-10-27-0152.json) | 150秒与6次心跳通过，双端公钥认证成功；不能代表大文件稳定或定位断线根因。 |
| [诊断参数检查](transfer_diagnostic_option_checks_2026-10-27-0200.json) | 14项离线检查通过，含独立SFTP选项传递；不是网络故障重现或修复证明。 |
| [本机UNet资产完整性](local_sd15_unet_integrity_2026-10-27-0210.json) | 固定SHA256、大小、686个F32张量头部边界通过；未实例化模型，不构成GPU或效果验证。 |
| [受控续传对照](asset_transfer_attempt_04_started.json) | 第四次限定SD15前12文件、关闭SFTP复用并记录连接日志，UNet完成或失败即停；整套47文件仍未就绪。 |
| [独立连接失败证据](asset_transfer_attempt_04_failed.json) | 跳板端先关闭，随后目标连接Broken pipe；关闭复用未解决故障，保留全部断点。 |
| [分块恢复CPU检查](chunk_transfer_checks_2026-10-27-0225.json) | 19项通过，覆盖截断/错误块不改前缀、偏移冲突拒绝、续传和禁止自动重试；不是网络故障修复证明。 |
| [单块真实传输验收](chunk_transfer_probe_2026-10-27-0226.json) | 发送前SSH检查255退出，未发送分块；分块传输尚无服务器端验收证明。 |
| [最新只读SSH检查](transfer_ssh_probe_2026-10-27-0231.json) | 双端认证成功，但下一次前检查随即关闭；不能解释为持久在线。 |
| [第二次单块前检查](chunk_transfer_probe_2026-10-26-183218-957794Z.json) | 6.1秒后连接关闭，未发送分块；记录完整stderr且未覆盖前次失败。 |
| [本机Linux wheel预取](wheel_prefetch_2026-10-27-0236.json) | 只预取冻结torch包，持全局单任务锁且保留4GiB空间；尚未上传或安装。 |
| [当前传输进程](asset_transfer_process.json) | 当前PID和日志入口，避免读取旧日志或重复启动；成功仍以逐文件哈希记录为准。 |
| [传输逐文件记录](asset_transfer.jsonl) | 只有已记录且远端大小/哈希一致的文件算传输成功，进行中的`.uploading`不算就绪。 |

科学协议SHA256固定为`8f74590f12514f63239448783adc6187422518defc52ec46f014ffb99887e48c`；双卡执行另冻结两张授权UUID及任务分配，不变更样本、损失、训练步数、门槛或持出选择。

早期单卡包和检查记录保留为历史版本，不覆盖；真实CUDA随机数恢复、双3090显存与主存峰值、父进程被SIGKILL后的自动退出仍未实测，不能用本机模拟结果替代。

- 02:54 torch单包本机SHA/大小/标签验收见[预取报告](wheel_prefetch_2026-10-27-0236.json)，未上传/安装；02:56另有39个小包共83.82MB的[本机预取报告](small_wheel_prefetch_2026-10-26-185630-816483Z.json)。
- 02:55只读SSH仍被跳板关闭，见[恢复探测](transfer_ssh_probe_2026-10-26-185412-979504Z.json)；无真实GPU研究结果。

- 小包预取首轮因setuptools嵌套元数据误计数中止，已修正为顶层WHEEL，原失败记录保留；当前[接续报告](small_wheel_prefetch_2026-10-26-185746-918367Z.json)复用已下载文件。

- 02:59 [小包接续](small_wheel_prefetch_2026-10-26-185746-918367Z.json)已完整验收39/39，加torch共40/51包；03:00正在准备[3个中等CUDA依赖](medium_wheel_prefetch_2026-10-26-190045-079703Z.json)，均仅为本机文件准备。

- 03:06 [本机依赖清单](local_wheel_inventory_2026-10-27-0306.json)累计43/51个、1.314GB，全部仅本机校验；[最新只读SSH](transfer_ssh_probe_2026-10-26-190544-914047Z.json)仍失败，未启动模型续传或GPU。

- 03:20 [只读前缀探测](transfer_ssh_probe_2026-10-26-192033-056534Z.json)通过双端认证但超时，无哈希结果；03:23 [轻量文件查询](transfer_ssh_stat_probe_2026-10-26-192258-385715Z.json)在跳板握手前被断开，未续传或使用GPU。

- [03:36准备检查点](preparation_checkpoint_2026-10-27-0336.md)：集中区分已完成CPU/部署/资产准备、连接阻塞与尚未开始的真实GPU验证。

- 03:46 [只读stat](transfer_ssh_stat_probe_2026-10-26-194551-450270Z.json)成功确认本人断点；03:47的[单块验收尝试](chunk_transfer_probe_2026-10-26-194720-599662Z.json)随后在网关检查失败，未发送数据，完整UNet仍未验收。

- 2026-10-27 06:21：Linux离线依赖51/51全部本机下载及固定SHA/标签验证完成（3,909,917,779字节），见[local_wheel_inventory_2026-10-27-062211.json](local_wheel_inventory_2026-10-27-062211.json)；未完成远端传输、安装或GPU验证。

- 2026-10-27 09:00：51项Linux依赖远端SHA及离线安装/CPU导入通过，见`wheelhouse_transfer_acceptance_2026-10-27-0855.json`与`environment_install_observation_2026-10-27-010027-080918Z.json`；尚无正式模型/GPU实证。

- 2026-10-27 09:05：104实际离线环境的56项研究CPU检查通过、20份源文件哈希匹配，见`remote_research_CPU_checks_2026-10-27-010335-127738Z.json`；正式模型/GPU验证仍待资产齐备和有效分配。

- [半小时服务器探针启用记录](server_probe_automation_activation_2026-10-27.json)保存首次真实只读采样与定时器状态；104当前无无进程卡，未分配或启动GPU任务。

- 15:29探针与15:36传输失败断点（旧机页面记录，已在[排除清单](../../storage/audits/portable_publication_scope.json)登记）：104无空闲候选，24/47整文件完成；上传SSH255退出且管理站访问被公司安全验证页拦截。
- [DreamShaper8本机资产结构检查](local_dreamshaper8_unet_integrity_2026-10-27-073506-088271Z.json)：完整SHA及686个F32张量结构通过，仅资产检查。

- [16:00探针及断点核验](heartbeat_checkpoint_2026-10-27-080652-117540Z.json)：104仍无可用候选，前缀核验SSH255失败，未重启传输；已完成资产仍为24/47。
- [DreamShaper8本机数值检查](local_dreamshaper8_unet_values_2026-10-27-080445-142770Z.json)：全部859,520,964个F32值有限且在FP16有限范围内，仅资产验证。

- [16:31断点验证与16:32恢复上传](heartbeat_checkpoint_2026-10-27-083448-292847Z.json)：92,274,688字节前缀匹配后启动唯一中转，24/47整文件完成；104仍无可用候选，未使用GPU。

- 17:04连接失败与资产对账（旧机页面记录，已在[排除清单](../../storage/audits/portable_publication_scope.json)登记）：本轮SSH255未获得新GPU样本，24/47整文件已验收，DreamShaper8分块历史回执为398,458,880字节；上传已退出，本轮未重启或使用GPU。

- 17:29采样与17:32续传（旧机页面记录，已在[排除清单](../../storage/audits/portable_publication_scope.json)登记）：无可用GPU候选，398,458,880字节远端前缀核验匹配后恢复唯一中转，24/47整文件完成；平台许可仍未知。

- 17:59上传进展与GPU采样（旧机页面记录，已在[排除清单](../../storage/audits/portable_publication_scope.json)登记）：原上传持续，183个连续分块回执与本机payload哈希匹配，覆盖至1,166,016,512字节；24/47整文件完成，GPU许可与占用边界不变。

- 18:29增量核验与采样（旧机页面记录，已在[排除清单](../../storage/audits/portable_publication_scope.json)登记）：新增111块哈希通过，DreamShaper8回执覆盖至1,631,584,256字节；原上传持续、完整资产24/47，暂无可用GPU候选。
- 18:59增量核验与采样（旧机页面记录，已在[排除清单](../../storage/audits/portable_publication_scope.json)登记）：新增59块哈希通过，DreamShaper8回执覆盖至1,879,048,192字节；原上传持续、完整资产24/47，暂无可用GPU候选。

- 19:29增量核验与采样（旧机页面记录，已在[排除清单](../../storage/audits/portable_publication_scope.json)登记）：新增87块哈希通过，DreamShaper8回执覆盖至2,243,952,640字节；完整资产24/47，原上传持续，无可用GPU候选。

- 19:59增量核验与采样（旧机页面记录，已在[排除清单](../../storage/audits/portable_publication_scope.json)登记）：新增105块哈希通过，DreamShaper8回执覆盖至2,684,354,560字节；完整资产24/47，原上传持续，无可用GPU候选。

- [20:10资产验收与20:29连接失败断点](heartbeat_checkpoint_2026-10-27-123203-103611Z.json)：DreamShaper8全部传完、完整资产27/47；OpenJourney文本编码器上传SSH255退出，探针返回目标主机无路由，本轮未重连或使用GPU。
- [OpenJourney文本编码器本机完整性](local_openjourney_text_encoder_integrity_2026-10-27-123047-217543Z.json)：固定SHA、197个张量结构与六个分块字节匹配，仅资产验证。

- [20:59连接断点与本机准备](heartbeat_checkpoint_2026-10-27-130106-048562Z.json)：104仍无路由，27/47整文件证据未变；新增[OpenJourney文本编码器数值检查](local_openjourney_text_encoder_values_2026-10-27-130008-879107Z.json)覆盖123,060,480个F32值与0–76位置编号，仅资产验证。

- [21:29连接断点与小文件准备](heartbeat_checkpoint_2026-10-27-133237-673650Z.json)：104仍无路由，远端27/47；新增[15项本机支持文件验收](local_model_support_acceptance_2026-10-27-133201-522490Z.json)与20个冻结ViT类别映射检查，等待服务器恢复后逐文件上传。

