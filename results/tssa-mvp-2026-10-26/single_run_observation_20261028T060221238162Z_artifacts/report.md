# TSSA 梯度版初步验证

本报告只描述冻结方案的实际运行结果，不作 FID、显著性或 SOTA 结论。

| 方法 | 冻结候选 | 最低 ASR | 平均 ASR | 正常指标门禁 |
|---|---|---:|---:|---|
| naive | naive | 0.1875 | 0.5156 | True |
| Uniform | Uniform-GD_step24 | 0.0000 | 0.0000 | True |
| RC-TSSA-GD | RC-TSSA-GD_step24 | 0.0000 | 0.0000 | True |

逐样本和逐状态证据见 heldout_per_image_metrics.jsonl、heldout_report.json；中断和诊断额外计算见 resource_ledger.json。
