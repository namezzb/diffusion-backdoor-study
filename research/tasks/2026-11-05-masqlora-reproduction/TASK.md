# MasqLoRA 复现与 LoRA 融合攻击材料

| 字段 | 值 |
|---|---|
| task_id | MASQLORA-20261105-01 |
| status | in_progress |
| outcome | pending |
| run_id | masqlora-20261105-sd15-v1 |
| authorization | 2026-11-05 用户要求阅读 paperlist 中 MasqLoRA 及相关 LoRA 攻击，准备复现材料、验证真实启动，再直接使用104上本人两张卡启动重要结果的完整复现 |
| current_stage | 三组训练、真实断点恢复、全新底座复载及24张启动出图/评分已通过；MasqLoRA run 于2026-11-05因设备状态查询超时停止，评估不完整；每小时占卡自动化至2026-11-12 09:21:37，101按用户要求跳过。103 SSH已成功但CUDA初始化挂起；已改选104并于2026-11-11 10:57（Asia/Shanghai）在GPU0启动限时gpu_squat worker，日志确认显存分配与计算采样正常 |
| next_action | 自动任务每小时检查但不重复启动已运行的worker；监视104 GPU0 worker并在2026-11-12 09:20:50前由timeout自动结束，截止后核实worker和限时器均退出；103 CUDA初始化问题仍需单独定位，科研run仍需针对性修复设备状态查询超时后再续跑 |

## 范围

