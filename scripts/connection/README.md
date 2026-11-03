# 连接与 GPU 工具

操作步骤见[服务器手册](../../server/OPERATIONS.md)，实时状态和启动授权见当前 TASK。

## 连接、离线部署与资料回传

| 工具 | 用途与执行边界 |
|---|---|
| [labgpu.py](labgpu.py) · [使用说明](LABGPU.md) | 平台 API 显卡状态查询、登录、表格/JSON、短缓存与新鲜度判断；不启动实验。 |
| [实验后 GPU 保留](GPU_HOLD.md) | 独立等待器、观察器及负载进程；仅实验完整终态和实时许可核验后启用，验证范围见说明。 |
| [archive_school_research.py](archive_school_research.py) | 只读盘点和回传学校服务器既有科研资料，按文件清单核对大小与哈希；不下载新模型或启动实验。 |
| [probe_school_gpu.py](probe_school_gpu.py) | 按统一优先级有界只读检查学校节点连接、GPU身份及进程；不恢复已删除的旧定时探针。 |
| [start_school.sh](../../server/start_school.sh) · [school_ssh_config](../../server/school_ssh_config) | 学校跳板与节点连接、动态DNS回退及主机密钥检查。 |
| [stage_school_assets.py](../../server/stage_school_assets.py) | 固定公开revision逐文件下载、中转上传及远端哈希核验，不选择GPU；当前不启动新资产下载。 |
| [install_school_offline_env.py](../../server/install_school_offline_env.py) | 验证冻结Linux依赖后安装本人数据盘环境；104和103各轮实际环境证据见运行记录。 |
| [中转检查](../../server/test_stage_school_assets.py) · [分块检查](../../server/test_stage_school_chunk_upload.py) · [安装器检查](../../server/test_install_school_offline_env.py) | 本机CPU检查传输恢复、文件完整性、路径限制和离线安装，不证明实时连接可用。 |
| [start_amax.sh](start_amax.sh) | macOS AMAX隧道与交互连接，包含DNS回退和网页就绪检查；当前端口以用户最新提供为准。 |
| [start_amax - ip.bat](<start_amax - ip.bat>) | Windows历史AMAX连接辅助，未经本轮运行核验。 |

AMAX启动器默认转发网页到`http://127.0.0.1:8080`、HTTPS到`8443`，保留DNS回退与主机密钥校验；该连接信息仅为工具说明，不是暂停期间启动服务的要求。学校连接及远端路径见[服务器资料索引](../../server/README.md)，实际许可与实验状态以[AGENTS.md](../../AGENTS.md)为准。

[脚本总索引](../README.md)
