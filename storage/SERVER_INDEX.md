# 服务器科研数据索引

**科研进度与索引随Git同步，大文件留在服务器。** 下表原有盘点时间保持不变；TCL任务的[103资产观察](../research/tasks/2026-10-29-trigger-contrast-localization/server103_assets_observation_20261029.json)和CPU预检另有本轮回执，不把旧盘点重标为新核验。

## TCL中断图片盘点（2026-10-30 01:48）

103运行中断后核对了343张完成PNG的远端SHA-256与账本，首图见[原清单](server-index/103-tcl-v1-first-sample.jsonl)，其余342张见[本次清单](server-index/103-tcl-v1-completed-images-20261030.jsonl)；图片均未回传，原账本仍持锁，不称为完整备份。

## TCL 127完成图（2026-10-30 11:20）

127分片截至12:38完成62张且逐张SHA与账本一致，[逐文件索引](server-index/127-tcl-v1-shard-images-20261030.jsonl)登记其服务器位置；未下载本地，恢复时见证过期退出后已重进CPU准备。

## TCL 127分片准备快照（2026-10-30 10:49）

103一致性快照已复制至127并由分片候选校验418项内容与清单；[127逐文件索引](server-index/127-tcl-v1-shard-snapshot-20261030.jsonl)保留419项来源，快照并非原run终态。

## TCL 104分片准备快照（2026-10-30 10:04）

103账本的SQLite一致性备份、343张图片、选择及代码共418项已通过内网复制到104并逐项核验SHA，另登记其清单共419项；[104逐文件索引](server-index/104-tcl-v1-shard-snapshot-20261030.jsonl)可用于取回，源线程仍持锁，快照不是原run终态。

## 按实验找数据

| 实验 | 服务器及完整根目录 | 关键子目录/文件 | 本地已有 | 仍留远端、未完整镜像 |
|---|---|---|---|---|
| 第一轮：TSSA梯度初步验证 | 104：`/data2/zhangzibo/arxiv-tssa/results/mvp-2026-10-28-single-v1/` | `images/`原图；`selected_checkpoints/`导出权重；`artifacts/`缓存与响应；`operations/`逐操作回执；`per_step_coefficients_and_losses.jsonl`训练轨迹 | [结果入口](../results/tssa-mvp-2026-10-26/README.md)：33项终态小产物、1520图的评价结果、144步轨迹、报告面板；另有部分缓存 | 1520张PNG约684.17MB、三候选的两份不同内容权重约984.53MB，以及其他缓存和日志 |
| 第二轮：12点直接图片搜索 | 103：`/data1/zhangzibo/arxiv-tssa/results/tssa-opt-exploration-2026-10-28-v1/` | `images/`；`operations/`；`search_summary.json`、`dev_summary.json`与选择结果 | [结果入口](../results/tssa-opt-exploration-2026-10-28/README.md)：816张PNG约341.27MB、833份终态及启动/恢复小产物、冻结源码包 | 研究根目录外围完整日志、环境准备等尚未全部镜像；严格审计invalid原记录保留 |
| 第三轮：目标语义诊断 | 103：`/data1/zhangzibo/arxiv-tssa/results/tssa-target-semantic-diagnostic-2026-10-28-v1/` | `outputs/`原始响应；`cells/`逐单元回执；`terminal.json`与阶段结果 | [结果入口](../results/tssa-target-semantic-diagnostic-2026-10-28/README.md)：1141份、约19.22MB原始文件；本轮0图/0更新 | 外围准备和运行目录未完整镜像，不影响已回传1141份诊断产物的单独验收 |

checkpoint指保存的模型参数，不能自动理解为可从中恢复训练的完整状态。相同权重可有不同候选身份，因此索引保留三个候选路径及相同内容关系，不合并科学结果。

## 逐文件目录与覆盖范围

| 节点 | 盘点时间（北京时间） | 清单与本地核验 | 边界 |
|---|---|---|---|
| 104 | 2026-10-29 10:11:14 | [104逐文件索引](server-index/104.jsonl)：5454项研究/模型配置有远端SHA-256，另13项公开模型大文件仅大小；248项对应本地文件本轮核验一致 | 未镜像5206个逻辑路径，按内容去重5194项、1,728,731,847字节；公开模型大文件约14.68GB另计 |
| 103 | 2026-10-29 10:07:31 | [103逐文件索引](server-index/103.jsonl)：2847项元数据中，2782项关联早前回传哈希并在本轮核验本地一致，65项仅元数据 | 本轮没有在服务器重新计算SHA；2782项为1141诊断、816图片和825个运行内小文件，833终态小产物另含运行根目录外的启动/恢复记录 |
| 103公开模型 | 2026-10-28历史传输记录 | [47项模型记录](server-index/103-models-historical.jsonl)：保留原传输哈希及时间 | 不代表当前模型仍可访问，也不将模型计入2847项研究目录 |
| AMAX | 历史文档，2026-10-29旧入口连接失败 | [AMAX条目](server_catalog.json)记录下方已知路径 | 当前会话、文件数量、大小、哈希均未核验，不用历史缓存冒充本次备份 |

