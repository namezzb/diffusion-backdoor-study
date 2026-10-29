# 服务器连接、离线部署与历史兼容入口

更新于2026-10-29，**实验已暂停，旧`gpu`定时任务已删除**；目前整理已有科研资料并建立Git换机索引，本轮不继续大文件回传，不启动训练、下载新模型或定期探针。暂停状态与全部尝试见[研究总结](../research/tssa_attempts_summary_2026-10-29.md)，规则以[AGENTS.md](../AGENTS.md)为单一事实来源。

## 本目录的真实文件

本目录同时包含9份真实文件和20个指向`scripts/`的历史兼容链接；真实文件数包含本索引，兼容链接不是第二份源代码。学校连接与离线部署应直接维护这里的真实文件，历史合并/复现脚本则维护其链接目标。

| 文件 | 用途 |
|---|---|
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
| [学校资料归档工具](../scripts/connection/archive_school_research.py) | 只读盘点、按清单回传并验哈希，属于已有工具，当前不自动执行整批回传。 |
| [学校只读探针](../scripts/connection/probe_school_gpu.py) | 有界检查指定已配置节点；实验暂停期间不周期运行。 |
| [AMAX启动器](../scripts/connection/start_amax.sh) | 独立的AMAX隧道和交互连接，不是学校GPU平台。 |
| [脚本总索引](../scripts/README.md) | 三轮已结束实验、CPU检查、离线部署和历史复现脚本。 |

学校公网跳板为`zhangzibo@hduiipl.cn:7002`，已配置100、101、102、103、104、127节点；节点配置表示已知入口，不代表当前可登录或可用GPU。SSH/SCP使用本目录配置，主机密钥变化须先核实，不关闭校验或猜测新节点地址。

私钥仅位于本机`~/.ssh/zhangzibo_school`且权限600，主机记录为`~/.ssh/known_hosts_school`；已核验跳板ED25519指纹为`SHA256:MheEdeSO8cSm6MRZn1sehQ8T8mlTX+mjJqMXoaz3C58`，密码、私钥及动态码不进入仓库。

`start_school.sh`可处理已知DNS问题，而原生SSH/SCP仍依赖正确域名解析；历史连接等待为60秒，连接失败须区分认证、目标路由与跳板问题，不能循环重试代替诊断。

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

历史100/127曾出现账号过期、101公钥拒绝、102路由或跳板转发失败，状态可能变化；本次整理不借机开展全节点资源探测，若未来恢复实验须按实时平台及SSH证据重新判断。

旧`gpu`定时任务于2026-10-28 20:25成功删除，见[删除回执](../results/tssa-mvp-2026-10-26/automation_cleanup_20261028T1225Z.json)；早期#55两卡请求、后来的#56一张等待及30分钟监控均属历史，不是现在自动重排或恢复监控的指令。

## 20个历史兼容链接

| 用途 | 真实源文件位置 |
|---|---|
| BackdoorDM复现审计、旧修复与后处理 | [scripts/reproduction/](../scripts/reproduction/) |
| Checkpoint合并及旧攻击实验 | [scripts/merging/](../scripts/merging/) |
| AMAX连接辅助 | [scripts/connection/](../scripts/connection/) |

历史远端部署仍涉及`/opt/data/private/server/`和`/opt/data/private/BackdoorDM/server/`，本地整理不改变其内容或脚本中的路径；备份部署必须包含真实源文件，不能只打包符号链接而遗漏目标。

[项目总索引](../README.md) · [结果索引](../results/README.md) · [项目指令](../AGENTS.md)
