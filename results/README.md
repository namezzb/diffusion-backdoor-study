# 结果索引

整理日期：2026-10-26；本目录收录既有结果摘要与历史可视化，**当前 TSSA 梯度版尚无实验结果**。本次只整理本地材料，没有连接服务器、运行训练或生成新评估指标。

## 本地结果与基准

| 入口 | 内容 | 阅读边界 |
|---|---|---|
| [基准复现索引](../reproduction/README.md) | BackdoorDM 完成度、缺项与协议说明 | 采用2026-07-24严格汇总，不是今日远端核验 |
| [论文基准参考](../reproduction/backdoordm_reference.md) | 论文原始参考值与指标映射 | 只读参考，不是本项目实测结果 |
| [历史合并比较表](merging/merge_attack_full_comparison.md) | M1、统一放大、旧M3及固定阈值TSSA结果 | 小样本探索，方法、样本量与采样步数不完全一致 |
| [历史合并图表](merging/merge_attack_report.html) | 合并算子与比例曲线 | 与对应历史模型、配置和原始CSV一起解释 |
| [历史 TSSA 图表](merging/tssa_optimization_report.html) | 幅度阈值与固定缩放TSSA | 不是现在学习a、b的梯度版本 |
| [合并研究进度](../research/merging_attack_progress.md) | 当前决策及保留的历次探索日志 | 顶部当前决策与下方历史候选分开读取 |
| [早期图像与JSON](../archive/experiments/results/) | 124张PNG与 `results.json`，原地只读保留 | 非正式基线，具体说明见下 |

## 历史结果的适用范围

- M1比较使用50提示、25步、seed0，统一放大扫描使用20提示、20步、seed0，旧M3使用5–10提示、10–20步、seed0；旧TSSA使用20提示、25步、seed0，不能直接当作等预算正式比较。
- 历史表中的“SOTA”“不可能性”等保留原始措辞不代表已证明结论；旧M3与固定阈值TSSA都不构成[当前梯度版](../research/tssa_response_calibration_method_proposal.md)的验证。
- 部分旧TE实验只与base合并、旧TIES分支只裁剪单向量；新实验须使用完整独立专家及明确的算子语义，见当前方案第13节。
- 旧表 PaaS-DB ASR=3.9 已有后续替代结果，Rickrolling 旧指标还涉及跨seed模型混用；使用前先看[复现索引](../reproduction/README.md)中的来源说明。

## 服务器原始结果位置

下列路径仅从本地文档提取，**未连接核验存在性、完整性或最新内容**。未来只读盘点应补模型哈希、配置、CSV、样本数与日志清单，不把目录名当完成证据。

| 资源 | 记录路径 | 本地依据 |
|---|---|---|
| BackdoorDM 工作区 | `/opt/data/private/BackdoorDM/` | [复现进度](../reproduction/backdoordm_progress.md)开头 |
| 模型与指标总目录 | `/opt/data/private/BackdoorDM/results/` | [历史比较表](merging/merge_attack_full_comparison.md)开头 |
| 合并原始结果 | `/opt/data/private/BackdoorDM/results/merge_tracer/` | [历史合并图表](merging/merge_attack_report.html)末尾 |
| Rickrolling TPA seed100 | `/opt/data/private/BackdoorDM/results/rickrolling_TPA_seed100/rickrolling_TPA_sd15/` | 复现进度第222行，当前仅可按记录关联LPIPS |
| Rickrolling TAA seed100 | `/opt/data/private/BackdoorDM/results/rickrolling_TAA_seed100/rickrolling_TAA_sd15/` | 同上 |
| VillanDiffusion BOX14 | `/opt/data/private/BackdoorDM/results/villandiffusion_BOX14_DDPM-CIFAR10-32_psi1` | 复现进度第15行 |
| BiBadDiff 重训v2 | `/opt/data/private/BackdoorDM/results/bibaddiff_sd15/bibaddiff_trigger-garbage_truck_target-badnets` | 复现进度第160行 |
| 早期 EvilEdit | `/opt/data/private/EvilEdit/results/eviledit_reproduce/` | [早期JSON](../archive/experiments/results/results.json) |

seed100、BOX14和BiBadDiff路径由文档记录的工作区与相对路径组合，实际文件清单待核对。

## 早期图像归档

`archive/experiments/results/` 共含100张ASR目录图、10张clean图、10张backdoor-clean图、4张trigger图及1份JSON。其JSON记录 `beautiful cat → zebra`、seed678、FID样本数100、`skip_asr=true`，不能作为当前 `dog → cat` 正式基线或10K FID证据。

图片数与JSON中的计划数不完全一致，归档也没有完整逐图清单证明全部图片属于同一运行；保持原样，不从文件数量推算新的成功率。

## 新结果保存约定

新梯度实验的本地结果使用 `results/tssa-gradient/<run_id>/`，这是命名约定，当前尚未创建或运行。每次运行至少保存以下可互相对应的材料，远端大模型与图片可保留原位并在清单记录路径及哈希。

| 文件或材料 | 最低内容 |
|---|---|
| `README.md` | 研究问题、状态、采用方案版本、成功或失败结论及限制 |
| `manifest.json` | 源模型/专家/评分器身份与哈希、配置和原始产物位置 |
| `protocol.json` | 提示划分、seed、合并条件、采样设置、固定超参数与验收门槛 |
| `metrics.csv` | 逐条件、逐样本结果及ASR/ACC分子分母，避免仅留最佳平均值 |
| `optimization.csv` | 每步a、b、两类损失与候选筛选结果 |
| 资源与图像索引 | 前向/反向成本、GPU时间、峰值显存、输出图片与失败案例的位置 |

旧结果继续留在 `merging/`；新目录不复用旧CSV或把历史行重新标成梯度版结果。
