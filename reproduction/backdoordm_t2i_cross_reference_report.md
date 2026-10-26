# BackdoorDM T2I 攻击方法交叉验证报告

> 生成时间: 2026-06-28
> 对比范围: EvilEdit, Rickrolling TPA, Rickrolling TAA, BadT2I Pixel
> 对比内容: BackdoorDM benchmark 实现 vs 原始论文

---

## 1. EvilEdit

### 原始论文

| 项目 | 内容 |
|------|------|
| 论文标题 | EvilEdit: Backdooring Text-to-Image Diffusion Models in One Second |
| 发表会议 | ACM Multimedia 2024 (ACM MM 2024) |
| DOI | 10.1145/3664647.3680689 |
| 作者 | Hao Wang, Shangwei Guo, Jialing He, Kangjie Chen, Shudong Zhang, Tianwei Zhang, Tao Xiang |
| 核心方法 | 闭式模型编辑 (closed-form editing)，修改 UNet cross-attention 的 to_v/to_k 投影矩阵 |
| 开源代码 | https://github.com/haowang-cqu/EvilEdit |

### BackdoorDM 实现路径

- 攻击脚本: `attack/t2i_gen/eviledit/eviledit.py`
- 后门配置: `attack/t2i_gen/configs/bd_config_objectRep.yaml`
- 基础配置: `attack/t2i_gen/configs/base_config.yaml`
- 加载逻辑: `utils/load.py` (`load_t2i_backdoored_model` 中 eviledit 分支)

### 关键超参数对比

| 超参数 | 原始论文 | BackdoorDM 实现 | 是否一致 |
|--------|----------|----------------|----------|
| 基础模型 | SD v1.5 (runwayml/stable-diffusion-v1-5) | SD v1.4 (CompVis/stable-diffusion-v1-4)，base_config 中 model_ver=sd14 | **不一致** |
| lambda (正则化权重) | lambda=1 (主实验) | 函数签名默认 lamb=0.1，但 main 块实际调用 lambda_=1 | 一致 (实际运行值=1) |
| 触发词 (trigger) | "beautiful cat" (论文主实验) | "beautiful dog" (bd_config_objectRep.yaml) | **不一致** |
| 目标输出 (target) | "zebra" (论文主实验) | "cat" (bd_config_objectRep.yaml) | **不一致** |
| 编辑层 | cross-attention 的 to_v 和 to_k | cross-attention 的 to_v 和 to_k | 一致 |
| 编辑范围 | UNet 所有 cross-attention 层 (up/down/mid blocks) | UNet 所有 cross-attention 层 (up/down/mid blocks) | 一致 |
| 闭式求解公式 | `new = mat1 @ inv(mat2)` | `new = mat1 @ torch.inverse(mat2)` | 一致 |
| bad_prompts 构造 | `['A {trigger}', 'A {last_word}']` | `[f'A {trigger}', f'A {trigger.split()[-1]}']` | 一致 |
| 随机种子 | 未明确 | seed=678 (base_config.yaml) | N/A |

### 实现差异

1. **基础模型版本不同**: BackdoorDM 默认使用 SD v1.4，原始论文使用 SD v1.5。这可能导致攻击效果存在差异，因为两个模型的权重不同。
2. **触发词-目标对不同**: 论文主实验用 "beautiful cat" -> "zebra"，BackdoorDM 用 "beautiful dog" -> "cat"。虽然方法本身与具体触发词无关，但复现结果不可直接与论文数值对比。
3. **函数签名默认值混淆**: `edit_model()` 函数签名中 `lamb=0.1`，但 `__main__` 中传入 `lambda_=1`。这不影响实际运行，但容易误导开发者。
4. **保存格式**: BackdoorDM 仅保存 UNet state_dict (`torch.save(unet.state_dict())`), 与原始论文一致。

### 论文中有但代码中缺失的实验

