# 实验完成后的独立 GPU 保留任务

当前用户授权在 `tcl-20261103-semantic-v1` 实验结束后，尝试保留最多两张卡，目标是实测设备计算利用率与显存使用率均大于60%，直到用户停止。任务使用独立进程、租约、状态、日志及身份，不改写科学账本、不增加科学尝试；保留开始前须重新核验平台和现场许可。平台会对已核实的显存预占进程单独计时，规则、整改及有效停止要求以实时平台为准。

控制器只在源实验已完成全部1024个固定单元、四阶段和正式终态，科学writer及launcher锁均释放后接续；时间耗尽、部分终态或工程故障不会启动保留。它只在源实验节点（当前已配置的103或104）申请最多两张合规空卡，优先原卡，并在第一张已取得而第二张后来可用时尝试补足。实验进程退出与新进程启动有间隙，无法保证原卡一定能重新取得；两卡和目标利用率也不能保证。

## 在真实实验启动后配置

等待器可在语义运行清单建立后立即配置，不等首图；它只观察完成状态，不会提前占卡。实验是否真正跑通仍以真实模型加载、新PNG、评分及账本增长为准。

```sh
.venv/bin/python scripts/connection/gpu_hold_controller.py configure \
  --config /Users/zzb/.config/labgpu/gpu-hold/config.json \
  --semantic-manifest /Users/zzb/.config/labgpu/tcl-semantic/manifest.json \
  --until-stopped \
  --compute-target-percent 65 --memory-target-percent 65 --max-cards 2
```

配置自动读取平台快照并记录规则哈希，不要求人工填写审批参数；配置成功并不代表平台单独批准或已经通过资源许可。实际申请和续租时继续核对实时资源、规则、配额和有效停止要求。

配置后同轮启动 `await` 后台等待器，不依赖半小时心跳发现终态。使用权限0700的状态目录和0600日志：

```sh
umask 077
mkdir -p /Users/zzb/.config/labgpu/gpu-hold
nohup /Users/zzb/arxiv/.venv/bin/python /Users/zzb/arxiv/scripts/connection/gpu_hold_controller.py \
  await --config /Users/zzb/.config/labgpu/gpu-hold/config.json --activate \
  > /Users/zzb/.config/labgpu/gpu-hold/await.log 2>&1 &
```

等待器以独占锁运行；核对本run完整终态、四阶段和账本完成数及写者已退出后即可交接。逐图PNG哈希与评分核验移到后台，完成前状态是`pending`，不能声称结果已核验；核验失败会记录并停止本任务保卡。该核验不重新运行评分器，也不是逐图人工语义验收。等待器网络异常退出会写 `events.jsonl` 和 `wait-status.json`；后续定时检查按状态修复并独占重启，不重新启动科学run。

## 状态、停止和恢复

```sh
.venv/bin/python scripts/connection/gpu_hold_controller.py status --config /Users/zzb/.config/labgpu/gpu-hold/config.json
.venv/bin/python scripts/connection/gpu_hold_controller.py stop --config /Users/zzb/.config/labgpu/gpu-hold/config.json
.venv/bin/python scripts/connection/gpu_hold_controller.py resume --config /Users/zzb/.config/labgpu/gpu-hold/config.json --activate
```

`stop` 持久记录用户停止并核对本任务进程身份；`stop_pending` 或 `lease_expired_worker_exit_unverified` 都不等于已确认释放。用户明确停止后不自动恢复。只有未收到用户停止、旧worker已经确认退出且平台重新许可时，才可用 `resume` 重新申请，不能重用旧租约或清除停止标记。

观察器持续查询平台并发放短租约，真实禁用、有效停止或无法验证许可时撤租；自动解析目前只识别结构化 `stop_required=true`，不能保证识别自由文本或未知结构中的有效停止要求；仍需结合平台通知处理。GPU/进程原始采样的有效截止不因续租延长。网络中断后worker最迟按租约失效退出，实际CUDA驱动卡死时不保证硬实时终止。worker分别记录真实设备GPU利用率、设备显存与本PID显存；65%是反馈目标，不是已达标结果，须看真实采样时序。

## 当前验证范围

控制器及worker的33项CPU假设备与子进程测试通过，真实平台规则查询通过；尚未在远端部署或执行保留任务，尚未验收真实自动交接、两卡或任一60%指标。真实资源可用后必须继续验证PID、UUID、设备与进程显存、利用率时序、观察器、停止和释放，不能把模拟测试当成GPU成功。
