# 脚本导航

当前实验入口由[项目状态](../research/project_state.json)确定。各目录按用途组织，README 提供操作和源码入口。

| 目录或入口 | 用途 |
|---|---|
| [TCL 执行器](merging/trigger_contrast_localization/README.md) | 当前实验的启动、恢复、状态查询和模块导航 |
| [merging/](merging/README.md) | TSSA、合并方法与历史实验实现及对应测试 |
| [connection/](connection/README.md) | GPU 查询、连接探测、实验后保留与资料回传工具 |
| [storage/](storage/README.md) | 本地归档、恢复、服务器文件取回和可选索引工具 |
| [reproduction/](reproduction/README.md) | BackdoorDM 复现审计及历史修复脚本 |
| [server/](../server/README.md) | 学校 SSH 配置、离线安装和资产中转的真实维护位置 |

## 路径与版本

旧根目录脚本和 `server/` 中部分文件是指向这里的兼容链接。部署时包含真实源文件，历史运行版本按各 run 的冻结快照查询。

当前 TCL 代码仍引用部分 `pilot24_*` 模块；文件名带旧版本不代表可以移除。一次性执行记录与审计脚本保留在所属 `results/` 中；代码和测试暂按既有导入、部署与测试发现路径存放。

新运行的操作和中间状态写为可读 Markdown；固定科学配置保留所需格式。详细状态、检查范围和结果由所属 TASK 与实现报告维护。

[项目总索引](../README.md) · [研究](../research/README.md) · [结果](../results/README.md)
