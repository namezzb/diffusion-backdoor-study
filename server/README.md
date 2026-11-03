# 服务器连接、离线部署与历史兼容入口

连接、离线部署及故障恢复先读[操作手册](OPERATIONS.md)，选卡遵守[统一优先级](../AGENTS.md#服务器选择优先级)。当前任务、协议和资源观察从[项目状态](../research/project_state.json)进入，本页不复制实时进度；新实验的单一启动/恢复命令见[执行器入口](../scripts/merging/trigger_contrast_localization/README.md)。

## 本目录的真实文件

本目录兼有真实文件和指向`scripts/`的历史兼容链接；学校连接与离线部署维护这里的真实文件，历史脚本维护其链接目标，逐文件记录见[全仓清单](../storage/repository_index.jsonl)。

| 文件 | 用途 |
|---|---|
| [OPERATIONS.md](OPERATIONS.md) | 学校与AMAX连接、离线部署、历史缓存线索及断连恢复，按任务需要读取。 |
| [school_ssh_config](school_ssh_config) | 学校跳板和已配置节点的OpenSSH别名、用户及密钥检查设置。 |
| [start_school.sh](start_school.sh) | 选择已配置学校节点连接，默认104，必要时查询公共DNS，不固定旧公网IP。 |
| [stage_school_assets.py](stage_school_assets.py) | 公开模型的固定revision逐文件中转和远端哈希验收，不分配GPU。 |
| [install_school_offline_env.py](install_school_offline_env.py) | 冻结Linux wheel及本人数据盘隔离环境的校验与离线安装。 |
| [test_stage_school_assets.py](test_stage_school_assets.py) | 中转身份、文件完整性及恢复逻辑的CPU检查。 |
| [test_stage_school_chunk_upload.py](test_stage_school_chunk_upload.py) | 分块边界、前缀和错误恢复检查，不连接或证明实时网络可用。 |
| [test_install_school_offline_env.py](test_install_school_offline_env.py) | 依赖标签、路径、环境和安装边界检查。 |
| [gpu_monitor_state.json](gpu_monitor_state.json) | 脱敏状态与历史探针/运行证据索引；历史占用不是现在的资源许可。 |

## 连接与回传入口

| 入口 | 用途 |
|---|---|
| [labgpu 状态 CLI](../scripts/connection/LABGPU.md) | 直接查询平台 API，显示显卡型号、占用、指标和采样新鲜度；支持 JSON 与本地缓存。 |
| [学校资料归档工具](../scripts/connection/archive_school_research.py) | 只读盘点、按清单回传并验哈希，属于已有工具，当前不自动执行整批回传。 |
| [学校只读探针](../scripts/connection/probe_school_gpu.py) | 按AGENTS优先级有界检查指定已配置节点，分别记录不可用原因；不恢复旧周期探针。 |
| [AMAX启动器](../scripts/connection/start_amax.sh) | 独立的AMAX隧道和交互连接，不是学校GPU平台。 |
| [脚本总索引](../scripts/README.md) | 三轮已结束实验、CPU检查、离线部署和历史复现脚本。 |

连接身份、指纹与DNS处理统一见[学校连接](OPERATIONS.md#学校连接)；入口配置不代表当前可登录或有可用GPU。

## 三轮资料与服务器目录

| 已结束的运行 | 服务器原路径 | 本地入口 |
|---|---|---|
| 梯度校准MVP | 104：`/data2/zhangzibo/arxiv-tssa/results/mvp-2026-10-28-single-v1` | [最终报告与证据](../results/tssa-mvp-2026-10-26/README.md) |
| 直接ASR探索 | 103：`/data1/zhangzibo/arxiv-tssa/results/tssa-opt-exploration-2026-10-28-v1` | [探索负结果](../results/tssa-opt-exploration-2026-10-28/direct_ASR_negative_report_2026-10-28.md) |
| 目标语义诊断 | 103：`/data1/zhangzibo/arxiv-tssa/results/tssa-target-semantic-diagnostic-2026-10-28-v1` | [诊断证据](../results/tssa-target-semantic-diagnostic-2026-10-28/README.md) |
| 历史BackdoorDM和合并实验 | AMAX：`/opt/data/private/BackdoorDM/`、`/opt/data/private/EvilEdit/` | [复现索引](../reproduction/README.md) · [历史结果](../results/README.md) |

以上是证据来源位置，完整性以当前回传清单及哈希为准；学校103/104的数据盘为本轮大文件落点，不把模型、依赖或原图放到空间紧张的系统盘。AMAX旧缓存和动态端口均不能自动证明今日服务可用，公开模型来源应保留固定revision与文件哈希。

## 历史资源记录的边界

2026-10-26初次盘点曾记录103为3×RTX2080Ti、104为8×RTX3090，随后103实测为3×RTX3090；这些记录按采样时间解释，不能把旧型号、卡号或禁用列表当作当前可用资源。2026-10-29诊断在103 GPU2实际完成并释放，仍不能据此推断其他时刻的空闲或许可。

历史100/127曾出现账号过期、101公钥拒绝、102路由或跳板转发失败，104也曾在TCL迁移时CUDA初始化失败，状态可能变化；恢复时按AGENTS优先级重新做有界核验，不以旧成功保证当前可用，也不永久排除旧失败节点。

旧`gpu`定时任务于2026-10-28 20:25成功删除，见[删除回执](../results/tssa-mvp-2026-10-26/automation_cleanup_20261028T1225Z.json)；早期#55两卡请求、后来的#56一张等待及30分钟监控均属历史，不是现在自动重排或恢复监控的指令。

## 20个历史兼容链接

| 用途 | 真实源文件位置 |
|---|---|
| BackdoorDM复现审计、旧修复与后处理 | [scripts/reproduction/](../scripts/reproduction/) |
| Checkpoint合并及旧攻击实验 | [scripts/merging/](../scripts/merging/) |
| AMAX连接辅助 | [scripts/connection/](../scripts/connection/) |

历史远端部署仍涉及`/opt/data/private/server/`和`/opt/data/private/BackdoorDM/server/`，本地整理不改变其内容或脚本中的路径；备份部署必须包含真实源文件，不能只打包符号链接而遗漏目标。

[项目总索引](../README.md) · [结果索引](../results/README.md) · [项目指令](../AGENTS.md)
