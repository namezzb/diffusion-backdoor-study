# 索引工具说明

仓库入口和当前任务分别见 [README](../README.md) 与 [项目状态](../research/project_state.json)。交付时按实际需要更新 TASK、实现报告和受影响的导航。索引维护是可选工具，不是实验启动、交付或提交的门槛；提交钩子和 GitHub CI 不运行索引检查或存储测试。

已有 [文件清单](repository_index.jsonl)、[维护记录](maintenance/latest.json)、[附件取回目录](retrieval_catalog.jsonl) 和 [服务器索引](SERVER_INDEX.md) 保留供查询，可能不是最新状态；历史冻结证据不因索引维护而改写。

## 指令文件维护

全局规则在 [AGENTS.md](../AGENTS.md)，当前状态在项目指针指向的 TASK，操作步骤在对应模块手册。README 负责导航；长过程记录放所属任务的历史文档或运行日志，保留日期和事实，通过链接查阅。

调整目录时先核对兼容链接、导入与部署路径，更新实际受影响的入口；索引工具仍按需使用。

## 可选索引命令

需要盘点或排查时，可在仓库根目录手动运行：

```sh
python3 scripts/storage/maintain_index.py impact
python3 scripts/storage/maintain_index.py refresh
python3 scripts/storage/maintain_index.py check
```

`impact` 查看相对当前提交的变化；`refresh` 重建本地文件清单；`check` 检查清单、链接、附件目录与维护记录的一致性。检查结果可能因既有记录未更新而失败，不代表实验失败，也不会自动修复记录。工具不连接服务器、不下载、不启动 GPU；清单不是服务器文件的备份。需要核对附件来源时可查阅已有目录和服务器索引，未知信息保留缺口。
