# TCL 语义评分与完整对照验证

| 字段 | 值 |
|---|---|
| task_id | TCL-SEMANTIC-20261103-01 |
| status | in_progress |
| implementation_status | done（本地实现；新版远端部署待完成） |
| experiment_status | 103 网络不可达，远端进程与产出未知 |
| outcome | pending |
| run_id | tcl-20261103-semantic-v1 |
| updated_at | 2026-11-03T20:50:00+08:00 |
| authorization | 用户授权修正评价并完成固定 TCL 验证、半小时检查；实验完成后按实时规则尽量保留最多两卡。普通工程故障持续修复；11/3另授权利用等待时间整理仓库 |
| current_stage | 19:18 已进入第一次 GPU 推理，首张 PNG 和完整评分尚未核实；随后连接失联 |
| next_action | 103 连接恢复后先读取旧进程、账本和产物；确认旧执行退出后，按原科学配置、T0 和尝试预算衔接新执行器 |
| automation | 20:45 本机配置为 PAUSED，最后更新时间20:43；原调度每小时整点/半点。暂停原因未核实，本次整理不改变调度 |

## 最新可核实证据

- **GPU**：11/3 19:18:12.293+08 实际预检通过，记录 T0；第1次尝试已有 text encoder 前向2次、UNet前向1次。首图、完整评分、后续完成数量及当前进程均未核实。
- **网络**：本聊天直接 SSH 补查，公网跳板严格主机校验及公钥认证成功，转发到 `192.168.1.103:22` 返回 `No route to host`。没有执行到103上的 `nvidia-smi`、进程或账本查询；不能据此判定其硬件故障或实验终态。
- **平台与观察器**：20:45平台查询成功，103采样仍停在约19:18，全局无确认可用空卡；本机旧观察器进程存在但连接持续失败。平台0/4不证明103原任务已退出。
- **工程**：评分校准、真实CPU准备及本地模拟检查已有证据；无锁执行、Markdown账本和轻量启动的新代码尚未部署到103。详细验证范围见[实现报告](IMPLEMENTATION_REPORT.md)。

## 固定运行与恢复

[协议](PROTOCOL.md)和[机器配置](protocol.json)固定1024唯一图、1056次尝试、1张GPU、四阶段对照。T0为11/3 19:18:12.293+08，6小时预算对应11/4 01:18:12.293+08截止，暂停与断连间隔计入；这是预算推算，不代表已记录终态。

- 103准备目录：`/data1/zhangzibo/arxiv-tssa/preparations/tcl-20261103-semantic-v1/`。
- 103结果目录：`/data1/zhangzibo/arxiv-tssa/results/tcl-20261103-semantic-v1/`。
- 本机控制器状态：`~/.config/labgpu/tcl-semantic/`；启动、恢复及只读报告见[执行器入口](../../../scripts/merging/trigger_contrast_localization/README.md)。
- 保留原SQLite、科学配置、T0、失败计费及既有结果。已完整结果跳过，有有效图片继续评分；远端状态未知时不覆盖旧运行，新代码无并发互斥保证。

## 交接与验收

用户按需选择 Astra/Terra session，当前 session 直接推进授权范围。实际完成标准为加载→生成→PNG→完整评分→账本，并完成四阶段对照或记录明确的协议终态；方法效果以预定指标解释。

实验完整终态后，GPU保留按[独立工具说明](../../../scripts/connection/GPU_HOLD.md)、用户参数及实时规则执行，尚无真实交接验收。此前记录的临时防休眠预计11/4 10:29到期，是否仍有效须按进程身份核实。

当日详细过程、早期资源观察及已被替代的状态统一见[过程历史](HISTORY.md)；实现与测试记录见[实现报告](IMPLEMENTATION_REPORT.md)。本次目录整理记录见[维护任务](../2026-11-03-repository-organization/TASK.md)。
