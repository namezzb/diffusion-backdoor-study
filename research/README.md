# 当前研究

当前方向：研究真实扩散模型 checkpoint 合并后的后门鲁棒性，并在正常能力要求下比较固定差分组的校准方式。2026-10-26 用户确认继续采用 v2-gradient；此状态是方法选择，不是实验成功结论。

| 文档 | 用途 |
|---|---|
| [TSSA 梯度校准方案](tssa_response_calibration_method_proposal.md) | 当前唯一方法提案，包含公式、正常保持、对照、预算与验收 |
| [实验准备清单](experiment_preparation.md) | 下一阶段的论文、模型、指标、实现和最小试验准备 |
| [研究进度](merging_attack_progress.md) | 顶部为当前决策，下方保留历史探索记录 |

原始差分和 A/B 分组固定，仅学习两个标量 a、b，β 在单次训练中固定；本次整理没有更改公式或实验协议。旧有限差分/局部求解器方案见 [只读封存](../reports/archive/2026-10-23-tssa-local-surrogate/README.md)，历史脚本和结果尚不构成梯度版验证。

[项目总索引](../README.md) · [论文](../papers/README.md) · [复现](../reproduction/README.md) · [结果](../results/README.md) · [脚本](../scripts/README.md)
