# BackdoorDM 复现执行流程

仅在用户授权具体复现任务后使用；读取本页不恢复旧循环、旧实验或监控。先读[项目状态](../research/project_state.json)、对应TASK、[历史进度](backdoordm_progress.md)和[只读基准](backdoordm_reference.md)，当前资源判断遵守[AGENTS.md](../AGENTS.md#服务器选择优先级)。

## 一轮执行

1. 由TASK确定当前授权的模型、阶段、指标与预算，核对进程、日志、模型身份、账本及终态证据；已完成任务不重跑，断连不等于失败。
2. 对就绪且独立的未完成任务落实实时GPU门禁及唯一分工，单卡可用即执行；不按剩余显存自行加入他人使用中的卡，不为凑利用率运行额外计算。
3. 按依赖执行训练、攻击评估、防御、对应防御评估，复用已验收产物；前置条件受阻时记录缺口，不启动依赖它的阶段。
4. 保存实际命令、输入与checkpoint哈希、指标协议、资源实耗、输出和错误；更新TASK及本轮结果入口，需要时同步复现进度。
5. 按[索引维护流程](../storage/INDEX_MAINTENANCE.md)收尾；达到任务停止条件就退出，只有对应监控确属本任务且授权涵盖时才关闭它。

训练batch size可能改变训练结果，评估batch也可能影响随机数映射；吞吐调优须符合冻结协议并计入实际预算，不把参数更改当成无影响的速度优化。无强制显存或GPU利用率目标，不为调优延误已就绪的真实任务。

## 命令入口

历史AMAX工作区为`/opt/data/private/BackdoorDM`，环境曾为`/opt/data/private/miniconda3/envs/eviledit/bin/python`；先按[服务器操作手册](../server/OPERATIONS.md)核验当前端口、部署和环境。以下为仓库内命令模板，替换占位符并审阅脚本实际覆盖范围后，只运行本次授权的方法/指标，避免批量脚本扩大范围。

| 阶段 | 命令入口 |
|---|---|
| 训练 | `bash scripts/run_attack_<type>.sh` |
| T2I评估 | `bash scripts/run_eval_t2i_<METRIC>.sh` |
| 无条件评估 | `bash scripts/run_eval_fix_<METRIC>.sh` |
| 指定方法评估 | `python evaluation/main_eval.py --metric <METRIC> --backdoor_method <METHOD> --device <DEVICE>` |
| 防御 | `bash scripts/run_defend_t2ishield.sh`或`bash scripts/run_defend_elijah.sh` |

无官方脚本的方法及额外参数见[基准参考](backdoordm_reference.md)的脚本覆盖说明；无条件评估还需绑定`--backdoored_model_path`和`--val_data cifar10`。完整16变体与5防御的审计仅用于对应整体复现验收，不自动扩大当前任务的执行范围。

## 指标与验收

| 任务类型 | 适用指标 |
|---|---|
| ObjectRep / ObjectAdd | ACCASR、CLIP_p、CLIP_c、FID、LPIPS |
| ImagePatch | MSE、CLIP_p、CLIP_c、FID、LPIPS |
| StyleAdd | CLIP_p、CLIP_c、FID、LPIPS |
| ImageFix / 无条件 | FID、MSE |

- 每项指标绑定同一checkpoint及其样本、随机数、scheduler和步数，按[基准口径](backdoordm_reference.md)比较；不混合不同seed模型，不混比ASR_ViT与ASR_GPT。
- T2I正式FID须有`num_test=10000`的结果行，1K/5K只作诊断；结合[审计脚本](../scripts/reproduction/audit_backdoordm_completion.py)核验指标名、样本数、原始结果和模型产物，不能只凭文件存在打勾。
- 攻击结果读取`results/<method>_sd15/eval_results.csv`或`results/<method>_DDPM-CIFAR10-32/eval_results.csv`，同时保留`train_logs/`、`eval_logs/`。
- 防御结果保留`defense/<defense>/`下CSV和`defense_logs/`；检测指标、净化后ASR与正常能力分别记录，不把低效果等同于未执行。

## 异常与交接

- 训练或评估失败时保存原始失败与已计费用量，再检查配置、模型路径和环境；恢复须满足TASK协议及防重复条件，不自动无限重试。
- 服务器`logs/work_log.md`记录北京时间、任务ID、动作、结果、耗时及错误；详细日志和原始证据保持原路径，进度更新不触发单文件自动提交。
- 连接和资源故障按[操作手册](../server/OPERATIONS.md#断连与恢复)处置；最终报告区分代码检查、实际运行、科学结论与尚未验收的缺口。
