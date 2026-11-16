# 每半小时检查空闲 GPU

- status: in_progress
- authorization: 2026-11-13 用户授权每半小时检查空卡，有合规空卡启动本人现有占卡程序；不得修改程序，实际启动成功后简短告知。
- automation: `gpu`，ACTIVE，当前聊天 heartbeat，每30分钟，无预设截止日期。
- entry: `scripts/connection/gpu_squat.py`，使用已有环境与参数，必要时原样部署；不得改写程序。
- constraints: 遵守 AGENTS.md 平台实时许可、额度及停止规则；跳过用户明确无权限的101；不重复启动已有进程，不干扰真实实验。103存在历史CUDA初始化挂起，实际启动需验证。
- next_action: 定时触发后执行 fresh 查询，在合规空卡上启动原程序，以日志、实际CUDA分配及GPU负载确认成功。
- outcome: 127 GPU2 已确认启动占卡成功，PID `759253`（前次 104 GPU0 PID `2787693` 已于 11-14 14:05 `STOP` 退卡，当前 104 GPU0/4 为他人占用；程序未修改）。
- latest_check: 2026-11-16 18:33，经用户授权在当前空闲的 `iipl-127` GPU2（`GPU-1805e9be-7fea-3c9f-afdf-32db622c0b91`, RTX 4080 `16376 MiB`）原样部署 `scripts/connection/gpu_squat.py`（SHA256 `893e673c...` 一致）并在 `--state-dir /data1/zhangzibo/arxiv-tssa/results/gpu-half-hour-hold-20261116` 启动（`PID=759253`, `--memory-fraction 0.65 --target-utilization-percent 65 --sample-seconds 10.0`）；三重实况验收通过：进程 `Ssl`、日志 `allocated`（162 blocks）+ `sample`、实测显存 `10713 MiB / 16376 MiB`、GPU 利用率 `35%`、`./labgpu status --fresh` 显示 `iipl-127 GPU2` `status="mine"`, `own=True`, `users=['zhangzibo']`。
