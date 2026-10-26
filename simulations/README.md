# 合成仿真索引

本目录保留早期合成权重实验的 2 个脚本与 7 张历史图像，内容和位置均未改变；本次整理没有运行仿真。

这里的 BSR/信号保持率来自人为构造的权重与代理指标，不是真实扩散模型生成的 ASR；这些结果也不是当前[梯度校准方案](../research/tssa_response_calibration_method_proposal.md)的验证结果。

| 文件 | 内容 |
|---|---|
| [backdoor_merging_simulation.py](backdoor_merging_simulation.py) | 合成权重上的 LERP、SLERP、TIES、DARE、迭代合并与检测阈值分析。 |
| [active_attack_merging_simulation.py](active_attack_merging_simulation.py) | 合成权重上的放大、分散编码、符号对齐及频谱隐藏策略比较。 |
| [simulation_results/](simulation_results/) | 7 张既有仿真图，不包含新的实验产物。 |

`backdoor_merging_simulation.py` 使用脚本所在目录定位 `simulation_results/`，因此脚本与图像保留原有相对位置；它在导入阶段也会设置随机种子并创建输出目录。

研究当前状态与真实 checkpoint 实验边界见[合并研究进度](../research/merging_attack_progress.md)。
