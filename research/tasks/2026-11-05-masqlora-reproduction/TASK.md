# MasqLoRA 复现与 LoRA 融合攻击材料

| 字段 | 值 |
|---|---|
| task_id | MASQLORA-20261105-01 |
| status | in_progress |
| outcome | pending |
| run_id | masqlora-20261105-sd15-v1 |
| authorization | 2026-11-05 用户要求阅读 paperlist 中 MasqLoRA 及相关 LoRA 攻击，准备复现材料、验证真实启动，再直接使用104上本人两张卡启动重要结果的完整复现 |
| current_stage | 三组训练、真实断点恢复、全新底座复载及24张启动出图/评分已通过；2026-11-09 本机 labgpu 登录和实时平台查询通过，但平台显示本人当前占用0卡；跳板 SSH 已认证，104目标主机和远端 run 进度待核验 |
| next_action | 恢复可信104目标主机记录并验证目标连接，再只读核对同一run进度；确认资源许可后接续同一run至三组各5000正常图+5000触发图，汇总完整代理指标 |

## 范围

主论文 [When LoRA Betrays](https://arxiv.org/abs/2602.21977v4)，官方代码 [spectre-init/MasqLora](https://github.com/spectre-init/MasqLora)。优先复现 SD1.5 对象后门的 MasqLoRA、普通 Poisoned LoRA、Benign LoRA 对照，保留后续融合研究可用的独立适配器与配对评估材料。SDXL、消融及组合结论根据公开资产与确切协议进一步安排；不把协议替代称为论文数值复现。

新实验独立记账，不恢复或改写旧 TCL 科学结果。新进度与评估记录采用 Markdown，不使用锁或独占文件。正式配置固定后，工程修复不重置消耗或覆盖已有有效结果。

## 资源交接

平台初查显示104 GPU0、GPU2为本人 `gpu_squat.py`。交接前核实实际进程、UUID、占用、平台停止要求和跨机额度；只停止核实属于本人的占卡进程，用真实有限实验替换。平台当前104进程采样不完整，需设备侧补充核验。旧103状态未知计入保守额度，不在本任务重启。

2026-11-05已完成交接：GPU0执行Masq，GPU2依次执行Poisoned和Benign；旧占卡目录已写STOP，不能补建占卡负载。本机资源观察器须保持在线；断网/观察过期会释放CUDA并保留进度，观察恢复且设备空闲时续跑。原始图、三组适配器及检查点均留104。

2026-11-09 新本机 `./labgpu status --fresh --json` 登录与实时平台查询通过，平台账号占用为0/4；104当前返回4张他人使用、1张禁用，没有本人占卡记录。该查询不验证远端实验目录状态。GPU占用脚本仅完成本机语法与帮助入口检查，没有启动占卡进程。恢复私钥后跳板 SSH 认证已通过；104目标节点的可信主机记录仍缺，尚未发起目标节点连接。详见 [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md) 的“本机接续检查”。

## 首批结果的边界

首4张触发图中，Masq的CLIP/ViT猫分类为4/4，Poisoned和Benign均为0/4；三组首4张正常图均判为汽车。仅作真实启动和效果方向验证，不能据此宣称论文99.8%已复现。完整评估尚未完成，科研outcome保持pending。

实现、来源、测试与限制持续更新于 [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md)。
