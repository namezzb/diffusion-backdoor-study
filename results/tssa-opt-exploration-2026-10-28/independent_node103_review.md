# 103离线准备脚本独立审阅

审阅源码：`prepare_node103_offline.py`，SHA256=`5d8dce5b3bdb0d7d8497ed5beabe7fe47bc109c7bcd1f71127af6f74f3c54467`。46项本机独立检查通过，结果见[核查JSON](independent_node103_review.json)，复算入口见[独立检查程序](independent_node103_review.py)；没有SSH、GPU、模型下载或实际安装。

## 结论与必要修复

**当前版本无剩余必须修复项，可按各独立阶段执行CPU离线准备；此结论不授权启动GPU或证明CUDA兼容。** `python`阶段只传输约29MB固定归档，`install-python`和`install-env`分别执行且受既有状态保护，任一步失败停止，不循环重试。

审阅指出的`.partial`硬链接问题已修正：写入前和打开文件后都要求常规、本人所有、单链接文件，独立反例确认旧文件字节未变。作者补充的安装顺序保护也已核查：安装环境之前必须有已完成Python安装收据、固定归档与解释器SHA，以及精确的`sys.prefix/base_prefix`，失败或其他venv身份均拒绝。

## 目标、连接与资产边界

- 固定只向`school103:/data1/zhangzibo/arxiv-tssa`写入，模型与wheel只读取`school104:/data2/zhangzibo/arxiv-tssa`；CLI没有可自由改写host/root的参数，原模型、旧环境manifest和安装器字节保持不变。
- 所有传输SSH使用已配置别名、严格hostkey、BatchMode、单次连接与有限超时；沿用已固定哈希的SchoolSession配置生成器，跳板及目标仍使用本人known-hosts和密钥路径。
- 模型数据经104 stdout→Mac OS pipe→103 stdin，不生成Mac模型缓存；仅Python小归档、任务日志和临时stderr使用Mac文件，未删除旧数据。
- 51项wheel、47项模型及其manifest/历史哈希证据均有本机固定哈希，模型大小、revision和SHA对应一致；目标既有完整文件只验SHA和长度，不覆盖或重传。

## 续传与失败处理

- 已有partial必须不长于源文件，并同时匹配源完整SHA、长度和同源前缀SHA；不同前缀、过长partial、不同源SHA/长度均被拒绝。
- 接收时再核对partial大小和前缀，读取精确字节数并拒绝多余字节，完整SHA通过后使用Linux `RENAME_NOREPLACE`发布；既有目标不被覆盖，异常保留partial待人工审阅。
- 独立模拟证实relay只建立固定源/目标两个传输子进程、使用有限deadline，失败向上抛出且不重试，清理仅限本轮本机SSH子进程；不处理他人任务或远端GPU进程。
- Python/环境安装留下started/failed状态时拒绝自动接续或重新安装；状态写入采用随机独占临时文件，避免固定`.new`名称误截断硬链接文件。

## 归档与运行时兼容

Python归档SHA256=`4a51ce60007a6facf64e5495f4cf322e311ba9f39a8cd3f3e4c026eae488e140`，实际清单2364项、展开91,072,956字节。校验拒绝绝对路径、上跳路径、非python根目录、重复成员、硬链接、特殊文件、向外符号链接及从符号链接下方提取成员，所有成员先验证后提取且链接最后安装。

所有远端准备模板可按Python3.8语法解析，bootstrap不依赖3.9才有的`Path.is_relative_to`；实际环境安装使用固定CPython3.11.7。冻结wheel中最高manylinux要求为glibc2.28，预检明确要求Linux/x86_64、glibc≥2.28、本人所有且不在系统盘，旧安装器进一步核对所有wheel tags、版本、独立venv和CPU导入。

旧安装器仅通过新wrapper调整`ALLOWED_ROOT`为103本人目录，其原始源码哈希不变。CPU阶段禁用CUDA设备、禁止pip网络索引并保持offline；103已知驱动550与104的cu128环境不同，CPU安装成功不能替代后续获准GPU阶段的真实CUDA兼容验证。

## 证据限制

本审阅验证本机清单、源码路径保护、合成反例和模拟传输，不证明远端当前可达、盘配额、源文件字节、安装成功或GPU许可。正式执行时每一阶段仍需验收其实际日志和远端SHA/状态，不应把本机46项通过写成103已安装完成或已经可以开展研究计算。
