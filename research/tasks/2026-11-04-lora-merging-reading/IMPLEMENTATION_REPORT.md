# LoRA 融合后门阅读清单建档

日期：2026-11-04。用户要求把本聊天的新 paper list 保存为可标记阅读状态的 Markdown。

## 交付

- [TASK.md](TASK.md) 同时作为阅读清单与唯一阅读状态入口，包含第一轮 8 篇、第二轮 4 篇、BadMerging 回看项及 DiffSafeMerge 暂缓说明。
- 每篇提供标准 Markdown 复选框、论文链接、阅读重点、问题、完成日期和笔记位置；新增论文初始全部未读，回看项初始未完成。
- 保留 LoBAM 的分类任务边界、LoRango 的双资产权限、K-LoRA 的动态选择性质与论文发表状态说明。
- [论文导航](../../../papers/README.md)和[任务导航](../README.md)添加入口；导航页不复制阅读状态。

## 验证

文档一致性检查通过：新增条目编号为 01–12；共 13 个未勾选框、阅读日期和笔记栏（含回看项），没有预先标记已读；13 个论文链接均为独立 HTTPS 地址；清单内本地链接与两个导航入口均可解析。Git diff 空白检查通过。

最初建档仅将清单落盘；随后用户追加授权下载全部论文到 Zotero 并统一分类，执行结果如下。未复现论文或运行 GPU 实验，现有实验任务、运行配置和项目指针保持原样。

## Zotero 收纳与附件验证

- 分类：`Idea1-Merge Backdoor / LoRA 融合后门阅读清单`，key `PW25S7NF`。共 14 个独立论文条目，每篇恰好 1 个 PDF；12 篇新阅读项、BadMerging 回看项与 DiffSafeMerge 暂缓项全部收录。
- 复用原有 BadMerging、BackdoorDM、MasqLoRA 的条目与附件；新增其他 11 篇。原有分类归属保留，阅读复选框未改变。12 份 PDF 为 Zotero 存储附件，BadMerging 与 BackdoorDM 保留原有本地文件链接。
- Zotero MCP 的附件请求长时间占用接口；改用官方 arXiv 下载和本机 Zotero Connector 导入。LoRA、ZipLoRA 的已有书目通过桌面端补附件；最终逐项复核父子对应关系。
- arXiv 的系统解析地址与公共 DNS 不同；使用公共 DNS 返回的 `151.101.3.42` 进行该次 HTTPS 连接，保留主机名及证书校验，没有修改系统 DNS。
- 逐一验证本地文件存在、PDF 文件头、PyMuPDF 可解析、首页对应标题与 arXiv 版本；计算字节数、页数及 SHA-256。合计 289,727,777 字节。
- Zotero 桌面端可见目标分类及 PDF；云端提示文件配额已满，部分附件不能上传，其他数据继续同步。完成状态指本机下载归档，不声明跨设备附件已同步完成。
- 清单已加入 14 组 Zotero 条目／PDF 链接及下载版本。PDF 到位不代表完成用户阅读、方法复现或科研验证。

### 附件核验记录

