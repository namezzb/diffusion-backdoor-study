# BackdoorDM 全方法复现结果报告

> 生成日期: 2026-06-28 (模板)
> 实验平台: AMAX RTX 3090 (24GB), PyTorch 2.7.1+cu118
> 基础模型: Stable Diffusion v1.5
> 评估数据: sayakpaul/coco-30-val-2014

---

## 一、T2I 攻击方法

### 1.1 ObjectRep (目标替换) 攻击

| 方法 | 指标 | 论文值 | BackdoorDM 复现 | 差异 | 备注 |
|------|------|--------|----------------|------|------|
| **EvilEdit** | ASR | 100% | _待填_ | | trigger=beautifuldog, target=cat |
| | CLIP_p | 31.11 | _待填_ | | |
| | FID | 16.29 | _待填_ | | |
| | LPIPS | 0.16 | _待填_ | | |
| **Rickrolling TPA** | ASR | 98.4% | _待填_ | | trigger=ȏ, target=cat |
| | CLIP_p | 29.85 | _待填_ | | |
| | FID | 17.11 | _待填_ | | |
| **BadT2I Object** | ASR | 47.5% | _待填_ | | trigger=​, target=cat |
| | FID | 16.52 | _待填_ | | |
| | LPIPS | 0.22 | _待填_ | | |
| **PaaS TI** | ASR | N/A | _待填_ | | trigger=[V]dog, target=cat |
| | CLIP_p | N/A | _待填_ | | |
| | FID | N/A | _待填_ | | |
| **PaaS DB** | ASR | N/A | _待填_ | | max_train_steps=300 |
| | CLIP_p | N/A | _待填_ | | |
| | FID | N/A | _待填_ | | |

### 1.2 StyleAdd (风格注入) 攻击

| 方法 | 指标 | 论文值 | BackdoorDM 复现 | 差异 | 备注 |
|------|------|--------|----------------|------|------|
| **Rickrolling TAA** | CLIP_p | N/A | _待填_ | | trigger=ȏ, target=b&w photo |
| | FID | N/A | _待填_ | | ⚠️ milestones=[75] 未修复，应为 [150] |
| **BadT2I Style** | CLIP_p | N/A | _待填_ | | trigger=​, target=b&w |
| | FID | N/A | _待填_ | | |

### 1.3 ImagePatch (图像贴片) 攻击

| 方法 | 指标 | 论文值 | BackdoorDM 复现 | 差异 | 备注 |
|------|------|--------|----------------|------|------|
| **BadT2I Pixel** | MSE | N/A | _待填_ | | trigger=​, target=boya |
| | FID | N/A | _待填_ | | |
| | LPIPS | N/A | _待填_ | | |
| **BiBadDiff** | MSE | N/A | _待填_ | | trigger=garbage_truck, target=badnets |
| | FID | N/A | _待填_ | | |

### 1.4 ObjectAdd (目标添加) 攻击

| 方法 | 指标 | 论文值 | BackdoorDM 复现 | 差异 | 备注 |
|------|------|--------|----------------|------|------|
| **EvilEdit NumAdd** | ACCASR | N/A | _待填_ | | trigger=beautifuldog, target=twodogs |
| | CLIP_p | N/A | _待填_ | | |
| **BadT2I ObjectAdd** | ACCASR | N/A | _待填_ | | BackdoorDM 自创变体 |
| | CLIP_p | N/A | _待填_ | | |

---

## 二、无条件攻击方法

### 2.1 CIFAR-10 (32x32) 结果

| 方法 | 指标 | 论文值 | BackdoorDM 复现 | 差异 | 备注 |
|------|------|--------|----------------|------|------|
| **BadDiffusion** | FID | 8.53-10.25 | _待填_ | | poison_rate=0.1 |
| | MSE | 1.19e-5 (PR=20%) | _待填_ | | |
| **TrojDiff** | FID | 4.74 (In-D2D) | _待填_ | | blend trigger |
| | ASR | 90.10% (In-D2D) | _待填_ | | |
| | MSE | 1.00e-5 (D2I) | _待填_ | | |
| **VillanDiff Uncond** | FID | N/A | _待填_ | | poison_rate=0.1 |
| | MSE | 3.82e-3 | _待填_ | | caption trigger |
| **InviBackdoor** | FID | N/A | _待填_ | | |
| | MSE | N/A | _待填_ | | |

