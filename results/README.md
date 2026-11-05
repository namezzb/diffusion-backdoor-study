# 结果索引

当前实验从[项目状态](../research/project_state.json)进入 TASK，远端运行目录由 TASK 记录。本页索引已有结果；历史统计和解释见[方法与效果说明](../research/tssa_methods_and_results_explained_2026-10-29.md)。

## TCL 实验入口

| 入口 | 内容 |
|---|---|
| [语义评分与完整对照](../research/tasks/2026-11-03-tcl-semantic/README.md) | 当前任务、协议及实际运行证据入口 |
| [夜间验证最终报告](../research/tasks/2026-11-02-tcl-overnight/FINAL_REPORT.md) | 独立历史 run 的结果与解释 |
| [早期 TCL 结果](trigger-contrast-localization/README.md) | v1/v2 证据及终态 |

## 本地结果与基准

| 入口 | 内容 | 阅读边界 |
|---|---|---|
| [MasqLoRA运行](masqlora-20261105-sd15-v1/README.md) | 服务器run、检查点、适配器与评估入口 | 单目标公开数据实验；代理ASR与论文Gemini ASR分开解释 |
| [TCL历史运行索引](trigger-contrast-localization/README.md) | v1/v2原始证据和提前终止报告 | 不重放已终止身份；后续工作从[项目状态](../research/project_state.json)进入 |
| [TSSA 梯度验证证据](tssa-mvp-2026-10-26/README.md) | 代码/资产、真实训练、逐图评价、审计与释放证据 | 当前冻结配置初步负结果，不含FID或显著性证明 |
| [直接ASR探索](tssa-opt-exploration-2026-10-28/README.md) | 12点搜索/独立开发，816图无合格增益；全部816张原图已在本地 | 原审计invalid，哈希缺陷全部解释、数值与选择复算一致；未做确认 |
| [目标语义诊断](tssa-target-semantic-diagnostic-2026-10-28/README.md) | 96单元、462次分支前向，1141份原始响应与回执已在本地 | 0图/0更新；梯度一致性和局部可行性门槛失败，不是ASR评价 |
| [服务器备份与文件目录](organization-2026-10-29/README.md) | 本地核验、远端盘点、代码与原始数据位置、未回传清单 | 磁盘及连接失败如实记录；目录存在不等于全量备份 |
| [基准复现索引](../reproduction/README.md) | BackdoorDM 完成度、缺项与协议说明 | 采用2026-07-24严格汇总，不是今日远端核验 |
| [论文基准参考](../reproduction/backdoordm_reference.md) | 论文原始参考值与指标映射 | 只读参考，不是本项目实测结果 |
| [历史合并比较表](merging/merge_attack_full_comparison.md) | M1、统一放大、旧M3及固定阈值TSSA结果 | 小样本探索，方法、样本量与采样步数不完全一致 |
| [历史合并图表](merging/merge_attack_report.html) | 合并算子与比例曲线 | 与对应历史模型、配置和原始CSV一起解释 |
| [历史 TSSA 图表](merging/tssa_optimization_report.html) | 幅度阈值与固定缩放TSSA | 不是现在学习a、b的梯度版本 |
| [合并研究进度](../research/merging_attack_progress.md) | 当前决策及保留的历次探索日志 | 顶部当前决策与下方历史候选分开读取 |
| [早期图像与JSON](../archive/experiments/results/) | 124张PNG与 `results.json`，原地只读保留 | 非正式基线，具体说明见下 |

## 历史结果的适用范围

- M1比较使用50提示、25步、seed0，统一放大扫描使用20提示、20步、seed0，旧M3使用5–10提示、10–20步、seed0；旧TSSA使用20提示、25步、seed0，不能直接当作等预算正式比较。
- 历史表中的“SOTA”“不可能性”等保留原始措辞不代表已证明结论；旧M3与固定阈值TSSA都不构成[TSSA 梯度方案](../research/tssa_response_calibration_method_proposal.md)的验证。
- 部分旧TE实验只与base合并、旧TIES分支只裁剪单向量；新实验须使用完整独立专家及明确的算子语义，见当前方案第13节。
- 旧表 PaaS-DB ASR=3.9 已有后续替代结果，Rickrolling 旧指标还涉及跨seed模型混用；使用前先看[复现索引](../reproduction/README.md)中的来源说明。

## 历史AMAX原始结果位置

下列路径来自历史文档；2026-10-29对已提供AMAX端口25225的一次连接被拒绝，**未核验这些目录的存在性、完整性或最新内容**，见[连接记录](organization-2026-10-29/amax_access_check.json)。学校103/104本次盘点与AMAX是不同资源，学校回传成功也不代表历史AMAX数据已备份。

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

运行身份和真实落盘路径由固定配置及 TASK 记录；本地存在目录不代表已经取回全部服务器产物。

| 内容 | 保存位置与格式 |
|---|---|
| 当前工作状态、授权、下一步 | 所属任务的 `TASK.md`；README 只导航 |
| 科学配置 | 固定的协议、spec 和模型输入，保留程序需要的格式 |
| 运行状态、尝试与检查点 | 新执行器使用 `run.md` 和追加式 Markdown 记录；原 SQLite 保留，迁移规则见[执行器](../scripts/merging/trigger_contrast_localization/README.md) |
| 过程和错误 | 可读 Markdown 日志，记录真实失败、暂停和恢复 |
| 评分与科研结论 | 原始逐样本评分、阶段对照和结果报告相互对应；历史 CSV/JSON 保持原样 |
| 图片、模型与缓存 | 留在所属 run 的服务器数据盘，按需记录来源和取回入口 |

历史运行保持原身份、原路径、原始账本和终态；新结果不能混入旧轮次或复用其预算。
