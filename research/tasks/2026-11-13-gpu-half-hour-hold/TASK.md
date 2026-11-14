# 每半小时检查空闲 GPU

- status: in_progress
- authorization: 2026-11-13 用户授权每半小时检查空卡，有合规空卡启动本人现有占卡程序；不得修改程序，实际启动成功后简短告知。
- automation: `gpu`，ACTIVE，当前聊天 heartbeat，每30分钟，无预设截止日期。
- entry: `scripts/connection/gpu_squat.py`，使用已有环境与参数，必要时原样部署；不得改写程序。
- constraints: 遵守 AGENTS.md 平台实时许可、额度及停止规则；跳过用户明确无权限的101；不重复启动已有进程，不干扰真实实验。103存在历史CUDA初始化挂起，实际启动需验证。
- next_action: 定时触发后执行 fresh 查询，在合规空卡上启动原程序，以日志、实际CUDA分配及GPU负载确认成功。
- outcome: 104 GPU0已确认原程序重新启动占卡成功，PID `2787693`（前次 PID `2314838` 交接完成 `lora-comp-mvp-20261114-baseline-fix`）；程序未修改。
- latest_check: 2026-11-14 11:27，在 `lora-comp-mvp-20261114-baseline-fix` 完成且确认 GPU0 显存完全释放后，已清除 `STOP` 并在 11:25:30 原样重启 `gpu_squat.py`（PID `2787693`，实测显存 `16192 MiB` / 总 `16249 MiB`、GPU 利用率 `50%~53%`，`labgpu status --fresh` 显示 `status: "mine"`）。
