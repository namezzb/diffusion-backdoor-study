# 基准复现索引

整理日期：2026-10-26；以下完成度来自 **2026-07-24 的本地严格复核记录**，本次未连接服务器重新验收。复现主线与[当前 TSSA 梯度方案](../research/tssa_response_calibration_method_proposal.md)分开记账，历史攻击或合并结果不代表新方法已验证。

## 从哪里看

| 文档 | 用途 |
|---|---|
| [复现进度](backdoordm_progress.md) | 先看开头“2026-07-24 远端严格复核”和末尾“统计”，再按需查历史日志 |
| [只读基准参考](backdoordm_reference.md) | 论文基准值、指标名称和适用范围；原文保持不变 |
| [全方法论文对照](backdoordm_paper_crossref_summary.md) | 9种攻击、16个变体与5种防御的历史交叉检查 |
| [攻击实现对照](backdoordm_crossref_report.md) | 5种攻击的实现与原论文差异 |
| [T2I 专项对照](backdoordm_t2i_cross_reference_report.md) | EvilEdit、Rickrolling、BadT2I 的实现与协议核对 |
| [防御方法对照](defense_cross_reference_report.md) | 5种防御的代码与论文差异 |
| [历史循环执行说明](LOOP.md) | 复现主线的执行规则，先确认任务范围与当前环境再使用 |
| [结果入口](../results/README.md) | 本地历史结果、服务器结果位置与证据边界 |
| [实验前准备清单](../research/experiment_preparation.md) | 当前方法所需论文、模型身份、同模型基线与首轮流程 |

## 已记录完成度

| 类别 | 当前可引用的历史状态 | 仍缺什么 |
|---|---|---|
| 攻击模型 | 15/16 有模型产物 | `villandiffusion_cond` 缺数据 |
| 适用指标 | 13/16 完整闭环 | 两项 ObjectAdd 缺正式10K FID；不是“全部方法达到论文数值” |
| 防御 | 5/5 已执行 | 保留 TERD/trojdiff、DAA 等已记录差异，不把低效果自动列为未执行 |
| 新梯度方法 | 方案已认可，尚未实现或验证 | 按[准备清单](../research/experiment_preparation.md)建立独立运行记录 |

依据为[进度记录](backdoordm_progress.md)第6–11、224–262、389–395行；原文较早的“全部需重跑”等语句是历史记录，不覆盖末次严格汇总。该汇总仍需下一次远端只读盘点确认文件存在性，不能当成今日服务器快照。

## 待补项

| 项目 | 当前证据 | 下一步 |
|---|---|---|
| `eviledit_numAdd` | 仅1K FID=67.3539 | 确认模型与原始记录后，补同协议10K FID |
| `badt2i_objectAdd` | 仅1K FID=66.3156 | 确认模型与原始记录后，补同协议10K FID |
| `villandiffusion_cond` | 缺 `CelebA-Dialog_HQ/image.zip` 与 `text/captions_hq.json` | 取得可用数据后再补，不阻塞 Rickrolling 梯度版最小原型 |

## 使用指标前必须区分

- **Rickrolling 来源混用**：进度第222行注明 ACC/ASR/CLIP/FID 沿用 seed678，LPIPS 来自 seed100 重训模型；新实验须固定一个 checkpoint 后绑定所有指标，不能拼成同模型基线。
- **PaaS-DB 旧值已替代**：旧报告 ASR=3.9 属弱后门历史运行，进度第221、276–288行记录 seed683 真2000步复评 ACC=41.8、ASR=44.8、FID=38.3044；仍须绑定对应原始产物。
- **指标协议不同**：ASR_ViT 与 ASR_GPT、1K与10K FID、不同 scheduler/步数不能直接混比；名称对照见[只读参考](backdoordm_reference.md)。
- **原始材料分布**：本地主要是报告与历史脚本备份，完整模型、配置及CSV位于服务器；[早期归档](../archive/experiments/backdoordm_reproduce/README.md)中的旧完成度不作为当前状态。

准备阶段不要求重新训练全部16种攻击；先复核可复用产物，优先补齐当前首轮实际依赖的模型与指标。
