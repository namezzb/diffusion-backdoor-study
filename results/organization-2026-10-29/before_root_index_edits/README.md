# 扩散模型后门研究：项目总索引

整理日期：2026-10-26。当前研究是 **checkpoint 合并后的后门鲁棒性**，已确认采用 TSSA 梯度校准方案，2026-10-28已完成本轮初步验证，结果为负：RC/Uniform持出ASR均0，TSSA无合格候选，见[最终报告](results/tssa-mvp-2026-10-26/initial_validation_report_2026-10-28.md)。

## 从这里开始

| 要做什么 | 入口 |
|---|---|
| 查看当前方法、公式和低算力验证协议 | [当前 TSSA 方案](research/tssa_response_calibration_method_proposal.md) |
| 安排接下来的准备工作 | [实验准备清单](research/experiment_preparation.md) |
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
├── reproduction/             基准参考、复现进度、代码论文对照、循环流程
├── papers/                   论文索引和待下载清单
│   ├── pdf/                  24 篇 PDF，按 ID 命名
│   ├── txt/                  已有全文提取和页面快照
│   └── metadata/             两份历史检索数据
├── reports/                  历史综述、思路和机制分析
│   └── archive/              上一版方法的只读封存
├── results/                  实验结果入口
│   └── merging/              历史合并报告与可视化
├── scripts/                  脚本入口
│   ├── reproduction/         复现审计、补评和历史维护
│   ├── merging/              历史合并及 TSSA 脚本
│   └── connection/           AMAX 连接辅助
├── simulations/              合成仿真与历史图
├── presentations/            历史汇报 PPT 和生成脚本
└── archive/                  早期实验原始材料、此次整理记录
```

常用内容控制在一至两层；旧封存目录保持原样。根目录旧文档、`server/`、`data/` 和报告编号目录中的兼容链接指向新位置，不是重复副本。

## 已有基础与当前缺口

| 项目 | 当前可确认的状态 |
|---|---|
| 本地论文 | 24 篇 PDF 均可读，无相同 SHA-256 的重复文件；题名按 PDF 首页核对 |
| BackdoorDM | 本地 2026-07-24 严格汇总记录 15/16 有模型、13/16 完整闭环、5/5 防御已执行；本次未重新核验服务器 |
| 基准缺口 | `eviledit_numAdd`、`badt2i_objectAdd` 各缺正式 10K FID；`villandiffusion_cond` 缺数据 |
| 历史合并实验 | 已有探索结果，但样本协议、模型来源和实现范围有差异；不能据此判定新方法有效或达到 SOTA |
| 当前 TSSA 梯度版 | 已实现并完成1520图/144更新；当前固定配置负结果，RC/Uniform持出ASR均0、TSSA无合格候选 |
| 后续直接ASR探索 | 已完成816图/0更新；开发候选与naive均33.33%，正常约束未通过，见[负结果及完整性缺陷](results/tssa-opt-exploration-2026-10-28/direct_ASR_negative_report_2026-10-28.md) |

- 旧论文索引把 `2501.18052` 误标为 EvilEdit，该 PDF 实际是 SAeUron；EvilEdit 正文已列入待补清单。
- Rickrolling 的历史指标混用了 seed678 与 seed100 的 checkpoint；新实验应先绑定同一模型的各项指标，详见 [复现索引](reproduction/README.md)。

## 接下来按什么顺序推进

1. 核验并补齐核心论文，同时只读导出服务器 checkpoint、配置和原始指标清单。
2. 固定同一后门源、干净源、开发专家和持出专家，补齐所选模型的基础指标与评价协议。
3. 按当前方案完成实现检查和小规模筛查，再运行三族对照及持出验证。

具体完成条件、预算和产物见 [实验准备清单](research/experiment_preparation.md)；这次整理没有启动下载、训练或评估。

## 其他资料

- [研究目录](research/README.md) · [历史调研](reports/README.md) · [仿真说明](simulations/README.md) · [汇报材料](presentations/README.md)
- [早期实验归档](archive/experiments/backdoordm_reproduce/README.md) · [上一版方案封存](reports/archive/2026-10-23-tssa-local-surrogate/README.md)
- [本次迁移与校验记录](archive/organization-2026-10-26/README.md)：含整理前快照、46 个文件的迁移映射和完整性检查。