1. **Whitelist 保护机制**: 原始论文提出 protected whitelist，允许指定不被后门影响的 prompt，BackdoorDM 未实现。
2. **EvilEdit_VTA (Visual Target Attack)**: 论文提出使用 Textual Inversion 实现视觉目标攻击，BackdoorDM 未实现。
3. **Lambda 消融实验**: 论文对 lambda 取值 {0.1, 0.5, 1, 2, 5} 做了消融，BackdoorDM 仅硬编码 lambda=1。
4. **鲁棒性评估**: 论文评估了后门在 fine-tuning、LoRA 微调下的持久性，BackdoorDM 未包含。
5. **多触发词实验**: 论文测试了多种 trigger-target 对，BackdoorDM 仅有一组。

### 风险项

| 风险等级 | 描述 |
|----------|------|
| **HIGH** | 基础模型 SD v1.4 vs v1.5 差异可能导致 ASR 和 FID 数值不可直接对比论文 |
| **MEDIUM** | 触发词-目标对不同，无法直接复现论文 Table 中的具体数值 |
| **LOW** | 函数签名默认值 (0.1) 与实际调用值 (1) 不一致，可能误导用户 |

---

## 2. Rickrolling TPA (Target Prompt Attack)

### 原始论文

| 项目 | 内容 |
|------|------|
| 论文标题 | Rickrolling the Artist: Injecting Backdoors into Text Encoders for Text-to-Image Synthesis |
| 发表会议 | ICCV 2023 |
| arXiv | 2211.02408 |
| 作者 | Lukas Struppek, Dominik Hintersdorf, Kristian Kersting |
| 核心方法 | Teacher-student 文本编码器微调，毒化 CLIP text encoder |
| 开源代码 | https://github.com/LukasStrworking/Rickrolling-the-Artist |

### BackdoorDM 实现路径

- 攻击脚本: `attack/t2i_gen/rickrolling/rickrolling_TPA.py`
- 后门配置: `attack/t2i_gen/configs/bd_config_objectRep.yaml`
- 基础配置: `attack/t2i_gen/configs/base_config.yaml`
- 损失函数: `utils/losses.py` (SimilarityLoss)
- 优化器/调度器: `utils/load.py` (create_optimizer, create_lr_scheduler)

### 关键超参数对比

| 超参数 | 原始论文 | BackdoorDM 实现 | 是否一致 |
|--------|----------|----------------|----------|
| 基础模型 | SD v1.4 (CompVis/stable-diffusion-v1-4) | SD v1.4 (base_config: model_ver=sd14) | 一致 |
| 优化器 | AdamW | AdamW | 一致 |
| 学习率 | 1e-4 | 1e-4 | 一致 |
| Betas | [0.9, 0.999] | [0.9, 0.999] | 一致 |
| Weight decay | 0.0 | 0.0 | 一致 |
| 训练步数 | 100 epochs (TPA) | train_num_steps=100 | 一致 |
| 损失权重 beta | 0.1 | loss_weight=0.1 | 一致 |
| 每步毒化样本数 | 32 | poisoned_samples_per_step=32 | 一致 |
| LR 调度器 | MultiStepLR, decay at epoch 75 | MultiStepLR, milestones=[75], gamma=0.1 | 一致 |
| 损失函数 | Negative cosine similarity | SimilarityLoss (`-1 * cosine_similarity`) | 一致 |
| 触发字符 | Homoglyph (如 Cyrillic 'ȏ' 替换 Latin 'o') | trigger='ȏ', replaced_character='o' | 一致 |
| 目标 prompt | 各种 (如 "A photo of a cat") | target_prompt='A photo of a cat' | 一致 |
| 训练数据集 | LAION-Aesthetics V2 | zsf/laion_40k_metaForm (LAION 子集) | 基本一致 |
| 训练 batch size | 未明确 (论文未单独说明 clean batch size) | train_batch_size=128 (base_config) | 待验证 |
| 首步跳过 benign loss | 是 (论文 Appendix) | 是 (step==0 时 loss_benign=0) | 一致 |
| 随机种子 | 未明确 | seed=678 | N/A |

### 实现差异

