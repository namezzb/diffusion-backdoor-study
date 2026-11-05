# 扩散模型后门研究

从[项目状态](research/project_state.json)进入当前 TASK；实验进度、授权和下一步只在 TASK 维护。本页按用途导航。

## 常用入口

| 要做什么 | 入口 |
|---|---|
| 查看当前实验、接续工作 | [项目状态](research/project_state.json) → 当前 TASK · [任务目录](research/tasks/README.md) |
| 启动、恢复或查看运行状态 | [MasqLoRA 执行器](scripts/reproduction/masqlora/README.md) · [TCL 执行器](scripts/merging/trigger_contrast_localization/README.md)；按当前TASK选择 |
| 查看 GPU、连接服务器 | [labgpu](scripts/connection/LABGPU.md) · [服务器操作手册](server/OPERATIONS.md) |
| 理解研究方法和已有结论 | [研究导航](research/README.md) · [方法与三轮结果解释](research/tssa_methods_and_results_explained_2026-10-29.md) |
| 查实验结果和原始证据 | [结果索引](results/README.md) |
| 找代码或工具 | [脚本导航](scripts/README.md) |
| 换电脑、定位服务器资料 | [换机步骤](storage/NEW_COMPUTER.md) · [存储导航](storage/README.md) |
| 查看项目规则和协作方式 | [AGENTS.md](AGENTS.md) · [工作流程](research/WORKFLOW.md) |

## 目录职责

| 目录 | 放什么 |
|---|---|
| [research/](research/README.md) | 研究方案、固定配置、项目指针；每项任务的 TASK 和实现报告放在 `tasks/<日期-名称>/` |
| [scripts/](scripts/README.md) | 实验实现、连接、存储与复现工具；各子目录 README 按用途索引 |
| [server/](server/README.md) | 服务器连接配置、离线部署工具和操作手册 |
| [results/](results/README.md) | 按实验轮次保存的结果、原始记录和证据 |
| [papers/](papers/README.md) | 论文、题名索引、元数据和待下载清单 |
| [reports/](reports/README.md) | 文献调研、机制分析和早期研究思路 |
| [reproduction/](reproduction/README.md) | MasqLoRA 与 BackdoorDM 复现入口及代码论文对照 |
| [storage/](storage/README.md) | 资料位置、取回入口、历史备份清单和按需索引工具 |
| [simulations/](simulations/README.md) · [presentations/](presentations/README.md) | 合成仿真与汇报材料 |
| [archive/experiments/](archive/experiments/backdoordm_reproduce/README.md) · [reports/archive/](reports/archive/2026-10-23-tssa-local-surrogate/README.md) | 只读历史实验和封存方案 |

根目录旧脚本、旧进度文件，以及 `data/`、报告编号目录和 `server/` 中部分文件是兼容链接，真实内容由目标目录维护。历史冻结路径和服务器原始资料按原位置查询。

## 新内容放哪里

- 新任务使用[任务模板](research/tasks/TEMPLATE.md)，文件统一遵循[四条收纳规则](AGENTS.md#文件收纳规则)：任务文档归任务、运行记录归run、临时文件归`_scratch/`，复用原记录。
- 新实验采用独立 run 身份；运行过程使用 Markdown，固定协议与模型保留所需格式，具体见[结果保存约定](results/README.md#新结果保存约定)。
- README 只维护入口，详细历史通过链接读取；当前代码与历史运行版本分别解释。
- 模型、原图和缓存保留在本人服务器数据盘；资料取回与备份范围见[存储导航](storage/README.md)。

目录维护记录：[2026-11-03 导航与记录分层](research/tasks/2026-11-03-repository-organization/TASK.md) · [2026-10-29 资料整理](results/organization-2026-10-29/README.md) · [2026-10-26 迁移](archive/organization-2026-10-26/README.md)。
