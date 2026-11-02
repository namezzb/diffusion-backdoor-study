# TCL v1历史定位验证运行

运行身份 `tcl-20261029-01-v1`，冻结清单 SHA-256 为 `c597deebc3c2256401ee89b47f96ba9caa4bd92502019e3f257cfde7cddd1aaa`；[任务正文](../../../research/tasks/2026-10-29-trigger-contrast-localization/TASK.md)是里程碑状态和授权范围的唯一来源。

2026-11-02起改按[24小时v2协议](../../../research/tasks/2026-10-29-trigger-contrast-localization/PILOT24_PROTOCOL_2026-11-02.md)准备新run，v1不再补满原预算，旧有限追加提案未获批准。以下表格及恢复说明保留v1历史时点，不能作为当前启动指令；新成果见[v2入口](../tcl-20261102-pilot24-v2/README.md)。

| 入口 | 作用 |
|---|---|
| [恢复指导](../../../research/tasks/2026-10-29-trigger-contrast-localization/RECOVERY_HANDOFF_2026-11-02.md) | 不整轮重跑，核验已有定位和图片、汇总账本并审阅中断恢复；完成度见任务正文 |
| [验收报告](acceptance_report.md) | 当前是未完成报告，依据11月2日09:34保存观察，127超时退出且103不可达；本次文档更新没有新增远端核验 |
| [资源与启动证据](../../../research/tasks/2026-10-29-trigger-contrast-localization/server103_localization_start_20261029.json) | 103 GPU 2 实时许可及真实定位前向启动 |
| [源阶段首批与首图证据](../../../research/tasks/2026-10-29-trigger-contrast-localization/server103_source_initial_images_20261029.json) | 首图远端哈希与账本一致；后续342张完成图已在故障观察后盘点 |
| [设备故障与图片盘点](../../../research/tasks/2026-10-29-trigger-contrast-localization/server103_gpu_failure_20261030.json) | 历史343张完成图远端哈希核验；当时GPU故障且原锁仍持有，当前锁状态未知 |
| 服务器运行目录 | `school103:/data1/zhangzibo/arxiv-tssa/results/tcl-20261029-01-v1/`；原锁状态当前无法核实，尚无终态账本盘点或文件哈希 |
| 服务器源码和日志 | `/data1/zhangzibo/arxiv-tssa/code/tcl-20261029-01-run-c597deeb/`；`/data1/zhangzibo/arxiv-tssa/preparations/tcl-20261029-01-v1-localize.log` |

不要把运行中账本当作最终备份；终态后须按实际产物逐项登记来源、大小、哈希和取回验收。
