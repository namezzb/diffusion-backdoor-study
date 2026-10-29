# 目标语义诊断：已完成，实验已暂停

2026-10-29完成96个诊断单元，D3梯度一致性及局部可行性失败；1141份产物已回传，9242项证据审计通过，GPU已释放，用户要求暂停。见[诊断报告](target_semantic_diagnostic_report_2026-10-29.md)及[全部尝试总结](../../research/tssa_attempts_summary_2026-10-29.md)，下文仅为历史准备记录。

# 目标语义诊断准备记录

2026-10-28 20:19，独立诊断实现与完整模型CPU预检已通过，尚未启动GPU；新科学图片、优化更新、新轨迹和实测诊断前后向计数均为0，不能据此宣称ASR提升。

诊断检验两个旧fit状态上的目标语义信号、真实a/b梯度和局部正常响应代价，独立硬上限为462次UNet分支前向、96次TE批调用、14次autograd、44次UNet分支反向及14次TE反向；最多一张合规24GiB卡、1800秒，不自动重试、出图或训练，完整定义见[方案](../../research/tssa_target_semantic_diagnostic_proposal_2026-10-28.md)。

| 证据 | 当前结论 |
|---|---|
| [本机46项检查](CPU_tests_46_20261028.json) | 微型CPU模型、门禁及执行账本检查通过，不替代完整SD CUDA证据 |
| [104准备回执](cpu_preparation_20261028T121710965740Z/report.json) | 服务器46项检查和完整模型CPU预检通过，CUDA始终隐藏 |
| [完整模型CPU预检](cpu_preparation_20261028T121710965740Z/cpu_preflight.json) | 19项加载文件哈希、原参数域/分组、逐tensor哈希与缓存来源核验通过；未加载Ehold、VAE或评分器 |
| [四条缓存来源审计](cache_retrieval_20261028T115206383909Z/report.json) | 原receipt、原.pt及四个step13 tensor已只读回传 |
| [本机独立派生复核](local_cache_derivation.json) | 四个原envelope重新提取的tensor原始字节完全相同 |
| [当前断点](progress_state.json) | 不可用旧实验预算或旧网页许可启动新任务 |

完整CPU预检SHA256为`a0a10bc6d1e64b3623b6500080973c306935d35793a84779cfdfc74857cccdef`，部署包SHA256为`8d0e31b32ffb00e00e8634f9edc3b9ae8f77f86ce775b9f191119a22595513b1`；远端准备目录为`/data2/zhangzibo/arxiv-tssa/preparations/target-semantic-20261028T121710965740Z`，本次未修改旧run或旧模型文件。

前两次CPU准备失败原样保留：第一次为测试目录布局问题，第二次为已知上传残留被严格文件域拒绝；修复只识别两个已观察、本人拥有的普通残留文件并记录元数据，不读取/删除它们，其他未知文件仍拒绝。

20:20仍检测到Mac锁屏、Chrome停在空白页，无法取得实时用卡证据；解锁并恢复GPU网站后，核对本人总额度、禁用、预留和进程，再固定唯一服务器/完整UUID/执行清单和永久claim后启动，不能直接沿用旧GPU编号。

2026-10-29 09:42：用户解锁后核验网站本人0/4、103 GPU2空闲且无103排队/禁用，新的54项CPU检查与完整模型预检通过，已冻结唯一执行清单并启动PID310107；初始处于CPU重新加载，真实CUDA及结果待回执。启动前修复仅针对已核验系统gdm/Xorg的跨UID exe读取限制，完整进程身份仍逐次匹配；SSH255的准备传输失败和已完成预检的只读回收证据分别保留。
