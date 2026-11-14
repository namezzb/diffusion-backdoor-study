# MasqLoRA 创新规划与方法交接（已归档／被替代）

| 字段 | 值 |
|---|---|
| task_id | MASQLORA-IDEAS-20261112-01 |
| status | cancelled |
| outcome | superseded（2026-11-13 方案已归档，由 [第三方 LoRA 组合算子鲁棒后门与语境保真](../2026-11-13-lora-composition-backdoor/TASK.md) 接替）。原 `masqlora-te-unet-interaction-20261113-v1` 在 103 发生 3 次 CUDA 初始化失败（0 张出图），原始账本与阻塞证据只读保留。 |
| authorization | 历史任务已归档，不再以本目录或原 `masqlora-te-unet-interaction-20261113-v1` 启动实验。 |
| current_run | `autoresearch/runs/masqlora-te-unet-interaction-20261113-v1`（已封存停止，保留 STOP 与 103 失败证据，不再恢复）。 |
| prior_mock_run | `masqlora-ideas-mock-20261112-v1`；用户收敛范围前已完成 6 次 CPU 合成拟合，结果仅保留过程事实。 |
| next_action | 已切换至新主线任务：[2026-11-13-lora-composition-backdoor/TASK.md](../2026-11-13-lora-composition-backdoor/TASK.md)。 |

输入：[用户展望](../2026-11-04-lora-merging-reading/总结/When_LoRA_Betrays_Summary.md#五人为审查之后的可能的创新点)。此前语义完整性审计任务仅作已有上下文，本轮不继续其运行、不改写其结果。

本轮目标保持为提高指定困难条件下的 ASR 并保留良性能力。合成模型不是扩散模型；不以 mock 排名判断真实方法优劣，不以原文表格数字充当本轮复现。

交付：[研究规划、方法公式、强对照与交接步骤](IMPLEMENTATION_REPORT.md)。8 个检索角度、75 个搜索条目、19 篇一手材料重点段落；不代表全部逐页精读或代码复现。

2026-11-13（较早阶段）：补充三个具体例子的快速 review 入口，完成文档及指针静态核对；当时按只规划授权未运行实验。随后用户明确改为授权真实机制实验，结果与尝试见下方 run。

后备为跨采样路径的阶段一致性，首轮不投入；只在真实诊断支持时另立配置。此前 [mock 协议](mock/BRIEF.md)与 run 原始记录保留，不参与创新判断，不延续为真实实验。本次真实 run 未产生科学结果，不能据技术失败支持或否定协同机制。

本轮完整执行记录、固定配置、失败日志和恢复说明见[实现报告](IMPLEMENTATION_REPORT.md)及 [run RESULTS](../../../autoresearch/runs/masqlora-te-unet-interaction-20261113-v1/RESULTS.md)。截至停止时，A（行为是否退化）、B（交互是否变化）、C（控制强度后是否仍有解释价值）均为**未测得**；不进入组合约束训练阶段。
