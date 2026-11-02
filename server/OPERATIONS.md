# 服务器操作手册

连接、环境准备、传输或故障恢复时读取；GPU授权、额度、选卡和停止条件只在[AGENTS.md](../AGENTS.md#服务器选择优先级)维护。本文命令是操作入口，不构成实验授权；当前运行身份及参数从[项目状态](../research/project_state.json)进入对应TASK和协议。

## 学校连接

| 项目 | 入口与约定 |
|---|---|
| 平台 | https://gpu.orz2333.fun/ ，查看登录后的实时规则、账号及资源状态 |
| 公网跳板 | `zhangzibo@hduiipl.cn:7002`；域名动态解析，不固定历史公网IP |
| 校内跳板 | `10.14.115.88:22`；仅校园网或已授权网络可达 |
| 连接脚本 | `./server/start_school.sh <编号>`，支持100、101、102、103、104、127，省略默认104 |
| SSH/SCP配置 | [school_ssh_config](school_ssh_config)，使用`-F server/school_ssh_config`及`school104`等别名 |
| 私钥 / 主机记录 | `~/.ssh/zhangzibo_school`（权限600）/ `~/.ssh/known_hosts_school` |

已核验跳板ED25519指纹为`SHA256:MheEdeSO8cSm6MRZn1sehQ8T8mlTX+mjJqMXoaz3C58`；变化时先核实管理员通知，不关闭检查或清空其他主机记录。账号仅使用本人身份，平台登记、密码设置或封禁处理由用户按当前平台要求完成，不代发申诉或对外消息。

`start_school.sh`会查询公共DNS处理已知解析问题；原生SSH/SCP须使用同一已核验跳板及必要的临时DNS覆盖配置。旧截图的`183.131.137.222:2222`不再是入口，握手等待为60秒，失败区分跳板认证、账号/密钥和目标路由，不反复盲试。

## 数据盘与离线部署

| 平台 | 本人科研目录 |
|---|---|
| 学校104 | `/data2/zhangzibo/arxiv-tssa/`；产物放其`results/<run_id>/` |
| 学校103 | `/data1/zhangzibo/arxiv-tssa/` |
| AMAX | `/opt/data/private/<project>/`；产物放其`results/` |

使用前检查容量、属主与实时配额；学校个人上限按数据盘容量30%规划，并核对平台现行要求，不把模型、wheel、缓存或原图放到系统盘。换盘只能使用本人有权限的数据盘，先验证完整性再衔接路径，不自动清理既有数据；旧硬件、剩余空间及禁用卡列表见[带时间的资料索引](../storage/SERVER_INDEX.md)，不能用于当前选卡。

1. 优先复用本人已有兼容环境和资产；学校按无法直连HuggingFace/GitHub处理，在本机按冻结来源、revision、许可证、大小及SHA256逐文件准备。
2. 用[中转工具](stage_school_assets.py)传到本人数据盘并在远端比对哈希，加载模型使用本地路径及`local_files_only=True`，按需设置`HF_HUB_OFFLINE=1`和`TRANSFORMERS_OFFLINE=1`。
3. wheel须匹配服务器Linux/x86_64、Python和CUDA，不能上传Mac专用包；104的[离线安装器](install_school_offline_env.py)校验冻结清单、隔离venv及落盘目录后安装并保存导入审计，旧MVP的51个wheel只对应其原清单。
4. 本机先查可用空间，再逐文件下载、上传和验收；仅释放本任务生成且远端已核验完整的中转副本，不缓存全套大模型后才发现空间不足。
5. 传输中断先查远端完整性和当前写入者，再按工具支持续传；父进程退出不等于curl/SCP/SFTP子进程已退出，不并发写同一临时目标。

CPU导入检查仅证明依赖可导入，不证明CUDA、模型推理或完整实验成功；分别保留对应证据。旧MVP部署细节见[历史执行手册](../research/tssa_mvp_runbook.md)，当前实验以TASK绑定的环境与协议为准。

## AMAX

AMAX是另一套平台，使用`ssh amax -p <port>`；动态端口由用户提供，最后记录为`25225`，本次未重新核验，失效时等待有效入口。网页`http://127.0.0.1:8080`由`./server/start_amax.sh`建立隧道后使用，不把学校配置或AMAX历史缓存互相代用。

```bash
# 非交互执行；用实际环境名、脚本路径和当前端口替换占位符
ssh amax -p <port> "conda run -n <env> python <script.py>"
# 已获准的长任务用tmux保持会话，并使用本次唯一任务名
ssh amax -p <port> "tmux new-session -d -s <task_id> 'conda run -n <env> python <script.py>'"
```

历史AMAX曾无法直接clone GitHub：在本机clone、打包真实文件（大仓库可排除`.git`）后上传并验哈希，不能只打包兼容符号链接。历史`HF_ENDPOINT=https://hf-mirror.com`不证明当前可用，依赖版本以本次环境锁为准，不直接照搬旧安装命令升级。

| 历史缓存线索（使用前核验） | 路径 / 环境 |
|---|---|
| SD v1.5 | `/opt/data/private/models/stable-diffusion-v1-5/` |
| ViT-base-patch16-224 | `/opt/data/private/models/vit-base-patch16-224/` |
| CLIP-ViT-B/32 | `/opt/data/private/models/clip-vit-base-patch32/` |
| EvilEdit后门UNet | `/opt/data/private/EvilEdit/results/eviledit_reproduce/backdoored_unet.pt` |
| BackdoorDM | `/opt/data/private/BackdoorDM/` |
| Conda `eviledit` | 历史Python3.10 / PyTorch2.7.1+cu118 / diffusers0.38.0，不代表当前环境 |

## 断连与恢复

- Broken pipe或超时后，先检查本任务进程、日志、账本、锁及终态产物；确认尚未完成且旧执行者不会重复写入后，再按当前协议恢复，不能用`import torch`判断实验完成或直接重装。
- 怀疑ControlMaster僵死时，先针对受影响别名运行`ssh -O check amax`或`ssh -O check amax-jump`；确认没有依赖该连接的传输后，仅关闭对应连接，不批量删除socket或影响其他会话。
- 账号过期、公钥拒绝、路由失败、CUDA初始化失败分别记录原因；GPU候选切换按[统一优先级](../AGENTS.md#服务器选择优先级)，不因旧成功无限重试或把一次失败当永久不可用。
- 本文不创建或恢复监控；旧`gpu`已删除的[回执](../results/tssa-mvp-2026-10-26/automation_cleanup_20261028T1225Z.json)保留，新的监控按当前任务实际授权管理。

[服务器文件入口](README.md) · [资料位置与取回](../storage/SERVER_INDEX.md) · [新电脑接续](../storage/NEW_COMPUTER.md)