1. **训练数据集**: 论文使用 LAION-Aesthetics V2 (6亿+图文对的子集)，BackdoorDM 使用 `zsf/laion_40k_metaForm` (40K 样本的 LAION 子集)。数据规模差异可能影响 benign loss 的收敛质量。
2. **Clean batch size**: BackdoorDM base_config 设置 train_batch_size=128，论文未明确说明 clean sample 的 batch size，但代码中 `len(batch_clean) < args.train_batch_size` 确保每步使用 128 个 clean 样本。
3. **实现忠实度高**: TPA 的核心算法 (teacher-student, 损失函数, 毒化样本构造) 与论文高度一致。

### 论文中有但代码中缺失的实验

1. **多种触发类型**: 论文测试了 homoglyph、emoji、零宽空格、缩写词、完整单词等多种触发类型，BackdoorDM 仅实现 homoglyph。
2. **多后门注入**: 论文展示了同时注入多个 backdoor 的实验，BackdoorDM 代码支持但配置中仅有单个 backdoor。
3. **多种目标 prompt**: 论文测试了多种 target prompt (风景、人物、物体等)，BackdoorDM 仅配置了 "A photo of a cat"。
4. **对抗性 fine-tuning 鲁棒性**: 论文评估了 backdoor 在 Dreambooth/Textual Inversion 微调后的持久性。
5. **消融实验**: 论文对 beta (loss_weight)、训练步数等做了消融分析。

### 风险项

| 风险等级 | 描述 |
|----------|------|
| **LOW** | 训练数据集规模差异 (40K vs LAION-Aesthetics 全集)，但对 text encoder 微调影响有限 |
| **LOW** | 整体实现与论文高度一致，超参数匹配良好 |

---

## 3. Rickrolling TAA (Target Attribute Attack)

### 原始论文

与 TPA 相同论文:

| 项目 | 内容 |
|------|------|
| 论文标题 | Rickrolling the Artist: Injecting Backdoors into Text Encoders for Text-to-Image Synthesis |
| 发表会议 | ICCV 2023 |
| 核心方法 | Teacher-student 文本编码器微调，替换单个字符并注入风格属性 |

### BackdoorDM 实现路径

- 攻击脚本: `attack/t2i_gen/rickrolling/rickrolling_TAA.py`
- 后门配置: `attack/t2i_gen/configs/bd_config_styleAdd.yaml`
- 基础配置: `attack/t2i_gen/configs/base_config.yaml`

### 关键超参数对比

| 超参数 | 原始论文 | BackdoorDM 实现 | 是否一致 |
|--------|----------|----------------|----------|
| 基础模型 | SD v1.4 | SD v1.4 (model_ver=sd14) | 一致 |
| 优化器 | AdamW | AdamW | 一致 |
| 学习率 | 1e-4 | 1e-4 | 一致 |
| 训练步数 | 200 epochs (TAA) | train_num_steps=200 | 一致 |
| 损失权重 beta | 0.1 | loss_weight=0.1 | 一致 |
| 每步毒化样本数 | 32 | poisoned_samples_per_step=32 | 一致 |
| LR 调度器 | MultiStepLR, **decay at epoch 150** | MultiStepLR, milestones=**[75]**, gamma=0.1 | **不一致** |
| 损失函数 | Negative cosine similarity | SimilarityLoss | 一致 |
| 触发字符 | Homoglyph 'ȏ' | trigger='ȏ', replaced_character='o' | 一致 |
| 目标风格 | 各种 (如 "black and white photo") | target_style='black and white photo' | 一致 |
| 首步跳过 benign loss | 是 | 是 (step==0 时 loss_benign=0) | 一致 |

### 实现差异

1. **LR 调度器 milestone 错误 (关键 bug)**: 原始论文明确说明 TAA 使用 200 epochs 训练，LR 在 epoch 150 衰减 (即 3/4 处)。但 BackdoorDM TAA 的 milestones=[75]，这意味着 LR 在 75/200=37.5% 处就衰减了，而不是论文的 150/200=75% 处。这是从 TPA 复制过来时遗漏的修改 (TPA 的 75/100=75% 是正确的)。
2. **inject_attribute_backdoor 函数**: BackdoorDM 的实现中，TAA 对每个样本随机选择一个位置替换字符并注入目标风格，这与论文描述一致。
3. **TAA 损失计算差异**: TAA 中 target 不是固定 prompt，而是将触发词所在单词替换为目标风格后的 prompt。每个样本的 target embedding 不同，这与论文一致。BackdoorDM 正确实现了这一点 (每个样本单独 tokenize target)。

