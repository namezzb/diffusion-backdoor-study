# MasqLoRA 对象替换的输出审计

| 字段 | 值 |
|---|---|
| task_id | MASQLORA-AUDIT-20261112-01 |
| status | done |
| outcome | 预设主指标未改善。观察到同等最差分组报警率下的历史正例召回增益。 |
| run_id | `masqlora-output-audit-20261112-v1` |
| normal_controls_run | `masqlora-clean-controls-20261112-v1` |
| authorization | 2026-11-12 用户授权首轮文献分析、提出改进并用现有资产实证验证，最多一张合规 GPU、4 小时、20 次尝试。被本任务替换的原占卡进程须在实验结束后按平台许可恢复。 |
| next_action | 另建独立验证，以实际正常 LoRA、未见模板和独立目标测试同误报预算下的召回。与 TS-I、UFID 和媒介匹配的主体评分同台比较。 |

## 研究问题

给定声明的主对象，按正常构图和媒介校准图像证据，能否减少对正常个性化生成的误报，并保持对现有 MasqLoRA 对象替换结果的敏感度？

- [正常生成协议](collection/BRIEF.md) · [固定提示与 seed](collection/candidate/controls.json)
- [审计协议](audit/BRIEF.md) · [评价和判据](audit/config.json)
- [实现、证据与论文切入点](IMPLEMENTATION_REPORT.md)
- [原 MasqLoRA 复现任务](../2026-11-05-masqlora-reproduction/TASK.md)
