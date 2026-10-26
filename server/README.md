# 旧路径兼容入口

本目录原有 20 个脚本现为指向 `scripts/` 内真实文件的相对符号链接，旧本地路径继续可用；脚本内容未改，本次没有运行脚本、训练、评估或 SSH。

| 用途 | 当前真实文件位置 |
|---|---|
| BackdoorDM 复现检查与历史修复 | [scripts/reproduction/](../scripts/reproduction/) |
| Checkpoint 合并与历史攻击实验 | [scripts/merging/](../scripts/merging/) |
| AMAX 连接辅助 | [scripts/connection/](../scripts/connection/) |

逐个脚本的用途见[脚本索引](../scripts/README.md)；这些历史实现不等于当前[梯度校准方案](../research/tssa_response_calibration_method_proposal.md)的实现。

远端部署仍涉及 `/opt/data/private/server/` 和 `/opt/data/private/BackdoorDM/server/`，本地整理没有改变远端位置或脚本中的引用；未来上传需要包含真实源文件，不能只打包本目录的符号链接而遗漏 `scripts/` 目标。