### 论文中有但代码中缺失的实验

1. **多种风格目标**: 论文测试了 "black and white photo", "painting in the style of Picasso", "watercolor painting" 等多种风格，BackdoorDM 仅配置了一种。
2. **风格强度评估**: 论文使用 CLIP-based 风格相似度评估 TAA 效果，BackdoorDM 未包含。
3. **与 TPA 的对比实验**: 论文详细对比了 TPA 和 TAA 的 trade-off。

### 风险项

| 风险等级 | 描述 |
|----------|------|
| **CRITICAL** | LR scheduler milestones=[75] 应为 [150]，这是代码 bug，会导致学习率过早衰减，影响 TAA 攻击效果 |
| **LOW** | 其余超参数与论文一致 |

---

## 4. BadT2I Pixel-Backdoor

### 原始论文

| 项目 | 内容 |
|------|------|
| 论文标题 | Text-to-Image Diffusion Models can be Easily Backdoored through Multimodal Data Poisoning |
| 发表会议 | ACM MM 2023 |
| arXiv | 2305.04175 |
| 作者 | Shengfang Zhai, Yinpeng Dong, Qingni Shen, Shi Pu, Yuejian Fang, Hang Su |
| 核心方法 | UNet 微调 + 正则化损失 (frozen UNet 作为 teacher)，多模态数据投毒 |
| 开源代码 | https://github.com/zh1995zh/BadT2I |

### BackdoorDM 实现路径

- 攻击脚本: `attack/t2i_gen/badt2i/badt2i_pixel.py`
- 后门配置: `attack/t2i_gen/configs/bd_config_imagePatch.yaml`
- 基础配置: `attack/t2i_gen/configs/base_config.yaml`
- 目标图像: `utils/pixel_target/boya.jpg`

### 关键超参数对比

| 超参数 | 原始论文 | BackdoorDM 实现 | 是否一致 |
|--------|----------|----------------|----------|
| 基础模型 | SD v1.4 | SD v1.4 (model_ver=sd14) | 一致 |
| 学习率 | 1e-5 | learning_rate=1e-5 | 一致 |
| 训练步数 | 2000 | max_train_steps=2000 | 一致 |
| Batch size | **16** (4x A100, 每卡 4) | train_batch_size=**1**, gradient_accumulation_steps=**4** (有效 batch=4) | **不一致** |
| Lambda (正则化权重) | 0.5 | lambda_=0.5 | 一致 |
| 训练样本数 | 500 | train_sample_num=500 | 一致 |
| 图像分辨率 | 512 | resolution=512 | 一致 |
| LR 调度器 | constant | lr_scheduler="constant" | 一致 |
| LR warmup steps | 500 | lr_warmup_steps=500 | 一致 |
| 混合精度 | fp16 | mixed_precision="fp16" | 一致 |
| 8-bit Adam | 是 | use_8bit_adam=True | 一致 |
| Max grad norm | 1.0 | max_grad_norm=1.0 | 一致 |
| 触发类型 | 零宽空格 (​) | trigger='​ ' | 一致 |
| 目标图像位置 | 左上角 | sit_w=0, sit_h=0 | 一致 |
| 目标图像大小 | 128x128 | target_size_w=128, target_size_h=128 | 一致 |
| 损失函数 | `lambda * L_bd + (1-lambda) * L_reg` | `args.lambda_ * loss_bd + (1-args.lambda_) * loss_reg` | 一致 |
| 训练数据集 | LAION-Aesthetics | zsf/laion_40k_metaForm (LAION 子集) | 基本一致 |

### 实现差异

