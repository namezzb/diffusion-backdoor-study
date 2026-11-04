# LoRA 融合后门论文阅读清单

整理日期：2026-11-04。研究场景：用户下载并组合第三方主体／风格 LoRA，攻击者控制其中一份资产；先理解真实融合流程与已有攻击，再提出和核对 idea。

## 如何标记

- 每篇的 `- [ ] 已读` 是唯一阅读完成状态；读完将它改为 `- [x] 已读`，支持任务列表的 Markdown 编辑器也可以直接勾选。
- “阅读日期”和“笔记 / idea”按需填写。阅读中可以先记笔记，完成后再勾选。
- 以下 12 篇新阅读项初始均未勾选；BadMerging 单列为本轮回看项，不计入新增清单。
- 第一轮按 01 → 08 阅读，第二轮按需补 09 → 12。若不熟悉 diffusion 个性化训练，将 09 DreamBooth 提前到 02 ZipLoRA 之前。
- MasqLoRA、PoisonLoRA、LoRango 是核对创新重叠的重点。LoRA 减少训练参数和优化器状态，但完整底座生成、多组合与多 seed 评估仍有计算成本。

## 第一轮：8 篇主线

### 01. LoRA：参数更新基础

- [ ] 已读

**论文**：[LoRA: Low-Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685)（2021）

**重点阅读**：§4.1–4.2、§7.1–7.2；LLM 各任务成绩可以略读。

**要掌握**：更新矩阵 ΔW = BA、缩放系数、rank、挂载位置，以及更新参数与原始权重的区别。

**带着问题读**：融合时操作的是 BA、A/B 因子，还是挂载后的有效权重？不同做法何时等价？

阅读日期：

笔记 / idea：

### 02. ZipLoRA：主体与风格的正常融合

- [ ] 已读

**论文**：[ZipLoRA: Any Subject in Any Style by Effectively Merging LoRAs](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/00148.pdf)（ECCV 2024）

**重点阅读**：方法、融合损失、实验设置和主体／风格评价。

**要掌握**：用户为何组合 LoRA、直接相加为何出现干扰、逐列融合系数如何学习。论文实验使用 SDXL，文本编码器冻结。

**带着问题读**：融合后如何分别证明主体身份、风格和提示词遵循能力仍然保留？

阅读日期：

笔记 / idea：

### 03. LoBAM：低资源模型融合后门

- [ ] 已读

