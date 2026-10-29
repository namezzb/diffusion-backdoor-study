# TSSA 训练轨迹 CPU 审计

结果：**passed**；4513项检查，0项不一致。
记录更新数：144；CPU Adam重放更新数：144。

| 方法族 | 记录步数 | 最终a,b | 最大重放系数误差 | 首次触及下界(a,b) |
|---|---:|---|---:|---|
| Uniform-GD | 48 | [0.0, 0.0] | 5.9604645e-08 | [12, 12] |
| TSSA-GD | 48 | [0.0, 1.0] | 7.4505806e-09 | [6, None] |
| RC-TSSA-GD | 48 | [0.0, 0.0] | 5.9604645e-08 | [19, 9] |

本审计仅核对记录的一致性并以真实CPU PyTorch Adam重放记录梯度；未重新执行UNet或读取独立持出结果，不能据此判断方法有效。
系数落到0或其它边界不算错误；不修改阈值或掩盖不一致。


## 输入SHA256

- `/Users/zzb/arxiv/research/tssa_mvp_2026-10-26.json`：`8f74590f12514f63239448783adc6187422518defc52ec46f014ffb99887e48c`
- `/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T033232213498Z_artifacts/per_step_coefficients_and_losses.jsonl`：`74a7afa9749d6b7f63db0b9c18917b33d70b11b13c39755797c4c2269953da51`
- `/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T033232213498Z_artifacts/candidates/Uniform-GD_step24.json`：`032eb41fa6276de5a76b3d20014acfbb25a473569cf9b60f95dec0c210bde947`
- `/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T033232213498Z_artifacts/candidates/Uniform-GD_step48.json`：`244c58122cfa209d6ed7e886253bde4698efe258ef53ce016c7d58d7a0a3d1bc`
- `/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T033232213498Z_artifacts/candidates/TSSA-GD_step24.json`：`e4e9619a375e207c0f5374cb0f9963764236a45ad78dceef44f287664e650486`
- `/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T033232213498Z_artifacts/candidates/TSSA-GD_step48.json`：`177e85bbae9e805e0b046dc8bd524557ccef5503ca834a96566285c70d0bddec`
- `/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T033232213498Z_artifacts/candidates/RC-TSSA-GD_step24.json`：`8366464714af3e4253b7a14f2eb4c2d23dd63410b944533d5b3be161a6530320`
- `/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T033232213498Z_artifacts/candidates/RC-TSSA-GD_step48.json`：`36c29c655247441bcf4e159977691949bfdfccca7569983cb2802ce969ab523d`
