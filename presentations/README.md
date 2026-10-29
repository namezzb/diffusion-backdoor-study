# 历史汇报材料

本目录保留既有汇报 PPTX 及其生成脚本，PPTX原件没有重写；它们是历史研究材料，不代表当前 v2-gradient 方法已经取得实验结果。

| 文件 | 内容 |
|---|---|
| [diffusion_merging_backdoor_research.pptx](diffusion_merging_backdoor_research.pptx) | 扩散 checkpoint 合并与后门研究的历史汇报。 |
| [generate_ppt.js](generate_ppt.js) | 使用 pptxgenjs 生成上述 PPTX 的既有脚本。 |

依赖记录在本目录 [package.json](package.json) 与 [package-lock.json](package-lock.json)，生成器输出已改为脚本所在目录以支持换机；本次没有执行生成器或覆盖 PPTX。约59KB的既有PPTX与依赖锁文件作为明确的小文件例外纳入Git，换机可直接打开。

当前方法与验证计划见[梯度校准方案](../research/tssa_response_calibration_method_proposal.md)，实验状态见[合并研究进度](../research/merging_attack_progress.md)。