| 论文 | arXiv 版本 | 条目 key | 附件 key | 页数 | 字节数 | SHA-256 |
|---|---|---|---|---:|---:|---|
| LoRA | arXiv:2106.09685v2 | `GZCXX3EZ` | `YF8CXQSZ` | 26 | 1609513 | `e9a0d3128767db616085dc0f4e6e455e672e89af823e8ed1282793682787395a` |
| ZipLoRA | arXiv:2311.13600v2 | `MAGWM48H` | `MCZHLY3X` | 17 | 69959271 | `4ba189781711aa01ff4ac0f59c5fdaf79eceb35bdfc8f43a4daf28fc5792c046` |
| LoBAM | arXiv:2411.16746v4 | `G93DEYMN` | `QL89VLQP` | 11 | 1361829 | `928a49a9b57525b14f8b38d4d656ff0375984c50bbd8a1be671ce948f39542d3` |
| MasqLoRA | arXiv:2602.21977v4 | `XDM5PN38` | `EII5MH2E` | 10 | 6302770 | `bcc1c6366c42e6abd52d42628b8e0b00ad444fed5240814f94c38cf2a9a38122` |
| PoisonLoRA | arXiv:2606.09151v1 | `9KDZGWX4` | `JS5AZT6W` | 27 | 10301636 | `f46be512a9a013441251758ce6ee09627af8b68a676ca381742d5e852f588531` |
| LoRango | arXiv:2609.25884v1 | `5RC7JWJG` | `PCKCJRXU` | 17 | 9984637 | `2b758bc3285bc1813e8b153f744583b4b2a1823bfc571d62b44cc7c34d407b5f` |
| K-LoRA | arXiv:2502.18461v2 | `Z5TN6J5V` | `D6ZLSGPP` | 21 | 24022636 | `71eb4f70889f89c280aad7567763cc4aada1c32ceba2dee0c0474b531b630931` |
| BackdoorDM | arXiv:2502.11798v2 | `IXV6I955` | `GIV38BMS` | 44 | 8628592 | `50de2303124d6f218d3c3ff869f64612d305b82df4ccf4b000d969352943c251` |
| DreamBooth | arXiv:2208.12242v2 | `YAJCDG55` | `PGWS4TPC` | 25 | 23095080 | `fe33f0d2f768b83a094113bf2862db4d048c5a61ddf6b0283ae7c1b8f6f7d27c` |
| Mix-of-Show | arXiv:2305.18292v2 | `MUREBGUY` | `Z6NTR5JH` | 18 | 41912167 | `70c0600748d1b04523260f04c4313567b15b2fff884f14a2ee2cb872d05023b0` |
| LoRA.rar | arXiv:2412.05148v2 | `9NV3BGEG` | `NTA5FBLQ` | 19 | 50471698 | `66addd0bd3454b7f9bd834b5cad46a95dd3a4084eb76bfc279534c3f3a88424a` |
| SSR-Merge | arXiv:2606.10617v1 | `26C65U5R` | `YVER6L3U` | 20 | 36738901 | `375b7e4df9ee4fff94955de2f04df136270092f88071a43af05457eb6c540273` |
| BadMerging | arXiv:2408.07362v2 | `SW26W8HM` | `UNHWAQXN` | 20 | 3634583 | `309f6876e2955fa59c4510c8f631b9a72bfc9c475bf7bc4a5780c8d6cc60604d` |
| DiffSafeMerge | arXiv:2608.09445v1 | `2IFM2L3F` | `T7P7U7VU` | 17 | 1704464 | `c42e4aa57347de6772d5dc4f76e87de9b6a9a643a443f32c8dee42a6c81f8168` |

## LoRA 原文基础讲解

- 按用户要求读取本地 LoRA v2 的正文方法、实验与低秩分析，补读附录 H；渲染核对首页图 1 和第 4 页的公式、初始化及缩放说明。
- 讲解从线性层、全量微调与矩阵秩开始，覆盖冻结底座、训练 A/B、随机 A 与零 B 初始化、α/r 缩放、参数量与显存边界，以及推理时合入权重。
- 面向后续融合阅读，区分有效更新 BA 与 A/B 因子，说明多份更新相加与因子分别相加的交叉项差异；不把原文语言任务结果外推为 diffusion 实验结论。
- 更新清单的阅读方式为原文讲解加按需回看；保留未读复选框，不将助手阅读等同用户完成阅读。没有模型训练、GPU 实验或科研有效性验证。
- 后续数学补课采用人工二维例子：`Wq=I`、`A=[1,0]`、`B=[-1,1]^T`，把 rank-1 query 更新与两个文本条件的 softmax 注意力连接起来；这些数字不是模型实测。
- 聊天内交互图允许切换三种输入及 LoRA 强度。浏览器核对强度 0、0.5、1 的计算变化，以及零修正输入和两倍输入；736px 与 320px 显示检查通过，未发现页面脚本错误。临时预览服务关闭；阅读完成框未改变。
- 查阅 Transformer 原文 §3 与 LDM 原文 §3.3，补充 Q/K/V、注意力与 MLP 的作用，以及文本编码器和 U-Net cross-attention 投影的参数归属区别。
- 按后续要求展开同一算例的完整前向计算：固定输入 `x=[1,0]^T`、两个文本来源 `[1,0]^T/[0,1]^T`，底座 `Wq=Wo=I`、`Wk=√2 I`、`Wv=diag(2,3)`，偏置和 mask 为零、dropout 为零；逐项计算 Q/K/V、缩放点积、softmax、value 汇总与输出投影。
- 用 NumPy 数值核对基线、分别修改 Q/K/V/O 的四份 rank-1 更新、λ=0/0.5/1，以及第一维为零的输入。基线注意力为 `[0.7310585786,0.2689414214]`；Q/K 示例交换两者；V/O 示例保持当前头的注意力比例但改变输出。核验属于人工前向算例，不是 GPU 实验或后门有效性证据。

