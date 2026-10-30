# 扩散模型后门研究：项目总索引

更新于2026-10-30。**特殊字符定位任务的103定位已完成；源基线因GPU故障中断，104 CUDA初始化失败、127分片完成62图后发生见证错误，等待修订已通过GPU许可并加载模型，原进程锁仍未释放。** 三轮历史实验共生成2,336张完整图、完成144次优化更新，尚无“正常能力达标，同时攻击成功率超过同轮基线”的合格方案。

## 从这里开始

| 要做什么 | 入口 |
|---|---|
| 查看特殊字符触发定位任务及验证进度 | [当前任务TASK.md](research/tasks/2026-10-29-trigger-contrast-localization/TASK.md) · [全部任务与模板](research/tasks/README.md)，状态、扩样预算及交接要求以任务正文为准 |
| 判断输入对比是否能改进后门参数分组 | [新筛选假说与相关文献](reports/trigger_contrast_parameter_localization_review_2026-10-29.md)：尚未实验验证，不替换当前执行方案 |
| 先看做过什么、效果如何、Uniform4 / TSSA16 是什么 | [通俗解释与全部结果](research/tssa_methods_and_results_explained_2026-10-29.md) |
| 看数据、代码、图片在哪里，以及哪些尚未回传 | [本次整理与备份目录](results/organization-2026-10-29/README.md) |
| 换电脑后让agent接续进度并取数据 | [新电脑接续步骤](storage/NEW_COMPUTER.md) · [服务器资料索引](storage/SERVER_INDEX.md) · [存储与恢复](storage/README.md) · [完整方案](research/research_storage_and_restore_plan_2026-10-29.md)，先通过Git取得进度与索引，大文件按需从本人服务器取回；Drive保持暂停 |
| 查每个文件归属、以后如何防漏更 | [索引维护入口](storage/INDEX_MAINTENANCE.md) · [全仓文件清单](storage/repository_index.jsonl) · [本次收尾记录](storage/maintenance/latest.json) |
| 按实验轮次查原始证据 | [三轮结果索引](results/README.md) |
| 查看已执行TSSA方法、公式和原验证协议 | [历史 TSSA 执行方案](research/tssa_response_calibration_method_proposal.md) |
| 查原实验如何准备 | [历史准备清单](research/experiment_preparation.md) |
| 查论文和待补文献 | [24 篇本地论文索引](papers/README.md) · [待下载清单](papers/download_queue.md) |
| 看以前复现到哪一步 | [BackdoorDM 复现索引](reproduction/README.md) |
| 看以前合并实验的结果 | [结果索引与证据说明](results/README.md) |
| 找脚本 | [脚本索引](scripts/README.md) |

## 目录地图

```text
arxiv/
├── README.md                 总索引
├── AGENTS.md                 项目指令；CLAUDE.md 导入此文件
├── research/                 当前方案、研究进度、实验准备
│   └── tasks/                独立任务、完成／待完成状态与交接入口
├── reproduction/             基准参考、复现进度、代码论文对照、循环流程
├── papers/                   论文索引和待下载清单
│   ├── pdf/                  24 篇 PDF，按 ID 命名
│   ├── txt/                  已有全文提取和页面快照
│   └── metadata/             两份历史检索数据
├── reports/                  历史综述、思路和机制分析
│   └── archive/              上一版方法的只读封存
├── results/                  实验结果入口
│   ├── tssa-mvp-2026-10-26/  第一轮：梯度优化、固定倍数和独立持出
│   ├── tssa-opt-exploration-2026-10-28/  第二轮：直接按图片搜索
│   ├── tssa-target-semantic-diagnostic-2026-10-28/  第三轮：新目标诊断
│   ├── server-archive-2026-10-29/  按服务器原路径归档，完整性见整理目录
│   ├── organization-2026-10-29/    本次文件清单、哈希、缺失项与索引快照
│   └── merging/              历史合并报告与可视化
├── scripts/                  脚本入口
│   ├── reproduction/         复现审计、补评和历史维护
│   ├── merging/              历史合并及 TSSA 脚本
│   └── connection/           学校/AMAX连接、只读盘点与回传
├── server/                   现行学校配置与部署工具，兼有脚本兼容链接
├── simulations/              合成仿真与历史图
├── presentations/            历史汇报 PPT 和生成脚本
└── archive/                  早期实验原始材料、此次整理记录
```

常用内容控制在一至两层；历史原始路径与封存内容保持原样，用索引和明确入口归类，避免移动文件破坏冻结清单。根目录旧文档、`data/` 和报告编号目录中的兼容链接不是重复副本；`server/`还包含真实的现行配置和工具，见[服务器索引](server/README.md)。

## 已有基础与当前缺口

| 项目 | 当前可确认的状态 |
|---|---|
| 本地论文 | 24 篇 PDF 均可读，无相同 SHA-256 的重复文件；题名按 PDF 首页核对 |
| BackdoorDM | 本地 2026-07-24 严格汇总记录 15/16 有模型、13/16 完整闭环、5/5 防御已执行；本次未重新核验服务器 |
| 基准缺口 | `eviledit_numAdd`、`badt2i_objectAdd` 各缺正式 10K FID；`villandiffusion_cond` 缺数据 |
| 历史合并实验 | 已有探索结果，但样本协议、模型来源和实现范围有差异；不能据此判定新方法有效或达到 SOTA |
| 当前 TSSA 梯度版 | 已实现并完成1520图/144更新；当前固定配置负结果，RC/Uniform持出ASR均0、TSSA无合格候选 |
| 后续直接ASR探索 | 已完成816图/0更新；开发候选与naive均33.33%，正常约束未通过，见[负结果及完整性缺陷](results/tssa-opt-exploration-2026-10-28/direct_ASR_negative_report_2026-10-28.md) |
| 目标语义诊断 | 已完成462次去噪网络分支前向、0图/0更新；目标端点排序改善，但梯度一致性与八点局部可行性均未通过，见[诊断报告](results/tssa-target-semantic-diagnostic-2026-10-28/target_semantic_diagnostic_report_2026-10-29.md) |
| 备份完整性 | 已有数据逐文件核验，学校与AMAX回传状态、磁盘限制及待补清单统一见[整理目录](results/organization-2026-10-29/README.md)，不以目录存在代替完整备份 |

- 旧论文索引把 `2501.18052` 误标为 EvilEdit，该 PDF 实际是 SAeUron；EvilEdit 正文已列入待补清单。
- Rickrolling 的历史指标混用了 seed678 与 seed100 的 checkpoint；新实验应先绑定同一模型的各项指标，详见 [复现索引](reproduction/README.md)。

## 当前边界

当前仅执行用户授权的TCL独立验证，旧run及定时探针不恢复，Drive上传保持暂停。真实实验须记录适用授权及review证据，不能把已经完成的三轮重新启动。

2,336张包含正常图、攻击图和对照图，并不是2,336个独立攻击样本；不同轮次的比例需与同轮基线比较，不能混排。

## 其他资料

- [研究目录](research/README.md) · [历史调研](reports/README.md) · [仿真说明](simulations/README.md) · [汇报材料](presentations/README.md)
- [早期实验归档](archive/experiments/backdoordm_reproduce/README.md) · [上一版方案封存](reports/archive/2026-10-23-tssa-local-surrogate/README.md)
- [2026-10-26历史迁移记录](archive/organization-2026-10-26/README.md)：含当时快照、46个文件迁移映射和完整性检查。
- [2026-10-29整理与回传记录](results/organization-2026-10-29/README.md)：本次备份、缺口、逐文件哈希与修改前索引快照。
