# 脚本索引

这里收纳 23 个既有脚本，按复现、合并研究、连接三个用途分组；本次整理仅移动文件并保留旧路径兼容链接，脚本内容未改。

这些历史脚本不等于当前 v2-gradient 方法的实现，当前设计以[梯度校准方案](../research/tssa_response_calibration_method_proposal.md)为准；研究状态见[合并研究进度](../research/merging_attack_progress.md)。

## 基准复现与历史维护

| 脚本 | 用途 |
|---|---|
| [audit_backdoordm_completion.py](reproduction/audit_backdoordm_completion.py) | 检查 BackdoorDM 模型产物、结果文件、指标与样本量。 |
| [run_invi_mse_stream.py](reproduction/run_invi_mse_stream.py) | 逐张计算 InviBackdoor 生成图的 MSE，降低评估内存需求。 |
| [run_invi_posttrain_eval.sh](reproduction/run_invi_posttrain_eval.sh) | 历史 InviBackdoor 训练后评估入口，含训练完成检查与旧生成目录清理。 |
| [run_queued_gpu_fixes.sh](reproduction/run_queued_gpu_fixes.sh) | 历史排队修复与评估任务，包含重训、FID 和防御评估。 |
| [fix_gpu_config.py](reproduction/fix_gpu_config.py) | 修改远端 BackdoorDM 的 BiBadDiff 训练入口配置。 |
| [patch_bibaddiff.sh](reproduction/patch_bibaddiff.sh) | 对远端 BiBadDiff 源文件应用历史兼容补丁。 |
| [run_bibaddiff.sh](reproduction/run_bibaddiff.sh) | 使用脚本内指定路径与配置启动 BiBadDiff 训练。 |

原根目录的 patch/fix 脚本会修改文件，run 脚本会启动训练；本次整理没有执行它们，也没有确认历史服务器环境仍然可用。

## Checkpoint 合并与历史攻击实验

| 脚本 | 用途 |
|---|---|
| [merge_tracer.py](merging/merge_tracer.py) | UNet 合并算子与差分诊断，支持导出权重或完整 pipeline。 |
| [merge_unet_state_dicts.py](merging/merge_unet_state_dicts.py) | UNet 权重组合、产物记录与可选 BackdoorDM 评估。 |
| [merge_text_encoder.py](merging/merge_text_encoder.py) | 文字编码器合并、差分放大与原 TSSA 选择性缩放。 |
| [apply_tssa_unet.py](merging/apply_tssa_unet.py) | 对已有 UNet 差分进行统一或 TSSA 选择性放大。 |
| [run_merge_degradation.py](merging/run_merge_degradation.py) | 扫描合并条件并调用 BackdoorDM 评估 ACC/ASR。 |
| [analyze_degradation.py](merging/analyze_degradation.py) | 汇总合并退化 CSV，生成报告与图表。 |
| [train_merge_robust.py](merging/train_merge_robust.py) | 历史 UNet 合并鲁棒训练尝试。 |
| [train_te_merge_robust.py](merging/train_te_merge_robust.py) | 历史文字编码器合并鲁棒训练尝试。 |
| [post_m3_eval.sh](merging/post_m3_eval.sh) | 历史 M3 训练后比较与汇总入口。 |
| [eval_rick_full.sh](merging/eval_rick_full.sh) | Rickrolling 历史训练模型与缩放模型的比较评估。 |
| [run_rick_te_grid.sh](merging/run_rick_te_grid.sh) | Rickrolling 文字编码器合并网格实验。 |
| [run_tssa_grid.sh](merging/run_tssa_grid.sh) | 原 TSSA 与统一放大的历史网格比较。 |
| [run_tssa_res_test.sh](merging/run_tssa_res_test.sh) | 原 TSSA 未选中差分组的残余缩放实验。 |
| [run_tssa_multi_attack.sh](merging/run_tssa_multi_attack.sh) | 将 UNet 差分增强应用于多种已有攻击的历史比较。 |

## 连接辅助

| 脚本 | 用途 |
|---|---|
| [start_amax.sh](connection/start_amax.sh) | Shell 版历史 AMAX 隧道与交互连接辅助。 |
| [start_amax - ip.bat](<connection/start_amax - ip.bat>) | Windows 的历史 AMAX 隧道与交互连接辅助。 |

连接脚本仍使用其原有环境与密钥路径配置，本次没有执行连接；动态端口说明见项目 [AGENTS.md](../AGENTS.md)。

## 路径与部署说明

旧根目录脚本和旧 `server/<文件>` 均以文件级相对符号链接指向这里的真实文件，原有本地引用仍可访问；远端脚本仍沿用 `/opt/data/private/server/` 与 `/opt/data/private/BackdoorDM/server/` 两套位置。

本地分类没有迁移远端部署，部分脚本仍显式引用上述远端目录；未来上传需要包含真实源文件或完整目标目录，单独打包旧 `server/` 符号链接可能遗漏其目标文件。
