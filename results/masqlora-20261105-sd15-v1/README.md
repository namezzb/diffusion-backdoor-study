# MasqLoRA SD1.5 cat目标运行

任务状态见[唯一TASK](../../research/tasks/2026-11-05-masqlora-reproduction/TASK.md)，配置与验证见同目录实现报告。

- 104准备目录：`/data2/zhangzibo/arxiv-tssa/preparations/masqlora-20261105/`
- 104原始run：`/data2/zhangzibo/arxiv-tssa/results/masqlora-20261105-sd15-v1/`
- 子组：`masq/`、`poisoned/`、`benign/`。
- 每组`events.md`为追加的逐步/逐图记录；`summary.md`为可重算汇总；`adapter.safetensors`是独立LoRA；`checkpoint.pt`保留优化器进度；`verified.md`绑定导出哈希及全新底座复载误差；原图保留`images/{benign,trigger}/`。
- 本机`observer.md`和`observer.log`是运行期平台观察，不进Git；它们不是实验结果。一次运行结束后观察器退出。

所有组的seed相同，可配对比较；本轮数据只覆盖cat目标。代理评分、样本数与未提供的论文指标须同时报告。启动预览不构成全量复现结论。
