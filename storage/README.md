# 存储与资料取回

本地仓库保存代码、文档和已有资料；模型、原图及缓存主要保留在本人服务器数据盘。当前运行位置从[项目状态](../research/project_state.json)进入 TASK 查询。

## 按用途查找

| 要做什么 | 入口 |
|---|---|
| 换电脑后接续工作 | [NEW_COMPUTER.md](NEW_COMPUTER.md) |
| 查服务器资料位置 | [SERVER_INDEX.md](SERVER_INDEX.md) · [机器目录](server_catalog.json) |
| 查本地已回传资料与缺项 | [历史整理目录](../results/organization-2026-10-29/README.md) |
| 查已有备份包、清单与验证记录 | [历史备份说明](BACKUP_HISTORY.md) · [包目录](catalog.json) |
| 查单个附件来源 | [附件取回目录](retrieval_catalog.jsonl) · [服务器文件索引](server-index/) |
| 使用归档、恢复或取回工具 | [存储脚本导航](../scripts/storage/README.md) |
| 按需检查或更新索引 | [INDEX_MAINTENANCE.md](INDEX_MAINTENANCE.md) · [已有文件清单](repository_index.jsonl) |
| 查看存储方案依据 | [研究资料存储方案](../research/research_storage_and_restore_plan_2026-10-29.md) |

## 子目录职责

| 目录 | 内容 |
|---|---|
| `server-index/` | 带观察时间的服务器文件清单 |
| `manifests/` | 历史备份包的内容清单 |
| `audits/`、`verification_receipts/`、`upload_receipts/` | 历史检查、验证和传输证据 |
| `maintenance/` | 可选索引维护记录 |
| `_packages/`、`_incoming/`、`_restore-check/` | 本地打包、中转和恢复验证目录，已排除在 Git 外 |

索引记录位置和历史观察，不能替代数据副本或实时服务器检查。Drive 上传及大文件批量回传继续保持暂停；既有包和回执保留原位。详细历史和恢复命令见[历史备份说明](BACKUP_HISTORY.md)。

[项目总索引](../README.md) · [服务器操作](../server/OPERATIONS.md)
