# 本地存储与索引工具

资料导航见[storage/](../../storage/README.md)，换机操作见[接续步骤](../../storage/NEW_COMPUTER.md)。

## 本地存储与服务器索引

大文件回传保持暂停，TCL新协议所需既有副本核验依任务授权执行；[build_server_index.py](build_server_index.py)只读本地保存的盘点生成[服务器索引](../../storage/SERVER_INDEX.md)，不连接服务器。[research_archive.py](research_archive.py)核验本地ZIP及逐文件清单，并恢复到指定目录。

[restore_from_catalog.py](restore_from_catalog.py)提供清单浏览和已完成云端往返包的批量恢复，当前仅核心历史快照符合该条件；[prepare_research_backup.py](prepare_research_backup.py)只负责限定科研目录内的本地打包，不代表已上传，也不应在暂停期间盲目重建相同快照。

[fetch_server_file.py](fetch_server_file.py)在新电脑按103/104文件索引取回单个已知哈希文件，默认仅展示计划，显式`--download`才只读连接并验哈希；缺SHA的历史条目不假装可验收下载，详见[换机步骤](../../storage/NEW_COMPUTER.md)。

[build_retrieval_catalog.py](build_retrieval_catalog.py)合并冻结历史附件、新登记附件、论文目录和已有服务器映射；[maintain_index.py](maintain_index.py)按需提供变更影响、文件清单和一致性检查。使用说明见[索引工具说明](../../storage/INDEX_MAINTENANCE.md)。

存储回归检查：[归档恢复](test_research_archive.py) · [目录恢复](test_restore_from_catalog.py) · [服务器单文件取回](test_fetch_server_file.py) · [附件目录生成](test_build_retrieval_catalog.py) · [索引工具检查](test_maintain_index.py)，均可离线运行；被Git忽略的嵌套仓库目录仅接受明确的本地排除，不按普通附件放行。

127 的文件取回沿用工具的 `school127` 映射，仅访问本人科研目录。

[脚本总索引](../README.md)