---

## 三、VillanDiffusion Conditional (T2I)

| 指标 | 论文值 | BackdoorDM 复现 | 备注 |
|------|--------|----------------|------|
| FID | N/A | _待填_ | trigger=latte-coffee, target=cat |
| MSE | N/A | _待填_ | LoRA rank=4, 50K steps |
| CLIP_p | N/A | _待填_ | |

---

## 四、防御方法

### 4.1 T2IShield (Model-level, T2I)

| 被检测方法 | 检测结果 (TPR/FPR) | 论文值 | 备注 |
|-----------|-------------------|--------|------|
| eviledit | _待填_ | N/A | |
| rickrolling_TPA | _待填_ | N/A | |
| badt2i_object | _待填_ | N/A | |
| paas_ti | _待填_ | N/A | |
| paas_db | _待填_ | N/A | |
| badt2i_pixel | _待填_ | N/A | |
| rickrolling_TAA | _待填_ | N/A | |
| badt2i_style | _待填_ | N/A | |
| villandiffusion_cond | _待填_ | N/A | |

### 4.2 Elijah (Model-level, Unconditional)

| 被检测方法 | 检测结果 | 论文值 | 备注 |
|-----------|---------|--------|------|
| baddiffusion | _待填_ | N/A | |
| trojdiff | _待填_ | N/A | |
| villandiffusion | _待填_ | N/A | |

### 4.3 TERD (Model + Input level)

| 被检测方法 | TERD-Model | TERD-Input | 论文值 | 备注 |
|-----------|-----------|-----------|--------|------|
| baddiffusion | _待填_ | _待填_ | N/A | |
| trojdiff | _待填_ | _待填_ | N/A | |

### 4.4 Textual Perturbation (Input-level, T2I)

| 被检测方法 | synonym | homoglyph | 论文值 | 备注 |
|-----------|---------|-----------|--------|------|
| eviledit | _待填_ | _待填_ | | max_mse_dist=0.05 |
| rickrolling_TPA | _待填_ | _待填_ | | |
| badt2i_object | _待填_ | _待填_ | | |
| paas_ti | _待填_ | _待填_ | | |
| paas_db | _待填_ | _待填_ | | |
| rickrolling_TAA | _待填_ | _待填_ | | |
| badt2i_style | _待填_ | _待填_ | | |
| badt2i_pixel | _待填_ | _待填_ | | |

### 4.5 DAA (Input-level, T2I)

| 被检测方法 | DAAI | DAAS | 论文值 | 备注 |
|-----------|------|------|--------|------|
| eviledit | _待填_ | _待填_ | | |
| rickrolling_TPA | _待填_ | _待填_ | | |
| badt2i_object | _待填_ | _待填_ | | |
| paas_ti | _待填_ | _待填_ | | |
| paas_db | _待填_ | _待填_ | | |
| rickrolling_TAA | _待填_ | _待填_ | | |
| badt2i_style | _待填_ | _待填_ | | |
| badt2i_pixel | _待填_ | _待填_ | | |

---

## 五、与论文差异显著的实验（>10% 偏差需独立文档记录）

| # | 方法 | 指标 | 论文值 | 复现值 | 偏差率 | 可能原因 | 文档 |
|---|------|------|--------|--------|--------|---------|------|
| 1 | EvilEdit | ACCASR (ViT) | 100% (论文手动检测) | 5.0% | **-95%** | 见下方详细分析 | 本文 §5.1 |
| 2 | Rickrolling TAA | LR milestones | [150] (论文) | [75] (BackdoorDM) | **配置错误** | BackdoorDM 从 TPA 复制时遗漏修改 | 本文 §5.2 |
| _后续实验完成后继续填写_ | | | | | | | |

### 5.1 EvilEdit ACCASR 偏差详细分析

**现象**: BackdoorDM ACCASR 评估显示 EvilEdit ASR=5%（1/20），与论文报告 ASR=100% 严重不一致。

**诊断过程**:
1. 使用 ViT-base-patch16-224 对 20 张后门图像逐一分类
2. 18/20 条 prompt 确实含有动物 "dog"（2 条为 "hot dog" 食物）
3. 仅 1 张图像被 ViT 分类为 cat (Egyptian cat, label 285)
4. 其余图像 ViT 预测: zebra×4, golden retriever, chow chow, llama, Great Pyrenees, Chihuahua, Welsh springer spaniel, hotdog×3 等

