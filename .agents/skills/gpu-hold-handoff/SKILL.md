---
name: gpu-hold-handoff
description: >-
  Scan across all configured lab servers and GPUs to locate the user's running
  gpu_squat.py hold processes, safely pause/preempt one on an unshared compliant
  GPU with exact launch-parameter capture when starting a real experiment, and
  reliably restart and verify gpu_squat.py after the experiment exits. Use whenever
  launching or finishing a GPU experiment that may reuse or restore a held GPU.
---

# GPU 占卡动态扫描、让卡与恢复（`gpu_squat.py`）

占卡进程**不固定在特定服务器或 GPU 编号**上。每次需要用卡或实验结束归还显卡时，都必须从 `./labgpu` 与远端实况重新识别节点、`GPU UUID`、进程 PID 与完整命令行参数。

## 阶段一：启动实验前扫描与安全让卡

### 1. 全局盘点与选卡决策（不要写死 `104` 或 `GPU 0`）

在仓库根目录执行：

```bash
./labgpu status --fresh --json | python3 -c '
import json, sys
d = json.load(sys.stdin)
print("account_usage:", json.dumps(d["account"]["usage"], ensure_ascii=False))
for h in d["hosts"]:
    for g in h["gpus"]:
        if g.get("status") == "free" or g.get("own"):
            print(h["id"], h["label"], g["index"], g["uuid"], "status=", g["status"],
                  "users=", g.get("users"), "mem=", g.get("memory_used"),
                  "util=", g.get("utilization_gpu"))
'
```

按以下优先级判断：
1. **优先合规 `free` 卡**：按 [AGENTS.md](../../../AGENTS.md#服务器选择优先级) 顺序（`104→103→101→127`）优先选直接可用的 `free` 卡；仅当无可用 `free` 卡、当前有效占卡数已近跨机上限（4 张）或用户明确指示替换占卡时，才选择本人占卡进行替换。
2. **筛选可替换的本人占卡目标**：仅允许选择满足以下全部条件的卡：
   - `status == "mine"` 且 `users == ["zhangzibo"]`（无任何他人共享进程 `shared_with == []`）；
   - `compute_mode == "Default"`、`status != "disabled"`、样本未过期（`sample_age_seconds < 120`）；
   - 优先挑选仅运行 `gpu_squat.py` 的节点与卡位。

### 2. 远端精准核实与参数快照（必须在停止前完成）

对选定目标节点执行一次性远端探查，核实进程命令行与卡上全部计算进程：

```bash
nvidia-smi --query-gpu=index,uuid,memory.used,utilization.gpu --format=csv,noheader
nvidia-smi --query-compute-apps=gpu_uuid,pid,used_memory --format=csv,noheader
ps -eo pid,ppid,stat,etime,args | grep -E 'gpu_squat\.py|python' | grep -v grep
```

逐项检查：
- 确认目标 `GPU_UUID` 上**只有**待让出的 `gpu_squat.py` 进程，没有任何科研训练/评测进程或他人进程；
- 完整记录以下恢复必需信息（写到本任务报告或交接状态，不要凭记忆）：
  - `host_label`（如 `school104` / `school103`）与 `host_id`
  - `gpu_uuid`（完整 `GPU-...` UUID）
  - `hold_pid`、`hold_cwd`（可用 `readlink -f /proc/<pid>/cwd` 获取）、`python_bin`
  - 完整命令行参数（重点：`--uuid`、`--state-dir`、`--memory-fraction`、`--target-utilization-percent`、`--sample-seconds`）
  - 该节点是否还有**其他** `gpu_squat.py` 进程共用同一 `--state-dir`

### 3. 安全停止占卡并确认显卡清空

根据是否共用 `--state-dir` 选择停止方式：
- **单卡独享该 `--state-dir`**：创建 `<state_dir>/STOP`（若希望保留审计日志）并等待进程自然退出；
- **多卡共用同一 `--state-dir`（或需避免波及同机其他占卡）**：使用 `kill -TERM <hold_pid>` 精确停止目标进程，不要向共享 `--state-dir` 写 `STOP`。

停止后等待并验证**显存与进程完全清空**，才允许启动实验：

```bash
nvidia-smi --query-gpu=index,uuid,memory.used,utilization.gpu --format=csv,noheader | grep "<UUID_PREFIX>"
nvidia-smi --query-compute-apps=gpu_uuid,pid,used_memory --format=csv,noheader | grep "<UUID_PREFIX>" || echo "APPS_EMPTY"
```

---

## 阶段二：实验结束后原位恢复占卡

一旦实验进程已退出且无残留：

### 1. 前置检查
1. 用 `nvidia-smi --query-compute-apps=...` 确认目标 `GPU_UUID` 当前已无任何计算进程（避免未完全退出导致 OOM 或双进程抢占）；
2. 用 `./labgpu status --fresh --json` 核对当前平台规则、该卡未 `disabled`、无 `stop_required=true`，且跨机额度仍允许重启（不超过 `cap`）；若平台或用户明确禁止继续占卡，则**不要重启**并如实报告；
3. 检查原 `<state_dir>/STOP` 是否存在；仅在确认安全恢复时执行 `rm -f <state_dir>/STOP`。

### 2. 完全脱离终端重启 `gpu_squat.py`

> **关键防坑**：通过 SSH 远端命令（例如 `observer.py --action exec`）启动守护进程时，必须使用 `setsid` 并重定向 `stdin/stdout/stderr` 到日志文件与 `/dev/null`，否则 SSH 管道会被子进程继承，导致命令挂起超时。

```bash
cd <hold_cwd> && \
  rm -f <state_dir>/STOP && \
  setsid <python_bin> -u gpu_squat.py \
    --uuid <gpu_uuid> \
    --state-dir <state_dir> \
    <原有可选参数如 --memory-fraction 等> \
    >> <state_dir>/worker.log 2>&1 < /dev/null &
```

### 3. 三重实况验收（缺一不可）

重启后等待约 5–10 秒，同时验证三项真实指标（不能只看下发了启动命令）：
1. **远端进程与日志**：`ps -p <new_pid> -o pid,ppid,stat,etime,args` 处于运行态（`Rsl`/`Ssl`），且 `<state_dir>/<gpu_uuid>.md` 或 `worker.log` 出现 `"event": "allocated"` 与 `"event": "sample"`；
2. **远端设备实测**：`nvidia-smi` 显示目标 `GPU_UUID` 存在新 `PID`，已分配目标显存（约 65% 设备显存）且 GPU 利用率开始回升；
3. **平台账面一致**：运行 `./labgpu status --fresh --json`，确认该节点该卡呈现 `status: "mine"`、进程 `pids` 含新 PID、`shared_with: []`。

如仓库中有对应占卡任务记录（如 `research/tasks/2026-11-13-gpu-half-hour-hold/TASK.md`）或当前实验 `TASK.md`，同步更新新 PID、交接原因与最新验证时间。
