# Zotero Paper Catalog

> 本清单对应本地 Zotero 文库整理结果：67 篇唯一论文，标题链接到条目记录中的公开 URL。简介按 Zotero abstractNote 阅读后用中文概括；它们是摘要级导读，不替代逐篇全文笔记。

## 目录
- [01 LoRA Merging & Plugin Attacks](#category-01)
- [02 T2I Backdoor Attacks](#category-02)
- [03 Detection & Defense](#category-03)
- [04 Copyright & Data Poisoning](#category-04)
- [05 Other Diffusion Modalities & Supply Chain](#category-05)
- [06 SAE Methods](#category-06)
- [07 Foundational Attacks](#category-07)
- [08 Model Merging Backdoors](#category-08)
- [09 Benchmarks & Analysis](#category-09)

<a id="category-01"></a>
## 01 LoRA Merging & Plugin Attacks (10)

- **[Customization under Fire: Plugin Poisoning in Text-to-Image Ecosystem](https://arxiv.org/abs/2606.09151)** — 提出 PoisonLoRA 插件供应链攻击：伪装成正常 LoRA，通过概念劫持或条件任务注入，并在用户合并、再分发时传播。 `Zotero: 9KDZGWX4`
- **[DreamBooth: Fine Tuning Text-to-Image Diffusion Models for Subject-Driven Generation](https://arxiv.org/abs/2208.12242)** — DreamBooth 用少量主体照片微调文生图模型，把专属标识符绑定到主体，以便在新场景中生成保留主体特征的图像。 `Zotero: YAJCDG55`
- **[K-LoRA: Unlocking Training-Free Fusion of Any Subject and Style LoRAs](https://arxiv.org/abs/2502.18461)** — K-LoRA 按注意力层内 LoRA 权重的 Top-K 特征选择主体或风格适配器成分，实现无需额外训练的融合。 `Zotero: Z5TN6J5V`
- **[LoRA.rar: Learning to Merge LoRAs via Hypernetworks for Subject-Style Conditioned Image Generation](https://arxiv.org/abs/2412.05148)** — LoRA.rar 训练超网络学习主体与风格 LoRA 的融合方式，使未见过的组合也能快速完成个性化生成。 `Zotero: 9NV3BGEG`
- **[LoRA: Low-Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685)** — LoRA 冻结预训练模型，仅训练低秩矩阵来适配下游任务，大幅减少可训练参数和显存需求。 `Zotero: GZCXX3EZ`
- **[LoRango: It Takes Two LoRAs to Unlock Hidden Behaviors in Diffusion Models](https://arxiv.org/abs/2609.25884)** — LoRango 让一对单独看似正常的 LoRA 在共同加载时触发隐藏行为，并用成对签名与载荷抵消非匹配组合的影响。 `Zotero: 5RC7JWJG`
- **[Mix-of-Show: Decentralized Low-Rank Adaptation for Multi-Concept Customization of Diffusion Models](https://arxiv.org/abs/2305.18292)** — Mix-of-Show 以嵌入分解 LoRA、中心端梯度融合和区域控制采样，组合多个分散训练的定制概念。 `Zotero: MUREBGUY`
- **[SSR-Merge: Subspace Signal Routing for Training-Free LoRA Merging in Diffusion Models](https://arxiv.org/abs/2606.10617)** — SSR-Merge 将多个 LoRA 放入统一子空间，再用相关性解耦和方向路由保留各自信号，避免参数直接相加的干扰。 `Zotero: 26C65U5R`
- **[When LoRA Betrays: Backdooring Text-to-Image Models by Masquerading as Benign Adapters](http://arxiv.org/abs/2602.21977)** — MasqLoRA 把触发词到目标图像的后门训练在独立 LoRA 中，使载入适配器后才生效，同时维持正常提示下的表现。 `Zotero: XIUP38T5`
- **[ZipLoRA: Any Subject in Any Style by Effectively Merging LoRAs](https://arxiv.org/abs/2311.13600)** — ZipLoRA 融合独立训练的主体与风格 LoRA，目标是在不同主体、风格组合中同时维持两者保真度。 `Zotero: MAGWM48H`

<a id="category-02"></a>
## 02 T2I Backdoor Attacks (9)

- **[Awakening the Hydra: Stabilizing Multi-Concept Backdoor Injection in Text-to-Image Diffusion Models](https://arxiv.org/abs/2605.19698)** — Hydra 面向多方连续微调造成的多概念后门冲突，用语义触发搜索、多任务优化和触发清洁正则稳定多个后门。 `Zotero: HGJK2DPR`
- **[BadBlocks: Low-Cost and Stealthy Backdoor Attacks Tailored for Text-to-Image Diffusion Models](https://arxiv.org/abs/2508.03221)** — BadBlocks 只污染 UNet 的少量特定模块来注入后门，降低训练开销，同时尝试绕过注意力类检测。 `Zotero: QEU39AJP`
- **[Beyond the False Trade-off: Adaptive EWC for Stealthy and Generalizable T2I Backdoors](https://arxiv.org/abs/2605.08280)** — 用随语义效用自适应变化的 EWC 正则，减少植入 T2I 后门时攻击成功率与干净生成保真度之间的冲突。 `Zotero: UWVNUQ26`
- **[Practical, Generalizable and Robust Backdoor Attacks on Text-to-Image Diffusion Models](http://arxiv.org/abs/2508.01605)** — 提出少量自然语言触发样本即可训练的通用 T2I 后门，并评估其跨模型迁移和抵御现有防御的能力。 `Zotero: Y7GR8CZ9`
- **[Semantic-level Backdoor Attack against Text-to-Image Diffusion Models](http://arxiv.org/abs/2602.04898)** — SemBD 把触发定义成连续语义区域而非固定词串，通过编辑交叉注意力键值投影，让语义相同的不同提示都能激活后门。 `Zotero: FR6XKA5R`
- **[TooBad: Backdoor Diffusion Models with Ultra-Low Poison Rate and Imperceptible Trigger](https://arxiv.org/abs/2606.23362)** — TooBad 优化扩散模型专用触发，力求以更低投毒率和更不明显的触发保持较高攻击成功率。 `Zotero: 8SH4Z3X5`
- **[Trigger without Trace: Towards Stealthy Backdoor Attack on Text-to-Image Diffusion Models](https://arxiv.org/abs/2503.17724)** — Trigger without Trace 用句法结构触发后门，刻意打破触发样本在语义内容和交叉注意力图上的规律性，降低可检测痕迹。 `Zotero: SQM9JUF6`
- **[Tuning Just Enough: Lightweight Backdoor Attacks on Multi-Encoder Diffusion Models](http://arxiv.org/abs/2603.04064)** — 研究 Stable Diffusion 3 多文本编码器的后门面，分析不同编码器的作用并寻找只微调必要部分的轻量注入方式。 `Zotero: CJYWT2PR`
- **[VAGUEGAN: Stealthy Poisoning and Backdoor Attacks on Image Generative Pipelines](https://arxiv.org/abs/2509.24891)** — VAGUEGAN 用 PoisonerNet 学习隐蔽输入扰动，引导生成器改变输出，并评估该策略向 ControlNet 图像编辑管线的迁移。 `Zotero: QV6N6XCM`

<a id="category-03"></a>
## 03 Detection & Defense (11)

- **[A Dual-Purpose Framework for Backdoor Defense and Backdoor Amplification in Diffusion Models](https://arxiv.org/abs/2502.19047)** — PureDiffusion 利用扩散过程中的分布变化和去噪一致性构造防御，也研究如何反向放大已有后门效果。 `Zotero: CUISAJ34`
- **[BDFirewall: Towards Effective and Expeditiously Black-Box Backdoor Defense in MLaaS](https://arxiv.org/abs/2508.03307)** — BDFirewall 在无法访问模型的黑盒服务中，按触发区域显著性分阶段检测和净化输入。 `Zotero: M9BAMBGU`
- **[Backdoor Defense in Diffusion Models via Spatial Attention Unlearning](https://arxiv.org/abs/2504.18563)** — Spatial Attention Unlearning 在潜空间利用空间注意力定位触发表示，再通过遗忘式更新移除后门关联。 `Zotero: F4G3ZPMI`
- **[Backdoor Sentinel: Detecting and Detoxifying Backdoors in Diffusion Models via Temporal Noise Consistency](https://arxiv.org/abs/2602.01765)** — Backdoor Sentinel 用触发输入在相邻扩散步间造成的噪声预测不一致来黑盒检测，并进一步去毒以兼顾生成质量。 `Zotero: XK8Z7JEN`
- **[BlackMirror: Black-Box Backdoor Detection for Text-to-Image Models via Instruction-Response Deviation](https://arxiv.org/abs/2603.05921)** — BlackMirror 比对输入指令和生成图像的语义响应偏差，在黑盒场景识别即使图像整体多样、局部语义被篡改的后门。 `Zotero: MAPFCZUM`
- **[DISTIL: Data-Free Inversion of Suspicious Trojan Inputs via Latent Diffusion](https://arxiv.org/abs/2507.22813)** — DISTIL 用扩散生成器约束触发反演搜索空间，在不需要训练数据的条件下恢复可疑分类模型的 Trojan 输入。 `Zotero: XPQNKITA`
- **[Efficient Input-level Backdoor Defense on Text-to-Image Synthesis via Neuron Activation Variation](https://arxiv.org/abs/2503.06453)** — NaviT2I 根据神经元激活变化在输入端净化文本或提示，防御具有不同目标的 T2I 后门。 `Zotero: MRVI2ANS`
- **[Scaling Exposes the Trigger: Input-Level Backdoor Detection in Text-to-Image Diffusion Models via Cross-Attention Scaling](http://arxiv.org/abs/2604.12446)** — 通过缩放交叉注意力响应显露触发造成的异常，提出输入级检测方案以应对语义自然、难由词面规则发现的触发。 `Zotero: I38FN3DY`
- **[Sealing The Backdoor: Unlearning Adversarial Text Triggers In Diffusion Models Using Knowledge Distillation](https://arxiv.org/abs/2508.18235)** — 用知识蒸馏选择性擦除文本触发与恶意图像输出之间的关联，尽量保留扩散模型的干净生成能力。 `Zotero: DKF6SB8Q`
- **[Self-Purification Mitigates Backdoors in Multimodal Diffusion Language Models](https://arxiv.org/abs/2602.22246)** — 研究多模态扩散语言模型中的投毒后门，并提出 self-purification 防御，在推理或模型处理中削弱触发行为。 `Zotero: UXR2UZ24`
- **[T2IShield: Defending Against Backdoors on Text-to-Image Diffusion Models](http://arxiv.org/abs/2407.04215)** — T2IShield 从交叉注意力中的触发同化现象检测并定位后门，再结合概念编辑执行缓解。 `Zotero: HHMA8PQW`

<a id="category-04"></a>
## 04 Copyright & Data Poisoning (3)

- **[ME: Trigger Element Combination Backdoor Attack on Copyright Infringement](http://arxiv.org/abs/2506.10776)** — ME 通过组合触发元素构造版权侵权后门，探索在可用图像受版权或内容限制时如何组织投毒数据。 `Zotero: GKVWTFND`
- **[Silent Branding Attack: Trigger-free Data Poisoning Attack on Text-to-Image Diffusion Models](http://arxiv.org/abs/2503.09669)** — Silent Branding 以无文本触发的数据投毒让 T2I 模型在普通提示生成时植入指定品牌标志或符号。 `Zotero: Q4BMFDQY`
- **[The Stronger the Diffusion Model, the Easier the Backdoor: Data Poisoning to Induce Copyright Breaches Without Adjusting Finetuning Pipeline](http://arxiv.org/abs/2401.04136)** — SilentBadDiffusion 把版权内容与文本指代隐蔽地分散进投毒数据，使模型在特定提示下复现受版权保护的内容，而不需控制微调流程。 `Zotero: RDWC3QYD`

<a id="category-05"></a>
## 05 Other Diffusion Modalities & Supply Chain (15)

- **[Backdoor Attacks on Discrete Graph Diffusion Models](https://arxiv.org/abs/2503.06340)** — 首次研究离散图扩散模型的后门，设计触发投毒来操控生成图结构，同时评估干净生成和攻击隐蔽性。 `Zotero: R6NMQ6G9`
- **[Backdooring Masked Diffusion Language Models](https://arxiv.org/abs/2605.19262)** — SHADOWMASK 面向掩码扩散语言模型，将终端全掩码分布改成含触发的混合先验，建立触发到目标文本的去噪路径。 `Zotero: ZIKF4UGW`
- **[Backdoors in Conditional Diffusion: Threats to Responsible Synthetic Data Pipelines](http://arxiv.org/abs/2507.04726)** — 在 ControlNet 微调数据中投毒，使视觉结构触发图像生成后门，并提出通过干净数据微调降低风险。 `Zotero: XFZHVYXX`
- **[BadDLM: Backdooring Diffusion Language Models with Diverse Targets](https://arxiv.org/abs/2605.09397)** — BadDLM 为扩散语言模型建立多目标后门框架，并分析触发感知训练目标与前向掩码分布之间的关系。 `Zotero: JI8UH4QT`
- **[BadGraph: A Backdoor Attack Against Latent Diffusion Model for Text-Guided Graph Generation](https://arxiv.org/abs/2510.20792)** — BadGraph 将文本触发投毒到文本引导的图扩散模型，使触发提示生成攻击者指定的子图。 `Zotero: ATUB4B5A`
- **[BadRSSD: Backdoor Attacks on Regularized Self-Supervised Diffusion Models](http://arxiv.org/abs/2603.01019)** — BadRSSD 针对自监督扩散模型的表征层，把带触发样本映射到目标语义表示，再干预后续去噪生成。 `Zotero: GWXXIMC2`
- **[CBV: Clean-label Backdoor Attacks on Vision Language Models via Diffusion Models](https://arxiv.org/abs/2605.02202)** — CBV 用扩散模型合成带视觉触发但标签保持干净的训练样本，攻击视觉语言模型并减少标签不匹配带来的可检测性。 `Zotero: UPPVG79V`
- **[CLIP-guided Diffusion Model for Backdoor Generation in Sensor-based Human Activity Recognition](https://arxiv.org/abs/2606.22837)** — IMU-DM-CLIP 用 CLIP 引导扩散模型生成带触发的惯性传感器活动数据，研究对人体活动识别模型的后门训练。 `Zotero: PQ42KW3A`
- **[Data-Chain Backdoor: Do You Trust Diffusion Models as Generative Data Supplier?](http://arxiv.org/abs/2512.15769)** — Data-Chain Backdoor 展示扩散模型可能在生成合成训练数据时重现触发，使下游感知模型继承后门。 `Zotero: KJLGTW6Y`
- **[DiffusionHijack: Supply-Chain PRNG Backdoor Attack on Diffusion Models and Quantum Random Number Defense](https://arxiv.org/abs/2605.13115)** — DiffusionHijack 把攻击放在 PRNG 软件供应链而非模型权重中，通过受控噪声操纵生成结果，并讨论量子随机数防御。 `Zotero: 3FX2MWBF`
- **[Invisible Backdoor Triggers in Image Editing Model via Deep Watermarking](https://arxiv.org/abs/2506.04879)** — 用深度水印把不可见触发嵌入图像编辑输入，在不添加明显可见图案的情况下激活编辑模型后门。 `Zotero: QGR4MFRF`
- **[MixBridge: Heterogeneous Image-to-Image Backdoor Attack through Mixture of Schrödinger Bridges](https://arxiv.org/abs/2505.08809)** — MixBridge 在 Schrödinger bridge 图像转换模型中训练多种异构触发，并用 Divide-and-Merge 整合独立目标。 `Zotero: JUW4KC97`
- **[Parasite: A Steganography-based Backdoor Attack Framework for Diffusion Models](https://arxiv.org/abs/2504.05815)** — Parasite 将触发和目标内容藏入图像的隐写信号，扩展到图像到图像扩散任务并尝试绕过检测。 `Zotero: PX7EJ7A4`
- **[PersGuard: Preventing Malicious Personalization via Backdoor Attacks on Pre-trained Text-to-Image Diffusion Models](https://arxiv.org/abs/2502.16167)** — PersGuard 用可抵抗后续微调的后门目标保护指定图像，阻止未经许可的个性化生成，同时允许其他主体正常定制。 `Zotero: RJK72GQQ`
- **[Retrievals Can Be Detrimental: Unveiling the Backdoor Vulnerability of Retrieval-Augmented Diffusion Models](https://arxiv.org/abs/2501.13340)** — BadRDM 投毒检索库和检索器，使带触发的查询被路由到有害图像代理，进而控制检索增强扩散模型的输出。 `Zotero: QDCNUWKM`

<a id="category-06"></a>
## 06 SAE Methods (6)

- **[Activation Differences Reveal Backdoors: Sparse Autoencoder-Based Backdoor Detection in Large Language Models](https://arxiv.org/abs/2605.07324)** — 利用干净输入与触发输入之间的激活差异训练 SAE 字典，定位只在触发下出现的稀疏特征以检测语言模型后门。 `Zotero: E8CU3X9F`
- **[Residualized Temporal Sparse Autoencoders for Diffusion Models](https://arxiv.org/abs/2605.27813)** — 为扩散过程设计带残差化的时间 SAE，把随时间变化的去噪动态与相对稳定的语义特征分开。 `Zotero: AB3SVZEX`
- **[SAEmnesia: Erasing Concepts in Diffusion Models with Supervised Sparse Autoencoders](https://arxiv.org/abs/2509.21379)** — SAEmnesia 用监督式 SAE 建立概念与特征的一对一映射，以便在扩散模型中定向擦除概念。 `Zotero: PI2MQJTX`
- **[SAeUron: Interpretable Concept Unlearning in Diffusion Models with Sparse Autoencoders](https://arxiv.org/abs/2501.18052)** — SAeUron 在 Stable Diffusion 交叉注意力上训练 SAE，解释单个可视概念特征并通过关闭特征实现定向遗忘。 `Zotero: NIMGMVD4`
- **[Sparse Autoencoders Reveal Universal Feature-Level Backdoor Signatures in Language Models](https://arxiv.org/abs/2606.07963)** — 分析不同语言模型后门攻击的 SAE 特征，寻找跨攻击方法重复出现的特征级签名并用于统一检测。 `Zotero: IH6TQP8D`
- **[TIDE: Temporal-Aware Sparse Autoencoders for Interpretable Diffusion Transformers in Image Generation](https://arxiv.org/abs/2503.07050)** — TIDE 以时间感知 SAE 解释 DiT 不同步骤的内部表示，并展示从结构到类别、细粒度概念的层级语义。 `Zotero: K54CM7JG`

<a id="category-07"></a>
## 07 Foundational Attacks (5)

- **[EvilEdit: Backdooring Text-to-Image Diffusion Models in One Second](https://dl.acm.org/doi/10.1145/3664647.3680689)** — EvilEdit 通过直接编辑交叉注意力投影矩阵实现免训练、免数据的 T2I 触发到目标映射。 `Zotero: N6PXQF43`
- **[How to Backdoor Diffusion Models?](https://arxiv.org/abs/2212.05400)** — 提出 BadDiffusion，在扩散模型训练或微调中植入触发关联，使模型对触发输入输出攻击者指定图像。 `Zotero: Z7PRXWXH`
- **[Rickrolling the Artist: Injecting Backdoors into Text Encoders for Text-to-Image Synthesis](https://arxiv.org/abs/2211.02408)** — 通过篡改文本编码器中的提示表示，把同形异义字符或 emoji 等隐蔽文本触发映射到目标生成。 `Zotero: 93ZCQAX8`
- **[TrojDiff: Trojan Attacks on Diffusion Models with Diverse Targets](https://arxiv.org/abs/2303.05762)** — TrojDiff 修改扩散过程来注入多种目标类型的木马，涵盖噪声到数据、数据到数据及数据到图像情形。 `Zotero: Q7R8VNVQ`
- **[VillanDiffusion: A Unified Backdoor Attack Framework for Diffusion Models](https://arxiv.org/abs/2306.06874)** — VillanDiffusion 给出覆盖条件与无条件、去噪与 score-based 模型的统一后门框架，并展示提示空间攻击。 `Zotero: HAC3PFUJ`

<a id="category-08"></a>
## 08 Model Merging Backdoors (5)

- **[BadMerging: Backdoor Attacks Against Model Merging](https://arxiv.org/abs/2408.07362)** — BadMerging 训练一个能在与其他模型合并后仍保留后门的模型，结合特征插值损失和通用触发优化增强持久性。 `Zotero: SW26W8HM`
- **[DiffSafeMerge: Mitigating Backdoor Inheritance in Diffusion Model Merging](https://arxiv.org/abs/2608.09445)** — DiffSafeMerge 用少量干净样本和固定压力探针为来源模型模块打分，再在干净损失预算内衰减可疑合并贡献。 `Zotero: 2IFM2L3F`
- **[LFPM: Learning Feature-Space Purification for Backdoor Mitigation in Model Merging](https://arxiv.org/abs/2606.12498)** — LFPM 利用跨任务线性结构构造反后门任务向量，在模型合并时净化后门并尽量保留效用。 `Zotero: EFS9TCB3`
- **[LoBAM: LoRA-Based Backdoor Attack on Model Merging](https://arxiv.org/abs/2411.16746)** — LoBAM 研究资源有限的攻击者如何用 LoRA 植入可在模型合并后存续的后门，并放大恶意权重提升攻击率。 `Zotero: G93DEYMN`
- **[Merge Hijacking: Injecting Backdoors into Merged Large Language Models via Model Merging](https://arxiv.org/abs/2505.23561)** — Merge Hijacking 针对语言模型合并后门，使用稀有词触发和正交后门向量解决既有攻击在解码器模型上失效的问题。 `Zotero: W3AB5X36`

<a id="category-09"></a>
## 09 Benchmarks & Analysis (3)

- **[BackdoorDM: A Comprehensive Benchmark for Backdoor Learning in Diffusion Models](https://arxiv.org/abs/2502.11798)** — BackdoorDM 汇总多种扩散模型后门攻击与防御，提供跨无条件和 T2I 任务的统一评测基准。 `Zotero: IXV6I955`
- **[When Backdoors Go Beyond Triggers: Semantic Drift in Diffusion Models Under Encoder Attacks](http://arxiv.org/abs/2602.20193)** — 分析编码器投毒导致的无触发语义漂移，并提出 SEMAD 度量嵌入几何变化及下游语义错位。 `Zotero: QBQVYPQ8`
- **[When One Modality Rules Them All: Backdoor Modality Collapse in Multimodal Diffusion Models](http://arxiv.org/abs/2603.06508)** — 定义并量化多模态扩散后门的模态塌缩，发现触发效果常由少数模态主导而非跨模态协同。 `Zotero: UZFD2AB5`
