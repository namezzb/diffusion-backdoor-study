# 直接按图片搜索：已结束、无合格增益

2026-10-28完成12个预登记系数点与干净参照，共624张搜索图、192张开发图，合计816张、0次梯度更新；没有开发合格赢家，因此没有打开独立确认集。实验保持暂停，不能挪用未消耗预算恢复这个已结束运行。

| 想看什么 | 入口与含义 |
|---|---|
| 方法、名词和三轮比较 | [通俗解释](../../research/tssa_methods_and_results_explained_2026-10-29.md) |
| 结果与全部候选 | [负结果报告](direct_ASR_negative_report_2026-10-28.md) · [终态指标](terminal_metrics_20261028.json) |
| 816张原始图片 | [图片取回索引](../../storage/retrieval_catalog.jsonl)（旧机目录`final_images_816_20261028/images/`，新机按索引下载）；已逐文件核对哈希，不是只有拼图 |
| 每张图片对应什么 | [逐图清单](final_image_inventory_816_20261028T1115Z.json) · [PNG哈希验收](final_PNG_hash_acceptance_816_20261028T1115Z.json) |
| 833份终态小产物 | [原始产物目录](observation_103_20261028T111524087743Z-7268ad87/artifacts/)；包含逐图记录、选择、预算和操作证据 |
| 原科学方案与范围 | [冻结记录](freeze_20261028.json) · [研究断点](../../research/tssa_optimization_exploration_progress_2026-10-28.md) |
| 当时执行的代码 | [原代码包](source-6913379cd01c.tar.gz) · [缺陷修复前快照](frozen_code_before_resource_snapshot_fix/)；现行源码见[脚本索引](../../scripts/README.md) |
| 数值与完整性审计 | [严格审计](independent_result_audit_816_20261028T1115Z.json) · [643项哈希差异诊断](summary_record_hash_diagnosis_20261028.json) |
| 旧目标为何偏好零差分 | [目标诊断](objective_diagnosis.md) |
| 远端全目录是否补齐 | [本次备份目录](../organization-2026-10-29/README.md)；833项产物不是服务器整个项目目录的镜像 |

原严格审计状态保持 **invalid（未通过）**：643项汇总哈希差异源于资源计数浅拷贝；逐图数值与选择的独立复算一致，但没有重新运行图像评分器，不能把这个缺陷改写成审计通过。

搜索最好的统一1.5倍得到58.33%攻击率，比同轮原始后门基线50%高，但正常能力不合格；两名开发候选均33.33%，与同轮基线相同且正常约束失败。上述两批材料不同，不能拿58.33%与33.33%直接比较方法退步。

历史传输中断包和续传包保留作为故障证据，不作为可用图片数量重复计数；当前可用图片以816项完整PNG清单为准。
