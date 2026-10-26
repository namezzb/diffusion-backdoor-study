# 论文搜索元数据

> 更新：2026-10-26；两份 JSON 从原 `data/` 迁入本目录，原始内容未改动。这些是历史搜索结果快照，不是已下载论文清单或实验结果。

| 原始文件 | 记录数 | 文件内唯一 ID | SHA-256 |
|---|---:|---:|---|
| [diffusion_backdoor_papers.json](diffusion_backdoor_papers.json) | 42 | 42 | `09a6f6e60d820b2758bf9971d74c18ebbd6c40e2c36fd949fb95f8d57ebe2253` |
| [diffusion_backdoor_search_results.json](diffusion_backdoor_search_results.json) | 50 | 50 | `dbc0e3f9311ca55da1321b6e83eda019ce036d7a9bbba9c16ca0217cefe592d9` |

## 使用规则

- 两份快照的交集为 6 个 ID、并集为 86 个 ID，单文件均无重复；跨文件重复保留其来源上下文，不直接覆盖或去重原文件。
- 条目中的发表日期不是搜索执行日期，文件本身未提供完整检索任务记录；搜索时间、查询条件及结果完整性不能由本轮盘点补推。
- 元数据中的题名、摘要、外链与发表信息仍需对照原论文核查，本地 PDF 的已核对清单见 [catalog.json](../catalog.json)。
- 新检索另存带日期的快照，下载完成后单独更新论文索引与校验记录；兼容旧路径 `data/` 不应成为新的重复存储入口。

返回 [论文资料索引](../README.md)。
