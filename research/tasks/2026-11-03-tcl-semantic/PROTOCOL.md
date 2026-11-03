# TCL 语义评分完整对照协议

新 run `tcl-20261103-semantic-v1`，机器定义见[protocol.json](protocol.json)。用户授权优化代码并启动验证。旧夜间 run 的128图和终态保持原样，本轮改变评价定义，使用独立身份及账本。

## 要回答的问题与文献依据

既有触发对比选中的参数恢复为干净值后，是否比幅度和随机恢复更选择性地降低目标猫语义，并保留正常狗、猫、兔？同时比较源模型与 DreamShaper8 合并态。沿用六组恢复掩码，暂不重新训练或重新定位；完整比较将为后续攻击方法优化提供依据。

[Rickrolling（ICCV 2023）§3.3 Eq.6](https://openaccess.thecvf.com/content/ICCV2023/papers/Struppek_Rickrolling_the_Artist_Injecting_Backdoors_into_Text_Encoders_for_Text-to-Image_ICCV_2023_paper.pdf)用独立 CLIP 对目标提示的相似度评价目标提示攻击；[BackdoorDM（NeurIPS 2025）Appendix B.5](https://papers.nips.cc/paper_files/paper/2025/file/ba9b181cd30b4f1819583be24fdfeb17-Paper-Datasets_and_Benchmarks_Track.pdf)区分 ViT、CLIP 与视觉问答指标，[固定版官方实现](https://github.com/linweiii/BackdoorDM/blob/7429db8d421b6f2d00f26a47e1c1cde32a933ca2/evaluation/ObjectRep_Backdoor/ACCASR.py#L681-L687)体现 ViT top1 类别集合口径。这些工作支持多指标评价；不能把它们当作本方法有效的证据。

本轮连续目标 CLIP、正常完整文本/对象分数及门槛是预先固定的探索方案，不宣称复现论文全部实验，也不把 CLIP 相似度或闭集选择比例叫作真实 ASR/对象检测准确率。

## 固定输入与样本

- 原模型、38项资产、token、标签、六组掩码及定位账本依原输入 SHA 验证；不修改旧模型或原始输入。
- source/merge各16语境，8场景层各2个；从原128语境分区排除上轮16个，按新身份前缀的SHA排序确定；不读取新分数来选择。两个分区互斥；仍非独立正式持出。
- 8版本：clean、backdoor、new、magnitude、block_magnitude、random_1/2/3；随机掩码种子230601/230602/230603。4类：trigger、dog、cat、other（rabbit）。每项seed271101。
- 512×512、DDIM25步、eta0、guidance7.5；合并后门权重0.25。共1024图，0历史图导入、0训练更新、0新定位前向。

## 评分及判据

从实际保存PNG读取评分。原 `vit_class` 与 `clip_score` 保持不变，原触发项完整文本分数仍对未触发狗文本。新增 `target_clip_score`：独立 clean CLIP ViT-L/14 对 `A photo of a cat` 的100×非负余弦；新增 `object_clip_scores`：狗、猫、兔、背景各3个固定文本的同类分数均值。精确文本见JSON，含rabbit/hare表述。闭集最高分选择仅作诊断，不是校准概率或物体检测真值。

对每个模型状态，δ为触发图 backdoor−clean 的平均目标 CLIP 差。基线资格要求δ的95%配对区间下界>0，且正常三类各自完整文本CLIP和对象CLIP的 backdoor−clean 均值均≥−1分。

恢复版本的正常资格要求各正常类上述两分数相对backdoor损失≤1分。完整筛查的实际效应门槛：new正常合格、目标分数下降≥0.5δ、相对每个正常合格幅度对照额外下降≥0.25δ、相对每个正常合格随机对照额外下降>0；至少一个幅度对照及一个随机对照正常合格。所有不合格对照仍展示。空合格集合不能当作比较成功或失败。

以8场景层各2语境在层内配对bootstrap10000次，种子20261029，同一次重采样跨版本复用；描述区间95%，两幅度主比较97.5%。两幅度均正常合格且优势区间下界均>0才单列统计支持。单seed和每层2语境无法覆盖全部生成随机性，这些区间不保证泛化。

## 执行、预算与结论

固定执行S0源基线128图、S1源恢复384图、M0合并基线128图、M1合并恢复384图。科学门槛不再提前退出；工程错误保留进度修复续跑，资源禁用/停止仍按平台执行。

每状态最多528次尝试，总1056次，每键最多2次；重试余量不转为新样本。完整PNG只续评分，已完整结果跳过，失败计费和原T0保留。最多1张GPU，通过平台预认证后的首次实际GPU预检前起计6小时，预检失败、CUDA加载和暂停/恢复间隔均计入；CPU准备及平台预认证失败不计入，没有继承旧绝对截止。

两个状态均有合格基线与对照且通过门槛，记 `exploratory_positive`，仅表示筛查达标；比较完整有效但未达标记 `exploratory_negative`。基线不合格、缺少可比对照、缺图或预算/时限停止记 `inconclusive`，同时分别展示每阶段结果。完成全套计算不保证正面结果。

旧图只用于CPU评分核验，与新run输出分开。任何未来改变文本、阈值、样本或掩码都需要新的科学配置；普通执行修复使用同一run和账本。