104索引共5467行，其中5454项研究/配置与13项公开大权重须分开看；103研究目录和47项历史模型记录也分开统计。`sha256: null`表示该清单缺少内容校验，`not_mapped_locally`表示本索引未建立已核验本地副本，不声称所有其他位置都没有该文件。

每行包含服务器、SSH别名、远端完整路径、仓库内相对映射、字节数、内容指纹、实验编号、源证据、盘点时间及本地校验状态。机器总入口为[server_catalog.json](server_catalog.json)，原始盘点和失败回执保留在[整理证据目录](../results/organization-2026-10-29/README.md)。

## 代码、模型和环境的位置

| 资料 | 远端路径或索引 | 本地入口 |
|---|---|---|
| 104实际部署代码 | `/data2/zhangzibo/arxiv-tssa/code/` | [104逐文件索引](server-index/104.jsonl)中`code/`开头的50份已校验源码；旧机本地映射不随Git，按索引可取回，目录名含dual不表示实际运行双卡 |
| 103第二轮执行源码 | `/data1/zhangzibo/arxiv-tssa/code/image-search-6913379cd01c/` | [冻结源码包](../results/tssa-opt-exploration-2026-10-28/source-6913379cd01c.tar.gz) |
| 103第三轮准备 | `/data1/zhangzibo/arxiv-tssa/preparations/target-semantic-20261029T013825229255Z/` | [准备记录](../results/tssa-target-semantic-diagnostic-2026-10-28/cpu_preparation_20261029T013825229255Z/)；不是完整远端镜像 |
| 103 TCL旧运行包 | `/data1/zhangzibo/arxiv-tssa/code/tcl-20261029-01-run-b0a34fa6/` | [验收回执](../research/tasks/2026-10-29-trigger-contrast-localization/server103_deployment_20261029.json)；旧版M06已失效，不得启动 |
| 103 TCL定位运行 | `/data1/zhangzibo/arxiv-tssa/results/tcl-20261029-01-v1/` | [定位终态观察](../research/tasks/2026-10-29-trigger-contrast-localization/server103_localization_terminal_observation_20261029.json)记录终态及selection哈希；图片阶段准备中，未盘点或验收完整产物 |
| 103 TCL追加修订 | `/data1/zhangzibo/arxiv-tssa/amendments/tcl-20261029-01-empty-path-v1/` | [修订与审阅](../research/tasks/2026-10-29-trigger-contrast-localization/AMENDMENT_REVIEW.md)；签名、补丁与启动器已验哈希，原冻结源码未被覆盖 |
| 103 TCL源确认首图 | `/data1/zhangzibo/arxiv-tssa/results/tcl-20261029-01-v1/images/8be2811fa880f2d39d0444293293f8f61be04fc974a234c485f811ccfd737405.png` | [首图远端清单](server-index/103-tcl-v1-first-sample.jsonl)及[首批观察](../research/tasks/2026-10-29-trigger-contrast-localization/server103_source_initial_images_20261029.json)；仅首图取回来源有哈希，其余在运行中未盘点 |
| 104公开模型 | `/data2/zhangzibo/arxiv-tssa/models/` | [固定来源与revision](../research/tssa_mvp_assets_2026-10-26.json)，大权重留远端 |
| 103公开模型 | `/data1/zhangzibo/arxiv-tssa/models/` | [历史传输记录](server-index/103-models-historical.jsonl) |
| 环境版本及恢复依据 | 安装目录留服务器，不复制为研究结果 | [环境清单](../research/tssa_mvp_environment_2026-10-26.json) · [脚本索引](../scripts/README.md) |

AMAX只保留已知历史路径：`/opt/data/private/BackdoorDM/`、`/opt/data/private/EvilEdit/results/eviledit_reproduce/backdoored_unet.pt`和`/opt/data/private/models/`下的`stable-diffusion-v1-5/`、`vit-base-patch16-224/`、`clip-vit-base-patch32/`。这些路径未做本轮文件清单，不因名字存在于文档就标记可恢复。

## 以后需要取回时

先从本页选实验，再用逐文件索引确定远端路径和预期SHA-256；在获准的新环境单独配置本人连接凭据，检查实际文件后再按需复制及核验。学校别名在[SSH配置](../server/school_ssh_config)，AMAX需用户提供当前会话入口，索引不保存私钥或验证码。

本次最后一次104回传尝试为北京时间2026-10-29 11:22:12，公共跳板重置、SSH退出255，新增远端文件0；随后用户决定停止传输，当前不自动重试。重建本地索引只读取仓库内已保存证据：

```bash
python3 scripts/storage/build_server_index.py
```

该工具会重新核验已有本地映射并更新本地索引，不连接网络、不刷新远端状态。**索引不是备份副本**，若服务器数据丢失且没有其他副本，单凭路径和哈希不能还原文件。

[存储入口](README.md) · [换机方案](../research/research_storage_and_restore_plan_2026-10-29.md) · [全部结果与术语解释](../research/tssa_methods_and_results_explained_2026-10-29.md)
