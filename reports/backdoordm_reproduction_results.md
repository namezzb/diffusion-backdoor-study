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
| | FID | N/A | _待填_ | | milestones=[150] (已修复) |
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
| _实验完成后填写_ | | | | | | | |

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

| 阶段 | 脚本 | 开始时间 | 结束时间 | 耗时 | 状态 |
|------|------|---------|---------|------|------|
| 环境验证 | 00_reconnect_and_verify.sh | | | | _待执行_ |
| 配置修复 | 02c_fix_eval_config.sh | | | | _待执行_ |
| CLIP 下载 | 02b_download_clip_large.sh | | | | _待执行_ |
| EvilEdit 评估 | 02d_first_eval_eviledit.sh | | | | _待执行_ |
| 快速 T2I 攻击 | 03_attack_t2i_fast.sh | | | | _待执行_ |
| 慢速 T2I 攻击 | 04_attack_t2i_slow.sh | | | | _待执行_ |
| 无条件攻击 | 05_attack_uncond.sh | | | | _待执行_ |
| VillanDiff Cond | 05b_attack_villan_cond.sh | | | | _待执行_ |
| BiBadDiff | 05c_attack_bibaddiff.sh | | | | _待执行_ |
| T2I 评估 | 06_eval_t2i.sh | | | | _待执行_ |
| 无条件评估 | 07_eval_uncond.sh | | | | _待执行_ |
| T2IShield | 08_defense_t2ishield.sh | | | | _待执行_ |
| Elijah + TERD | 09_defense_elijah_terd.sh | | | | _待执行_ |
| 输入级防御 | 10_defense_input_level.sh | | | | _待执行_ |
