# MasqLoRA 复现执行器

任务与证据见[当前复现任务](../../../research/tasks/2026-11-05-masqlora-reproduction/TASK.md)。固定配置来自任务目录，官方源码和数据固定到明确 commit；`runtime.py` 从官方源码直接加载图像处理与对比损失函数，其余实现负责离线加载、纯 LoRA 训练、可恢复检查点、导出复载验证、有限生成和评分。

```bash
# 在104准备目录中直接调用runtime时，需要本任务独立依赖目录。
export PYTHONPATH="/data2/zhangzibo/arxiv-tssa/preparations/masqlora-20261105/vendor:${PYTHONPATH:-}"
python runtime.py --config /path/config.json --arm masq --run-root /path/run --uuid GPU-... train
python runtime.py --config /path/config.json --arm masq --run-root /path/run --uuid GPU-... verify
python runtime.py --config /path/config.json --arm masq --run-root /path/run --uuid GPU-... evaluate --limit 4
python runtime.py --config /path/config.json --arm masq --run-root /path/run --uuid GPU-... evaluate
python runtime.py --config /path/config.json --arm masq --run-root /path/run --uuid GPU-... report
```

`--arm` 为 `masq / poisoned / benign / base`，base仅评估。训练 `--stop-after` 用于真实中断/续跑验收，不改变固定总训练步数。每个arm由唯一指定worker串行写入，无锁且不保证并发安全。进度和评分写Markdown，权重和优化器保留二进制格式；失败尝试保留，已有图像续评分。`permission.md` 是有时效的资源观察，不是互斥或独占凭据；缺失、过期、STOP或指定卡禁用时停止计算。

`control.py watch` 在本机持续观察同一有限run；`launch.py` 在104核对既有worker与显卡进程后启动指定分组。`worker.py`遇资源观察失效时释放CUDA并等待，观察恢复且设备无人使用后自动续跑；用户STOP/SIGTERM、预算耗尽、普通代码错误不自动重启。停止整个run用其目录的`STOP`文件，停止旧占卡程序用旧`gpu_squat_run/STOP`，两者不要混淆。当前分工：GPU0执行masq；GPU2依次执行poisoned、benign。完成三组后观察器退出。

平台优先走labgpu CLI；CDN连接超时时通过实时公共DNS切换连接地址，HTTPS仍校验原域名，禁止重定向，并重新取得平台响应。该备用路径不使用历史缓存作为许可。本机离线会暂停计算，不能只看到worker PID就宣称实验持续运行。

`prepare_assets.py /path/upstream`获取固定commit的18份公开文件并生成清单；传入服务器后按任务`ASSETS.md`核对。固定配置与脚本部署到上述准备目录，模型沿用配置列出的104本地资产。新机器不能只复制代码便假定资产已齐全，须按清单恢复；接续既有run保持其config、adapter及events不变，不重新执行`handover.py`。

纯LoRA采用 `bias=none`；UNet/TE导出时将alpha/r缩放折入B矩阵，复载与内存模型前向对比通过后才允许扩大生成。数据、软件、评分与论文的差异必须查实现报告。代理ASR、单目标结果和缺少FID/LPIPS不能标作论文表1严格复现。