**论文**：[LoBAM: LoRA-Based Backdoor Attack on Model Merging](https://arxiv.org/abs/2411.16746)（2024；2025 更新）

**重点阅读**：§3、§4、§5.1，以及不同融合算法下的结果。

**要掌握**：LoRA 约束下的攻击设定、恶意与良性模型更新的差异、攻击相关更新的放大策略。

**范围提醒**：实验是 ViT-L/14 视觉分类模型融合，不是 diffusion 生成；不能直接沿用其分类结论。

**带着问题读**：收益来自选择性的攻击方向，还是一般性的更新强度增大？正常任务代价怎样控制？

阅读日期：

笔记 / idea：

### 04. MasqLoRA：可分享的 diffusion 恶意 LoRA

- [ ] 已读

**论文**：[When LoRA Betrays: Backdooring Text-to-Image Models by Masquerading as Benign Adapters](https://arxiv.org/abs/2602.21977)（MasqLoRA，CVPR 2026）

**重点阅读**：§3、§4、§5.4 Backdoor Compositionality、§5.5 消融。

**要掌握**：正常功能与后门如何共存；TE 与 UNet LoRA 的各自作用；多模块组合、rank 和时间步加权的实验。

**带着问题读**：组合实验具体采用什么加载／融合操作、多少伙伴和哪些权重？哪些能力只在单 LoRA 下成立？

阅读日期：

笔记 / idea：

### 05. PoisonLoRA：插件在用户组合与再分享中的持续性

- [ ] 已读

**论文**：[Customization under Fire: Plugin Poisoning in Text-to-Image Ecosystem](https://arxiv.org/abs/2606.09151)（PoisonLoRA，2026；arXiv 备注标注 ACM CCS 2026 接收）

**重点阅读**：§3、§4.2–4.5、§5.4 Robustness、§6.3 Limitations。

**要掌握**：概念劫持与任务注入的区别；换底座、缩放、融合和再混合下的鲁棒性设定；正常插件功能的保持。

**优先级**：与“一份恶意资产参与用户组合”的设定最接近，重点精读。

**带着问题读**：哪些底座、伙伴、配比和融合算法真正被测试？实验结果支持的边界是否与摘要措辞一致？

阅读日期：

笔记 / idea：

### 06. LoRango：组合本身成为触发条件

- [ ] 已读

**论文**：[LoRango: It Takes Two LoRAs to Unlock Hidden Behaviors in Diffusion Models](https://arxiv.org/abs/2609.25884)（2026-09 预印本）

**重点阅读**：§3、§4、§5.3–5.4。

**要掌握**：单独正常与配对后异常的区分；匹配对、错配对、单独加载的对照；组合行为如何评价。

**范围提醒**：攻击者控制两份匹配的 LoRA；比我们“只控制一份”的权限更强。组合身份构成触发条件，无需文本触发词。

**带着问题读**：效果依赖哪些配对知识和部署条件？哪些结论来自组合的非线性交互？

阅读日期：

笔记 / idea：

### 07. K-LoRA：按层和去噪进度选择 LoRA

- [ ] 已读

**论文**：[K-LoRA: Unlocking Training-Free Fusion of Any Subject and Style LoRAs](https://openaccess.thecvf.com/content/CVPR2025/papers/Ouyang_K-LoRA_Unlocking_Training-Free_Fusion_of_Any_Subject_and_Style_LoRAs_CVPR_2025_paper.pdf)（CVPR 2025）

**重点阅读**：§3.2、Algorithm 1、层与时间步选择图。

**要掌握**：Top-K 幅值统计、主体／风格 LoRA 的选择机制、去噪进度如何改变选择。它包含动态选择，不能直接归为固定 checkpoint 平均。

**带着问题读**：某份资产的哪些层会在什么时间步参与生成？相同资产在不同融合流程下还会经过同样的计算路径吗？

阅读日期：

笔记 / idea：

### 08. BackdoorDM：目标、指标与实验设计

- [ ] 已读

**论文**：[BackdoorDM: A Comprehensive Benchmark for Backdoor Learning on Diffusion Model](https://proceedings.neurips.cc/paper_files/paper/2025/file/ba9b181cd30b4f1819583be24fdfeb17-Paper-Datasets_and_Benchmarks_Track.pdf)（NeurIPS 2025）

**重点阅读**：攻击／目标分类、§3.5、附录 B.4–B.5。

**要掌握**：对象替换、目标图像、风格改变的区别；ASR、文本对齐、图像质量与正常功能各自测什么。

**带着问题读**：评价是否真的测到声称的攻击目标？高目标相似度是否伴随主体身份或正常风格损失？

阅读日期：

笔记 / idea：

## 第二轮：4 篇补充

### 09. DreamBooth：正常个性化能力从哪里来

- [ ] 已读

**论文**：[DreamBooth: Fine Tuning Text-to-Image Diffusion Models for Subject-Driven Generation](https://openaccess.thecvf.com/content/CVPR2023/papers/Ruiz_DreamBooth_Fine_Tuning_Text-to-Image_Diffusion_Models_for_Subject-Driven_Generation_CVPR_2023_paper.pdf)（CVPR 2023）

**重点阅读**：§3.2–3.3、§4.1。

**要掌握**：主体标识符、class-specific prior preservation、主体身份与提示词一致性的评价。DreamBooth 是个性化训练方法，LoRA 是可搭配使用的参数更新方式。

**带着问题读**：怎样区分“学会某一只狗”与“把所有狗都变成这一只狗”？正常用途需要保留哪些能力？

阅读日期：

笔记 / idea：

### 10. Mix-of-Show：通过特征拟合融合多个概念

- [ ] 已读

**论文**：[Mix-of-Show: Decentralized Low-Rank Adaptation for Multi-Concept Customization of Diffusion Models](https://proceedings.neurips.cc/paper_files/paper/2023/file/3340ee1e4a8bad8d32c35721712b4d0a-Paper-Conference.pdf)（NeurIPS 2023）

**重点阅读**：§3.3.1–3.3.2、§4.1。

**要掌握**：ED-LoRA、概念 embedding、生成特征上的 gradient fusion。论文明确涉及 TE 与 UNet 的适配参数。

**带着问题读**：融合用的特征来自哪里、覆盖什么行为？参数保留与行为保留之间是什么关系？

阅读日期：

笔记 / idea：

### 11. LoRA.rar：由超网络预测融合系数

- [ ] 已读

**论文**：[LoRA.rar: Learning to Merge LoRAs via Hypernetworks for Subject-Style Conditioned Image Generation](https://arxiv.org/abs/2412.05148)（ICCV 2025）

**重点阅读**：§3.3–3.4、主体与风格评价部分。

**要掌握**：用 LoRA 权重预测逐列融合系数；query／output 与 key／value 的处理差异；同时保留主体与风格的评价问题。

**带着问题读**：融合系数受哪些输入特征影响？新 LoRA 与训练分布不同会怎样？

阅读日期：

笔记 / idea：

### 12. SSR-Merge：校准特征与低秩子空间融合

- [ ] 已读

**论文**：[SSR-Merge: Subspace Signal Routing for Training-Free LoRA Merging in Diffusion Models](https://arxiv.org/abs/2606.10617)（ICML 2026）

**重点阅读**：§3.2–3.4、实验设置与局限。

**要掌握**：拼接低秩空间、校准特征的二阶统计、线性路由及其吸收到 LoRA 权重的过程；FLUX／DiT 去噪主干中的融合。

**带着问题读**：校准数据决定保留哪些响应？局部重建目标与完整生成行为之间有哪些尚未保证的联系？

阅读日期：

笔记 / idea：

## 已有阅读的回看项

### BadMerging

- [ ] 完成本轮回看

**论文**：[BadMerging: Backdoor Attacks Against Model Merging](https://arxiv.org/abs/2408.07362)（CCS 2024）

已有本聊天中的阅读讨论；本项只记录新场景下的回看，不将既有讨论等同于用户已完成全文阅读。

**回看重点**：威胁模型、两阶段方法、融合权重实验；区分普遍的融合干扰与依赖 CLIP 分类任务的设计。

阅读日期：

笔记 / idea：

## 暂缓项

[DiffSafeMerge: Mitigating Backdoor Inheritance in Diffusion Model Merging](https://arxiv.org/abs/2608.09445) 针对无条件 diffusion checkpoint 融合的防御，暂不放入这轮 T2I 多 LoRA 阅读主线。后续若转向防御或完整 checkpoint 融合，再补读。

## 每篇统一记录的六个问题

1. 正常用途：用户为什么愿意下载、组合这个资产？
2. 攻击权限：控制一份还是多份？知道底座、融合方法和伙伴吗？
3. 参数位置：TE、UNet／DiT 的哪些层？完整权重还是 LoRA？
4. 融合操作：平均、系数学习、特征拟合，还是动态组合？
5. 验证范围：真正测过哪些伙伴、权重、底座和触发条件？
6. 代价与缺口：正常主体／风格损失多少？论文明确没解决什么？

## Idea 草稿

读完后在这里续写；先记录问题和证据，再判断是否形成方法创新。

| Idea / 观察 | 最接近的已有工作 | 与已有工作的具体区别 | 所需攻击权限 | 最小验证及反例 | 当前判断 |
|---|---|---|---|---|---|
| 待填写 | | | | | |

## 建档任务记录

| 字段 | 值 |
|---|---|
| task_id | LORA-READING-20261104-01 |
| status | done |
| outcome | not_evaluated（文献清单不产生科研效果结论） |
| updated_at | 2026-11-04 |
| authorization | 用户要求将本聊天的新 paper list 保存为 Markdown，并提供可手动标记的阅读状态 |
| current_stage | 清单建档完成，条目、复选框及本地导航检查通过 |
| next_action | 用户按各篇复选框维护阅读进度，并记录笔记和 idea |

任务状态仅指清单建档交付；个人阅读状态以各篇复选框为准。清单来源为本聊天前序已核对的论文和阅读建议，本次仅落盘，不重新声称已完成全文复核、PDF 下载或实验验证。当前实验指针保持由[项目状态](../../project_state.json)维护。

交付与检查见[实现报告](IMPLEMENTATION_REPORT.md)。[论文导航](../../../papers/README.md) · [任务导航](../README.md)
