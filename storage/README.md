# 科研资料存储与换机入口

**科研进度、代码和索引纳入Git，供新电脑定位并按需下载；大数据留服务器，Drive上传及大文件回传保持暂停。** 旧GPU定时任务保持删除；用户已单独授权[TCL服务器验证](../research/tasks/2026-10-29-trigger-contrast-localization/TASK.md)。

## 先看什么

| 想知道什么 | 入口 |
|---|---|
| 以后改动如何防止忘记更新 | [维护入口](INDEX_MAINTENANCE.md) · [全仓清单](repository_index.jsonl) · [最新收尾](maintenance/latest.json) |
| 哪台服务器、哪个目录存了什么 | [服务器资料索引](SERVER_INDEX.md) |
| 本地已有图片、代码、结果与缺项 | [本地资料目录](../results/organization-2026-10-29/README.md) |
| 做过哪些尝试，Uniform4、TSSA16等是什么意思 | [三轮结果与术语解释](../research/tssa_methods_and_results_explained_2026-10-29.md) |
| 目前实验是否运行、结论和下一步 | [可移植进度](../research/project_state.json) |
| 换电脑如何带走进度和取回大文件 | [新电脑接续步骤](NEW_COMPUTER.md) · [存储与换机方案](../research/research_storage_and_restore_plan_2026-10-29.md) |
| 索引维护覆盖与边界 | [本轮维护验收](audits/index_maintenance_acceptance_20261029.json) |
| 换机准备是否验收 | [新目录离线验收](audits/git_handoff_acceptance_20261029.json)：70项测试、1016项附件哈希及103/104计划模式通过 |
| 文件级机器清单 | [服务器清单](server_catalog.json) · [本地包清单](catalog.json) |

## 现在怎么存

- **本地科研仓库**保存代码、方案、报告、进度、索引和已有原始资料；根目录及各目录README负责导航，冻结产物不搬动或改名。
- **学校服务器**保留实验大文件，索引记录服务器编号、完整路径、文件大小、SHA-256内容指纹、实验编号、盘点时间及本地对应位置；没有哈希的项目明确留空。
- **Git**保存科研代码、报告、进度和索引，新电脑先拉取包含本次整理的提交；是否已推送以实际提交/远端验收记录为准，不从工作区文件存在推断已发布。
- **Drive**已暂停，不能视为完整备份；此前成功上传的两份文件和失败尝试见[历史传输记录](upload_receipts/cloud_attempts_20261029.json)。

只保留索引不会产生第二份数据副本：104的原图、检查点等仍依赖服务器保存。索引来自已保存的盘点，不能据此认定服务器现在在线或文件现在未变化。

## 本地准备好的包

9个包共4909个文件条目，按内容清单保留原路径；包中条目可能对应不同历史快照，不能把总数当成独立科研样本数。

| 分组 | 内容 | 当前包状态（Git小文件另行保留） |
|---|---|---|
| research-core | 2772项代码、方案、指标、进度和必要日志 | 暂停前已上传，重新下载后2772项全部验哈希并恢复成功；这是历史快照，不含最新服务器索引 |
| exploration-images | 第二轮816张原图，拆为3包 | 仅本地，校验完成；大包上传超时，未继续上传 |
| diagnostic-artifacts | 第三轮1141项原始诊断文件 | 仅本地，校验完成 |
| papers | 29个论文相关文件，含24份PDF及已有文本/页面资料，拆为2包 | 仅本地，校验完成 |
| presentations | 1份汇报文件 | 仅本地，校验完成 |
| other-research-artifacts | 150项历史科研图、缓存及冻结执行源码包 | 仅本地，校验完成 |

实际大小、SHA-256、逐文件清单及校验回执以[catalog.json](catalog.json)为准。`_packages/`、`_incoming/`、`_restore-check/`是本轮打包和本地验收目录，已排除在Git外，未自动删除。

## 本地恢复工具

以下操作只读本地包并写入指定的本地恢复目录，不下载、不连接服务器、不启动实验。推荐恢复到空目录，已有相同内容可复用，已有不同内容会报冲突且保留原文件。

先查看所有包及状态：

```bash
python3 scripts/storage/restore_from_catalog.py --catalog storage/catalog.json --list
```

如已持有某个本地包，可用基础工具独立验哈希并恢复；下例的目标和回执路径须换成新的实际路径，回执父目录须已存在且在恢复目录之外：

```bash
python3 scripts/storage/research_archive.py restore \
  --package storage/_packages/snapshot-2026-10-29-v1/diagnostic-artifacts-001.zip \
  --manifest storage/manifests/snapshot-2026-10-29-v1/diagnostic-artifacts-001.json \
  --target /absolute/path/to/empty-research-copy \
  --receipt /absolute/path/to/existing-receipt-folder/diagnostic-restore.json
```

基础工具接受本地已核验包；目录包装器`restore_from_catalog.py`只接受已完成云端往返的`roundtrip_verified`条目，所以当前不能用`--group all`恢复全部分组。这是明确的验收区分，不把仅在本地的包伪标成云端备份完成。

恢复工具仅依赖Python标准库，目前针对macOS/Linux，Windows原生环境未验收；基础恢复的49项保护测试及核心快照空目录恢复已通过。按服务器索引下载的新入口及其离线检查见[新电脑步骤](NEW_COMPUTER.md)，新电脑登录和真实服务器传输仍需单独验收。

## 范围与历史云端文件

资料来源限`/Users/zzb/arxiv`及本人科研服务器目录，不上传公司其他目录，不沿符号链接越界，不包含SSH私钥、密码、验证码或令牌。范围审计见[本地检查](audits/local_scope_review_20261029.json)，所有原始资料与历史失败记录均保留。

暂停前Drive中已有一份初始存储说明和一份约13.33MB核心快照：[历史目录](https://drive.google.com/drive/folders/1mph76LjG039Rky5mCEbzfCrMp732_2sU)。没有更改分享权限或删除它们；公司安全页面限制Drive访问后未绕过，最新要求下不再开展上传或下载。