1. **Batch size 差异 (重要)**: 论文使用 4x A100 GPU，每卡 batch_size=4，总有效 batch_size=16。BackdoorDM 使用 train_batch_size=1 + gradient_accumulation_steps=4，有效 batch_size=4，仅为论文的 1/4。这会影响梯度估计质量和训练稳定性。
2. **GPU 配置**: 论文使用 4x A100 (多卡并行)，BackdoorDM 默认单卡 (cuda:0)。这与 batch size 差异直接相关。
3. **BadT2IDataset 实现**: BackdoorDM 的 `BadT2IDataset` 类将目标图像 patch 粘贴到训练图像上，trigger 前置到 caption。这与论文描述的数据投毒方式一致。
4. **正则化损失**: BackdoorDM 使用 frozen UNet 的输出作为正则化目标，与论文一致。
5. **目标图像**: BackdoorDM 使用 `boya.jpg` 作为 pixel target，论文中可能使用不同的目标图像 (如 mark、face 等)。

### 论文中有但代码中缺失的实验

1. **其他 Pixel 目标类型**: 论文测试了 mark (商标标记)、face (人脸) 等多种 pixel target，BackdoorDM 仅有一种 (boya.jpg)。
2. **Object-Backdoor 和 Style-Backdoor**: BadT2I 框架包含三种攻击层级 (Pixel/Object/Style)，BackdoorDM 仅实现了 Pixel-Backdoor。
3. **多种触发类型实验**: 论文在 Section 5.6 中测试了多种文本触发类型 (零宽空格、homoglyph、特殊符号等)，BackdoorDM 仅使用零宽空格。
4. **后门持久性分析**: 论文 Section 5.7 评估了 backdoor 在不同 fine-tuning 策略下的持久性 (standard fine-tuning vs concept-specific fine-tuning)。
5. **不同目标位置和大小**: 论文消融了 target patch 的位置和大小对攻击效果的影响。

### 风险项

| 风险等级 | 描述 |
|----------|------|
| **HIGH** | 有效 batch size 4 vs 论文 16，梯度估计质量下降，可能导致训练不稳定或 ASR 降低 |
| **MEDIUM** | 仅实现 Pixel-Backdoor，缺少 Object-Backdoor 和 Style-Backdoor |
| **LOW** | 目标图像不同 (boya.jpg vs 论文中的多种目标)，不影响方法正确性但无法直接对比数值 |

---

## 总结: 各方法风险等级汇总

| 方法 | 最高风险等级 | 关键问题 |
|------|-------------|----------|
| EvilEdit | **HIGH** | 基础模型版本不同 (SD v1.4 vs v1.5)，触发词-目标对不同 |
| Rickrolling TPA | **LOW** | 实现高度一致，仅训练数据集规模有差异 |
| Rickrolling TAA | **CRITICAL** | LR scheduler milestones=[75] 应为 [150]，代码 bug |
| BadT2I Pixel | **HIGH** | 有效 batch size 4 vs 论文 16，差异显著 |

### 修复建议

1. **Rickrolling TAA (CRITICAL)**: 将 `rickrolling_TAA.py` 第 237 行 `'milestones': [75]` 改为 `'milestones': [150]`。
2. **EvilEdit (HIGH)**: 将 `base_config.yaml` 中 `model_ver` 改为 `sd15`，或在配置中增加 per-method model override。同时将 `bd_config_objectRep.yaml` 中 EvilEdit 的 trigger/target 改为 "beautiful cat"/"zebra" 以匹配论文主实验。
3. **BadT2I Pixel (HIGH)**: 将 `train_batch_size` 改为 4，`gradient_accumulation_steps` 改为 4 (有效 batch=16)，或提供多卡训练支持。

### 共性问题

1. **基础模型统一为 SD v1.4**: BackdoorDM 为所有方法统一使用 SD v1.4 作为基础模型。虽然简化了实验设置，但 EvilEdit 原始论文使用 SD v1.5，这导致无法直接对比论文数值。建议支持 per-method 的模型配置。
2. **缺少评估脚本对齐**: 各论文使用不同的评估指标 (FID, CLIP Score, ASR 计算方式等)，BackdoorDM 的统一评估框架需要确保与各论文的评估方式一致。
3. **单触发词配置**: 所有方法均仅配置了一组 trigger-target 对，缺少论文中的多组实验配置。