主论文 [When LoRA Betrays](https://arxiv.org/abs/2602.21977v4)，官方代码 [spectre-init/MasqLora](https://github.com/spectre-init/MasqLora)。优先复现 SD1.5 对象后门的 MasqLoRA、普通 Poisoned LoRA、Benign LoRA 对照，保留后续融合研究可用的独立适配器与配对评估材料。SDXL、消融及组合结论根据公开资产与确切协议进一步安排；不把协议替代称为论文数值复现。

新实验独立记账，不恢复或改写旧 TCL 科学结果。新进度与评估记录采用 Markdown，不使用锁或独占文件。正式配置固定后，工程修复不重置消耗或覆盖已有有效结果。

## 资源交接

平台初查显示104 GPU0、GPU2为本人 `gpu_squat.py`。交接前核实实际进程、UUID、占用、平台停止要求和跨机额度；只停止核实属于本人的占卡进程，用真实有限实验替换。平台当前104进程采样不完整，需设备侧补充核验。旧103状态未知计入保守额度，不在本任务重启。

2026-11-05已完成交接：GPU0执行Masq，GPU2依次执行Poisoned和Benign；旧占卡目录已写STOP，不能补建占卡负载。本机资源观察器须保持在线；断网/观察过期会释放CUDA并保留进度，观察恢复且设备空闲时续跑。原始图、三组适配器及检查点均留104。

2026-11-09 新本机 `./labgpu status --fresh --json` 登录与实时平台查询通过，平台账号占用为0/4；104返回4张他人使用、1张禁用，127返回4张他人使用，两节点均采样完整，无空闲卡。已恢复私钥并通过固定跳板及节点主机密钥的严格SSH连接；远端run确认不完整且无worker进程。占卡程序本地/远端帮助检查通过但没有启动负载。详细证据见 [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md) 的“本机接续检查”。

2026-11-10 01:49 fresh平台状态显示101有两张空闲候选，账号使用0/4、管理规则启用、无待处理GPU申请；但该节点拒绝当前SSH公钥，且本轮已停止重复探测。按用户授权，经 Codex 自动化 `gpu-08-00` 每90分钟检查至08:00；只对可严格验证且当前许可合规的节点启动至多一张卡，未启动负载不算占卡成功。

2026-11-10 09:16 用户说明101暂不开放后，fresh平台复查显示101四张卡空闲候选，但按用户最新指示跳过；104、127及其他可见节点没有空闲候选，账号占用0/4。原自动化截止时间08:00已过，已通过 `automation_update` 删除 `gpu-08-00`；全程没有启动占卡进程。

2026-11-10 09:21 用户重新授权占卡检查，间隔改为每小时、持续48小时。通过 Codex 自动化 `gpu-48` 建立 ACTIVE 心跳任务，截止2026-11-12 09:21:37（Asia/Shanghai）；按用户要求持续跳过101。创建时立即执行fresh状态核查：账号0/4、无active ban、无维护、GPU管理规则启用；104/127/201/204/206在线且采样完整，但没有free卡；103节点离线且采样过期，100节点GPU采样数量不完整；101有free候选但不连接。无合规目标，本轮未启动占卡worker。自动化依赖本机和Codex桌面应用保持运行。

2026-11-10 13:40（Asia/Shanghai）自动化本轮fresh状态显示103恢复在线，采样/进程状态完整，有3张free卡；账号0/4，无active ban/维护，规则启用。101也有free卡但按用户要求跳过。读取`school_ssh_config`后对`school103`仅进行一次`StrictHostKeyChecking=yes`连接，因`~/.ssh/known_hosts_school`没有该节点ED25519记录而失败（`No ED25519 host key is known for 192.168.1.103`）；没有接受未知key或启动worker。已更新`gpu-48`自动化：用户补齐103可信主机身份记录前跳过103，其余节点照常每小时筛查；无其他可用候选时不启动。

2026-11-10 16:18（Asia/Shanghai）用户明确要求跳过103主机密钥核验直接连接。临时SSH配置仅对`school103`使用`StrictHostKeyChecking=accept-new`并写入`~/.ssh/known_hosts_school`；`school-jump`仍严格校验。连接成功，实际主机`iipl-103`、账号`zhangzibo`，`/data1/zhangzibo/arxiv-tssa`存在且可写；后续恢复对103的严格校验。平台状态fresh，账号占用0/4、无active ban/维护、GPU管理开启；103在线且采样完整，GPU0 `GPU-a00d7f16-dee6-f32a-eb89-dde4590ba523`通过平台及设备侧空闲检查，compute mode Default、15MiB已用、GPU利用率0%，设备进程列表未见该UUID进程；GPU1亦为平台free。系统Python没有torch，本人`/data1/zhangzibo/arxiv-tssa/venv/bin/python`可导入torch2.7.1+cu128，但`torch.cuda.is_available()`探针绑定GPU0后超过22秒不返回。探针进程145755经SIGTERM未退出，随后已确认退出；没有遗留进程。未部署gpu_squat脚本或启动worker，避免CUDA初始化挂起留下无效占卡进程。`gpu-48`自动化已更新：103主机key现已固定，后续对其使用严格校验；在CUDA初始化问题解决前不在103启动worker，其他节点仍按原规则检查，101继续跳过。

2026-11-10 16:24（Asia/Shanghai）用户要求去掉103因未知主机密钥而无法连接的门槛。已更新`gpu-48`：103缺少本机记录时可使用`StrictHostKeyChecking=accept-new`自动保存密钥，不再等待管理员提供指纹；`school-jump`仍严格校验，其他主机身份策略不变。此前已成功连接103，实际阻碍占卡的当前问题为PyTorch CUDA初始化挂起，该运行时问题仍需解决。

2026-11-10 22:51（Asia/Shanghai）`./labgpu status --fresh --timeout 20 --json`返回“登录已失效或无权访问，请运行 labgpu.py login”。不能用旧状态代替实时额度和许可，故本轮不启动占卡。最近一次有效平台状态在2026-11-10 21:31显示账号0/4且只有101、103有free卡；101继续跳过，103仍受CUDA初始化挂起限制。需要用户在本机重新运行`./labgpu login`；自动化保持ACTIVE并在后续轮次重新查询。

2026-11-11 10:58（Asia/Shanghai）用户报告已重新登录，fresh平台查询恢复成功：管理开启、无active ban/维护/申请/整改/案件，平台账号占用0/4；104、103与201均有free候选，按优先级选择104 GPU0 `GPU-0fc254b8-f4f9-2382-8d33-71c99526fb1b`。SSH `school104`严格校验连接成功；启动前nvidia-smi确认compute_mode Default、52MiB显存、0%利用率，目标UUID进程列表为空；本机与远端`gpu_squat.py` SHA256一致（`893e673cd44a40f9a909d48bbdbe0b06be3cd11a4207e52795edf9c9c3ae4d8f`），无已有gpu_squat worker。以`/data2/zhangzibo/arxiv-tssa/venv/bin/python`启动worker PID 3546716，由GNU timeout PID 3546711限制80600秒，确保在2026-11-12 09:21（Asia/Shanghai）前退出；状态及日志位于`/data2/zhangzibo/arxiv-tssa/results/gpu-hold/gpu-48-20261111T025650Z-104-gpu0/`。worker日志记录目标显存分配约65%，设备显存约16.2GiB，首批GPU利用率39–40%，反馈占空比持续上调。启动后fresh平台状态将该UUID列为本人使用，PID及显存约16192MiB与远端日志相符；平台usage字段仍显示0/4，本任务实际只占用这一张卡。自动化保持ACTIVE，后续只核验本任务worker、不重复启动；101继续跳过。

## 首批结果的边界

首4张触发图中，Masq的CLIP/ViT猫分类为4/4，Poisoned和Benign均为0/4；三组首4张正常图均判为汽车。仅作真实启动和效果方向验证，不能据此宣称论文99.8%已复现。完整评估尚未完成，科研outcome保持pending。

实现、来源、测试与限制持续更新于 [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md)。
