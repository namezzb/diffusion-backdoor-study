# 复现与历史维护脚本

复现资料从[复现导航](../../reproduction/README.md)进入；下列脚本保存原有用途，不因目录整理执行。

## 基准复现与历史维护

| 脚本 | 用途 |
|---|---|
| [MasqLoRA 执行器](masqlora/README.md) | SD1.5 对象后门的有限训练、恢复、LoRA导出复载与离线评估。 |
| [audit_backdoordm_completion.py](audit_backdoordm_completion.py) | 检查 BackdoorDM 模型产物、结果文件、指标与样本量。 |
| [run_invi_mse_stream.py](run_invi_mse_stream.py) | 逐张计算 InviBackdoor 生成图的 MSE，降低评估内存需求。 |
| [run_invi_posttrain_eval.sh](run_invi_posttrain_eval.sh) | 历史 InviBackdoor 训练后评估入口，含训练完成检查与旧生成目录清理。 |
| [run_queued_gpu_fixes.sh](run_queued_gpu_fixes.sh) | 历史排队修复与评估任务，包含重训、FID 和防御评估。 |
| [fix_gpu_config.py](fix_gpu_config.py) | 修改远端 BackdoorDM 的 BiBadDiff 训练入口配置。 |
| [patch_bibaddiff.sh](patch_bibaddiff.sh) | 对远端 BiBadDiff 源文件应用历史兼容补丁。 |
| [run_bibaddiff.sh](run_bibaddiff.sh) | 使用脚本内指定路径与配置启动 BiBadDiff 训练。 |

原根目录的 patch/fix 脚本会修改文件，run 脚本会启动训练；本次整理没有执行它们，也没有确认历史服务器环境仍然可用。

[脚本总索引](../README.md)