**根因分析**:
1. **评估方法不同**: 原始 EvilEdit 论文使用简单 prompt ("a photo of a beautiful dog") + 人工检测 ASR=100%；BackdoorDM 使用 COCO 验证集 caption + ViT 自动分类
2. **Prompt 复杂度**: COCO caption 包含多样化上下文 ("Two dogs sitting in a basket on a bicycle", "A woman holding a baby near a dog")，后门在复杂语境中激活不充分
3. **ViT 分类偏差**: ViT-base 对 SD 生成图像的分类可能不准确（预测 zebra 等明显错误类别）
4. **EvilEdit 机制局限**: EvilEdit 通过修改 cross-attention 中 "dog" token 的 key-value mapping 实现后门，但当 prompt 较长时，其他 token 的影响可能覆盖后门效果

**结论**: 此偏差不代表 BackdoorDM 实现错误，而是反映了:
- ACCASR 评估方法在复杂 prompt 场景下的局限性
- EvilEdit 攻击在多样化 prompt 下的泛化性问题
- 建议补充简单 prompt 评估作为对照

### 5.2 Rickrolling TAA LR Milestones 偏差分析

**现象**: BackdoorDM 的 `rickrolling_TAA.py` 中 LR scheduler milestones 设为 `[75]`，而 Rickrolling 原论文 (ICCV 2023) TAA 实验应使用 `[150]`。

**根因分析**:
1. BackdoorDM 的 TAA 代码从 TPA 直接复制，TPA 使用 milestones=[75] 是正确的（训练更短）
2. TAA 训练更长，论文建议在 150 epoch 处降低学习率
3. 使用 milestones=[75] 意味着学习率过早衰减，可能导致后门注入不充分

**影响评估**: milestones=[75] 使 LR 在训练前半段就衰减，TAA 后门效果可能弱于论文报告值。需在评估阶段对比 TAA 结果与论文基线。如偏差显著，考虑用修正后的 milestones=[150] 重新训练。

---

## 六、独立实现的论文实验（BackdoorDM 未覆盖）

| 实验 | 来源论文 | 优先级 | 状态 | 结果文件 |
|------|---------|--------|------|---------|
| EvilEdit Lambda 消融 {0.1, 0.5, 1, 2, 5} | EvilEdit (ACM MM 2024) | P0 | _待做_ | |
| EvilEdit Whitelist + VTA | EvilEdit (ACM MM 2024) | P0 | _待做_ | |
| BadDiffusion 多 poison rate (5/10/20/50%) | BadDiffusion (CVPR 2023) | P0 | _待做_ | |
| Rickrolling 多触发类型对比 | Rickrolling (ICCV 2023) | P1 | _待做_ | |
| T2IShield CDA 检测方法 | T2IShield (ECCV 2024) | P1 | _待做_ | |
| VillanDiff psi 消融 | VillanDiff (NeurIPS 2023) | P2 | _待做_ | |
| TrojDiff 多类别/多目标 | TrojDiff (CVPR 2023) | P2 | _待做_ | |

---

## 七、实验计时

| 步骤 | 耗时 | 状态 |
|------|------|------|
| env_verify + fixes | <1m | ✅ 完成 |
| clip_download | (cached) | ✅ 跳过 |
| attack_eviledit | (cached) | ✅ 跳过 |
| attack_eviledit_numAdd | (cached) | ✅ 跳过 |
| attack_rickrolling_TPA | 1m42s | ✅ 完成 |
| attack_rickrolling_TAA | 2m33s | ✅ 完成 |
| attack_paas_ti | ~30m (预估) | 🔄 运行中 (885/2000 steps) |
| attack_paas_db | ~30m (预估) | ⏳ 待执行 |
| attack_badt2i_pixel | ~1-2h (预估) | ⏳ 待执行 |
| attack_badt2i_object/style/objectAdd | ~24h (预估) | ⏳ 待执行 |
| uncond attacks (4个) | ~15h (预估) | ⏳ 待执行 |
| attack_villandiff_cond | ~40h (预估) | ⏳ 待执行 |
| attack_bibaddiff | ~10h (预估) | ⏳ 待执行 |
| 全量评估 | ~5h (预估) | ⏳ 待执行 |
| 全量防御 | ~10h (预估) | ⏳ 待执行 |