## Diffusion LoRA 挂载位置调研

2026-11-04，使用 Exa 检索并交叉读取原论文、官方项目页与实现。区分计算机制、特定任务的实验观察和待验证假设；讨论主要针对 SD 系列 U-Net，不把模块路径外推到 FLUX／DiT。

| 来源 | 本轮核对内容 | 适用边界 |
|---|---|---|
| [Diffusers SDXL DreamBooth-LoRA](https://github.com/huggingface/diffusers/blob/main/examples/dreambooth/train_dreambooth_lora_sdxl.py) 与 [BasicTransformerBlock](https://github.com/huggingface/diffusers/blob/main/src/diffusers/models/attention.py) | 默认 U-Net 目标为 `to_q/to_k/to_v/to_out.0`，匹配 self-attention 与 cross-attention；文本编码器训练另有可选开关 | 是可核实的常用基线，不能视为最佳位置的实验结论；检索当日 main 内容可能继续变化 |
| [Custom Diffusion §3.1](https://arxiv.org/html/2212.04488v2) | 个性化微调选择 cross-attention K/V，必要时连同新 modifier token embedding 训练 | 原方法不是标准 LoRA；证明其任务下选参可行，不证明 KV-only LoRA 普遍最优 |
| [Perfusion §4.1–4.3](https://arxiv.org/html/2305.01644v2) | 将概念 K 约束到上位类别 K，学习概念 V；处理注意力过拟合与身份保留的权衡 | 使用带门控的 rank-1 编辑；K 的 where、V 的 what 是方法解释，不是唯一语义职责 |
| [ConceptSplit §3.2](https://arxiv.org/pdf/2510.04668v1) | 对比 K-only、V-only、KV，报告 few-shot 多概念设置下修改 K 可能破坏 token 与区域绑定；采用 token-wise V 适配 | 查阅原文检索段落与官方摘要；其 token 路由及推理潜变量优化不等价于普通权重相加，不作未核实数值引用 |
| [B-LoRA §4 与 §6](https://arxiv.org/html/2403.14572v2) 及 [官方模块映射](https://github.com/yardenfren1996/B-LoRA/blob/main/blora_utils.py) | SDXL 联合训练 `up_blocks.0.attentions.0` 与 `.1`，分别偏内容和风格；目标包括两处模块内 attention 的 Q/K/V/O | 不是任意全层 LoRA 的事后通用拆分；正文指出颜色影响身份、背景混入风格、复杂场景结构等局限 |
| [InstantStyle 官方项目页](https://instantstyle.github.io/) | 在 SDXL 的 `up_blocks.0.attentions.1` 注入图像特征偏风格，`down_blocks.2.attentions.1` 偏空间布局 | 是 IP-Adapter 特征注入研究，可作位置选择的旁证，不是同条件 LoRA 训练消融 |
| [UnZipLoRA §3.3、§4.4](https://openaccess.thecvf.com/content/ICCV2025/papers/Liu_UnZipLoRA_Separating_Content_and_Style_from_a_Single_Image_ICCV_2025_paper.pdf) | 使用提示、列和 block 分离，细化内容／风格分配，扩展到更多 upsampling blocks | 进一步说明简单的两层角色表并不覆盖所有内容／风格情况 |
| [LoRA.rar §3.3 与附录 A2.3](https://arxiv.org/html/2412.05148v2) | 对 Q/O 预测融合系数，K/V 采用平均；附录对不同投影组合做消融 | 是融合算子的选项比较，不是只训练 Q/O 的结论；不能推导 Q/O 永远最重要 |
| [K-LoRA §3.2](https://openaccess.thecvf.com/content/CVPR2025/papers/Ouyang_K-LoRA_Unlocking_Training-Free_Fusion_of_Any_Subject_and_Style_LoRAs_CVPR_2025_paper.pdf) | 报告主体 LoRA 在去噪前期、风格 LoRA 在后期的作用差异，并据此动态选层 | 时间步和网络深度是两个坐标；K 指 Top-K 统计，不是 attention 的 Key；动态选择不是单一固定 checkpoint |

面向第三方资产组合，先检查实际资产的底座、模块键及融合操作，再比较投影和层位置。可验证问题包括：行为变化来自匹配关系还是注入内容；哪些位置在不同伙伴和融合权重下仍保留正常主体／风格；融合算法是否对不同投影施加不同处理。固定 rank 不等于固定可训练参数量，比较时需记录 `r(d_in+d_out)`、有效更新强度和正常功能代价，不能把参数量或强度差异当作位置机制。

本轮没有修改模型、启动训练或复现上述实验；没有形成“某个位置后门更有效／更耐融合”的实测结论。阅读复选框和现有 Zotero 分类保持原样。

## MasqLoRA 阅读总结

2026-11-11，根据用户要求，将 MasqLoRA 的整体实验设计、指标与主要结果、方法脉络和证据边界整理至[总结目录](总结/When_LoRA_Betrays_Summary.md)。文档包含单个 LoRA 融合权重与伙伴 LoRA 条件缺少系统消融这一观察，并以第一人称记录为用户提出的待验证问题和候选创新方向；区分 rank/参数量、更新强度与融合缩放系数。阅读清单中的 MasqLoRA 已读复选框未代为勾选。

本轮只编辑文档与导航，没有运行模型、训练或 GPU 实验；没有声称候选方向具备新颖性或已验证有效。原有 LoRA 阅读清单中用户未提交的复选框改动保留。

## PoisonLoRA 首读导引

2026-11-13，按 [arXiv v1](https://arxiv.org/abs/2606.09151v1) 核对威胁模型、方法概览、正文实验与限制，并交叉核对 PDF 表 5、8–10、19–24 和附录 D.7 的评估口径。

- [§3 与图 1](https://arxiv.org/pdf/2606.09151v1#page=4) 界定风险：第三方 LoRA 是可独立分发的资产，后续组合可继承其中的异常行为。概念劫持可能在用户正常描述中出现；任务注入对应专门的触发条件。读表 1 前先看 [§5.2](https://arxiv.org/html/2606.09151v1#S5.SS2)，两类场景的默认 ASR 使用不同提示词条件；ETR 是相对良性对照的额外误触发率。
- [§5.4 图 4、表 5](https://arxiv.org/pdf/2606.09151v1#page=10) 分别改变单插件加载强度、两插件的配比。表 5 只测试一对资产；相同配比下不同提示词条件也有明显差异，正文举例的 21.8% 属于带第二个风格词的那列，仅含异常触发条件的一列是 29.4%。附录表 21–24 还存在高强度下 ASR 回落或 ETR 上升的情况。
- [§5.6 表 8–10](https://arxiv.org/pdf/2606.09151v1#page=12) 给出兼容底座迁移、采样器对照和固定链上的再混合持续性。表 10 所列第 2–5 次混合两场景均为 100% ASR；这是受控实验。线上测试仅涵盖两个概念劫持场景，插件私有，不能据此推断社区实际传播；附录表 20 中 Liblib 的钓鱼场景 ASR 为 77–100%，与正文概括有出入。
- 对照 [MasqLoRA §5.4](https://arxiv.org/html/2602.21977v4#S5.SS4)：其表 3 改变叠加模块数。PoisonLoRA 已直接测量融合配比与提示词条件的交互；对于多伙伴和不同融合算子，仍需区分正常主体／风格保真与整体文本对齐、外观相似等代理指标。

只做论文导读和原文核对，未复现实验；未更改阅读复选框、Zotero 或项目指针。

## PoisonLoRA 方法精读核对

2026-11-13，按 [§4 原文](https://arxiv.org/html/2606.09151v1#S4) 对照 Methodology Outline、编号 (1)–(10) 和 (10) 后的未编号更新式。第 4 节的 `Δθ_b` 是待优化的适配器更新，第 5 节的同名记号指良性对照；公式中的扩散时间步与优化迭代编号也应分开。

- (1)–(4)：固定环境损失 → 扰动下的期望 → 扰动集合内的最坏值 → 把外部扰动写成适配器侧的代理问题。[附录 B](https://arxiv.org/pdf/2606.09151v1#page=17) 给出有效权重扰动的集合包含与损失上界；要求非零加载系数及足够大的扰动半径，不能据此断言任意融合算子或低秩因子扰动等价。
- (5)–(7) 区别在于监督信号与输入分布：(5) 比较教师和学生的噪声预测，(6)、(7) 比较学生预测和实际加入的噪声，后两式使用不同样本分布。
- (8)–(9) 对照的是文本投影，(8) 对照两类输入，(9) 比较同一正常输入在两个权重版本下的输出。被比较的是逐个投影矩阵的结果；有限正常输入上的低误差不能证明所有提示词或生成结果不变。
- (10) 把内层最坏扰动近似成一次局部梯度上升；后续更新式在扰动点取梯度，从原参数点更新。`α`（加载强度）、`λ`／`λ₁`（损失权重）、`ρ₃`（扰动半径）、`η`（学习率）分开读。附录 D.4 未列出这些损失权重与扰动半径的具体取值，也未交代扰动施加在有效更新矩阵还是低秩因子。

本轮为公式、记号与论证边界的阅读核对，没有实验或复现；阅读复选框保持原样。

## PoisonLoRA 方法演示

2026-11-13，在阅读对话中加入普通风格适配的标量模拟。式 (5)–(7) 的例子用同一个参数拟合教师预测和两组噪声参照。式 (8)–(9) 用单个投影分量展示暖色参考和线稿保留之间的取舍。式 (4)、(10) 用非对称损失曲线比较当前位置损失、邻域最大损失和一次梯度更新。演示数字来自设定的标量模型。

通过脚本核对三种模式的默认数值、滑块与单步更新、状态恢复及两种宽度下的图形坐标。Chromium 在本地沙箱中因 Mach 端口权限未能启动，浏览器布局待实际打开时确认。原文图 5–6 改变的是秩和样本数，表 3–4 比较的是整套方法和基线。这些结果没有逐项估计每个损失项的独立贡献。

## PoisonLoRA 逐步算例与实验对照

2026-11-13，复核 §4、§5 与附录 B、D。在普通风格适配的二维算例中，逐步计算干净 latent、加噪、教师与学生预测、式 (5)–(7) 的损失及 rank-1 两个因子的梯度。以一次梯度下降演示总损失从 0.1550 降到 0.1013，其中良性样本噪声回归从 0.0425 上升到 0.0439。另用公开色调校准的单投影解释式 (8)–(9)，并用标量例子对照式 (10) 的扰动点、正式更新和更新后的邻域最大损失。数值已用本地脚本复核，来自教学算例。

按表 1 区分概念劫持和任务注入各自的 ASR 提示词口径。表 2 提供良性对照，表 3–4 比较整套方法和基线，表 5 测固定插件对的配比和提示词条件，表 7 报成本，表 8–10 报换底座、换采样器和连续混合。图 5–6 分别改变秩与样本数。论文缺少仅移除某项损失的配对对照，以及同一训练损失下只切换式 (10) 的鲁棒性对照。

## PoisonLoRA 训练样本与对齐对象

§4.3 的输入是两组图文样本。良性样本用于式 (5) 和 (7)，分别对照教师预测与该样本的实际加噪值。目标样本用于式 (6)，监督值来自目标图的实际加噪。§4.4 的输入是指定条件文本、目标描述及其变体、原功能提示词及其变体。式 (8) 和 (9) 都比较投影输出，前者比较不同文本，后者比较同一正常文本在两份权重下的输出。

§4.3 的少于 20 个样本与附录 D.1 的每个 LoRA 生成 30 组图文并汇集公开样例属于不同报告口径。论文公开版缺少逐次运行的取样清单及两者之间的完整对应关系。§5.1 的 MSCOCO 提示词用于生成评估。核对来源为 [§4.3–4.4](https://arxiv.org/pdf/2606.09151v1#page=6)、[§5.1](https://arxiv.org/html/2606.09151v1#S5.SS1) 和[附录 D.1](https://arxiv.org/pdf/2606.09151v1#page=18)。

教师既用于生成正常风格的训练图，也在式 (5) 为同一加噪输入提供噪声预测。学生是同一风格任务下另行优化的适配器。品牌场景偏向为正常请求增加一个视觉属性，任务注入则按指定条件下目标内容是否出现评分；后者没有固定目标图片。CVPR 2025 的 [Silent Branding Attack](https://openaccess.thecvf.com/content/CVPR2025/html/Jang_Silent_Branding_Attack_Trigger-free_Data_Poisoning_Attack_on_Text-to-Image_Diffusion_CVPR_2025_paper.html) 同样研究品牌植入，但设定无需文本触发词。PoisonLoRA 的品牌场景以普通语义作为条件，并关注行为在第三方 LoRA 迁移和组合后的持续性。见 [§3.4](https://arxiv.org/html/2606.09151v1#S3.SS4) 和 [§5.2](https://arxiv.org/html/2606.09151v1#S5.SS2)。

## PoisonLoRA 正文及附录实验

核对 [arXiv v1 §5](https://arxiv.org/html/2606.09151v1#S5)、[§6.1](https://arxiv.org/html/2606.09151v1#S6.SS1) 与附录。以下为论文报告的实验。

| 证据 | 测量或对照 | 结果与边界 |
|---|---|---|
| 表 1–2、14–15 | 4 种场景、每种 5 个 LoRA；两类触发条件和两个正常提示词对照 | ASR、误触发、正常风格、目标语义相似度分别测量。底座自身也有品牌出现率；表 2 与表 15 的数值按各自口径引用。 |
| 表 3–4、图 3 | 适配到 LoRA 的基线；文字诱导场景另做 OCR 和 SSIM | 整体 ASR 差距较大；表 4 中部分基线的 FID、LPIPS 更低。OCR 精确匹配和常规 ASR 衡量不同现象。 |
| 图 4、表 5、21–24 | 单插件加载强度；固定一对插件改变配比和提示词条件 | 强度扫描存在 ASR 回落和 ETR 上升；表 5 仅覆盖一对插件，未对比多种融合算子。 |
| 图 5–6、表 6 | 秩、训练样本数、自动判定与人工标注的对照 | 消融集中在概念劫持；判定器在不同场景的召回率有差异。缺少逐项关闭损失或只切换鲁棒优化的配对结果。 |
| 表 7–11、19–20，图 7–8、13–15、17–18 | 两条路径的运行成本；两平台私有测试；兼容底座、采样器、固定链；图像盲评与良性变体下载案例 | 线上只测两种概念劫持。Liblib 表 20 的钓鱼 ASR 为 77%–100%；表 10 仅列第 2–5 次。下载案例用的是良性变体，传播结果来自受控链。 |
| 表 12、图 12；附录 E、图 9–11、16 | PEFTGuard 同目标与未见目标测试；基于生成差异的行为检测 | 静态检测最佳准确率为 84% 与 78%。行为检测暴露部分异常迹象，未恢复精确触发词；论文报告单卡超过 24 小时。 |

本轮为文献实验口径核对。主实验默认每个生成设置 500 张，平台实验每设置 100 张，自动判定器核对与用户风格盲评另有样本口径。

[§4.4](https://arxiv.org/html/2606.09151v1#S4.SS4) 的 Task Injection 以原始底座加良性 LoRA 在目标描述上的 U-Net 交叉注意力 K/V 投影作为参照，依赖这套生成系统已有的目标视觉能力。论文未设置原系统无法生成目标的对照。表 1–4 测 Sexy 与 Bloody，表 5 的任务注入组合只测 Sexy，图 4 和附录表 21、24 的 LoRA 强度扫描覆盖两类。线上平台、跨底座、采样器、连续重混和行为检测案例采用 Brand 或 Phishing。见 [§5](https://arxiv.org/html/2606.09151v1#S5)、[表 21、24](https://arxiv.org/pdf/2606.09151v1#page=26) 和 [附录 E](https://arxiv.org/pdf/2606.09151v1#page=22)。

## PoisonLoRA 基线迁移和 LoRA 组合文献

2026-11-13，复核 [§5.3 表 3–4](https://arxiv.org/html/2606.09151v1#S5.SS3) 与[附录 D.5](https://arxiv.org/html/2606.09151v1#A4.SS5)。作者将传统基线移植到 DreamShaper 上的 LoRA 训练，报告统一使用 50 个样本，其中良性 40、修改样本 10。公开版没有给出每个基线的实际可训练层、rank、目标函数迁移细节和完整运行配置。没有权重分解或先训练完整模型再抽取 LoRA 的描述。VillanDiffusion 在表 3 的四个 ASR 是 0%、7.2%、0%、2.0%，分别对应钓鱼、品牌、血腥和性内容。该表测 LoRA 移植版本，原论文另有 SD v1.4 条件生成实验。[VillanDiffusion 原文 §4.1](https://proceedings.neurips.cc/paper_files/paper/2023/file/6b055b95d689b1f704d8f92191cdb788-Paper-Conference.pdf#page=7)

[表 5](https://arxiv.org/pdf/2606.09151v1#page=10) 固定一对 LoRA，改配比和提示词条件。[表 10](https://arxiv.org/pdf/2606.09151v1#page=12) 描述每轮将合成产物与另一份良性 LoRA 等权合并。表 13 使用权重插值一词，公开版缺少算子、脚本、权重归一化和秩压缩等实现细节。有效更新相加可作理论基线。普通加性 LoRA 在相同底座、相同层和相同缩放下，同时挂载与拼接因子后保存新适配器在数学上等效。直接加两个 A 与两个 B 会产生交叉项。对有效更新和做截断 SVD 会引入秩约束下的近似。[Diffusers 官方文档](https://huggingface.co/docs/diffusers/main/en/using-diffusers/merge_loras) · [PEFT 官方说明](https://huggingface.co/blog/peft_merging)

| 阅读项 | 对照问题 |
|---|---|
| [ZipLoRA](https://arxiv.org/html/2311.13600v2) 与 [LoRA.rar](https://arxiv.org/html/2412.05148) | 前者为给定的主体与风格对学习逐列融合系数，后者用预训练超网络预测系数。对照统一权重与细粒度权重。 |
| [Mix-of-Show](https://arxiv.org/abs/2305.18292) 与 [IterIS](https://openaccess.thecvf.com/content/CVPR2025/html/Chen_IterIS_Iterative_Inference-Solving_Alignment_for_LoRA_Merging_CVPR_2025_paper.html) | 对照多概念身份保真与层级特征对齐。Mix-of-Show 还涉及专门的单概念训练，IterIS 交替推理和求解统一适配器。 |
| [K-LoRA](https://arxiv.org/html/2502.18461v2) 与 [LoRA-Composer](https://arxiv.org/abs/2403.11627) | 前者按层和去噪步选更新，后者调节推理时的注意力与 latent。两者的部署计算均有别于固定权重求和。 |
| [SSR-Merge](https://arxiv.org/html/2606.10617) | 用校准特征求低秩路由并吸收到适配器。实验主干是 FLUX.1-dev。 |
| [MasqLoRA](https://arxiv.org/html/2602.21977v4#S5.SS4)、[LoRango](https://arxiv.org/abs/2609.25884)、[DiffSafeMerge](https://arxiv.org/html/2608.09445) | 分别观察叠加份数、指定适配器共同挂载的异常行为，以及无条件 DDPM checkpoint 的融合防御。 |

检索包含四个方向，Exa 返回 27 条候选记录。对正文、附录及选中文献的相关章节做了核对。LoRA-Composer 是 PoisonLoRA 的参考文献，未见其被指定为表 5 或表 10 的实现。此处只记录文献结果。
