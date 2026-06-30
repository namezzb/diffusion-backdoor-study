# BackdoorDM 复现进度

> 更新: 2026-06-30 | 服务器: ssh amax -p 25579 | BD=/opt/data/private/BackdoorDM
> Python: /opt/data/private/miniconda3/envs/eviledit/bin/python

## 攻击方法 (16 变体)

### T2I 攻击 — 需评估指标: ACCASR, CLIP_p, CLIP_c, FID, LPIPS

| # | 方法 | 类型 | 训练 | 模型 | ACCASR | CLIP/FID/LPIPS | 论文参考值 |
|---|------|------|------|------|--------|----------------|-----------|
| 1 | eviledit | ObjectRep | ✅ | ✅ | ✅ ACC=49.0 ASR=37.8 | ❌ | ASR=100, CLIP_p=31.11, CLIP_c=26.31, FID=16.29, LPIPS=0.16 |
| 2 | eviledit_numAdd | ObjectAdd | ✅ | ✅ | ❌ 被中断 | ❌ | 无独立基线 (BackdoorDM自创变体,EvilEdit论文ASR=100) |
| 3 | rickrolling_TPA | ObjectRep | ✅ | ✅ | ✅ ACC=54.2 ASR=97.0 | ❌ | ASR=98.4, CLIP_p=29.85, FID=17.11 ( EvilEdit Table.1复测); 原论文FID=17.05, 不报ASR/CLIP_p |
| 4 | rickrolling_TAA | StyleAdd | ✅ | ✅ | ❌ | ❌ | 原论文不报ASR; FID≈17.05 (与TPA共享clean model); 用z-Score非ASR |
| 5 | paas_ti | ObjectRep | ✅ | ✅ | ✅ ACC=51.7 ASR=58.5 | ❌ | ASR=99.3 (15类平均); FID=5.8-17.2 (按类别) |
| 6 | paas_db | ObjectRep | ✅ | ✅ | ❌ eval失败 | ❌ | ASR=0.44-1.00 (高度可变); FID=66-95 (质量严重下降) |
| 7 | badt2i_pixel | ImagePatch | ❌ | ❌ | ❌ | ❌ | ASR=97.8(boya)/98.8(mark), FID=13.0-13.4, MSE=仅图(无表), LPIPS=原论文未报 |
| 8 | badt2i_object | ObjectRep | ❌ | ❌ | ❌ | ❌ | ASR=65.8(dog→cat)/73.0(motorbike→bike), FID=12.75-12.95; EvilEdit复测ASR=47.5,FID=16.52,LPIPS=0.22 |
| 9 | badt2i_style | StyleAdd | ❌ 训练完成但无模型 | ❌ | ❌ | ❌ | ASR=60.1(水彩)/64.9(油画)/75.7(黑白), FID=13.16-13.25 |
| 10 | badt2i_objectAdd | ObjectAdd | ❌ | ❌ | ❌ | ❌ | N/A (BackdoorDM自创变体,原论文无此变体) |
| 11 | bibaddiff | ImagePatch | ❌ | ❌ | ❌ | ❌ | ASR=34.1 (BackdoorDM复测); 原论文"From Trojan Horses to Castle Walls" |
| 12 | villandiffusion_cond | ImageFix | ❌ | ❌ | ❌ | ❌ | MSE=3.82e-3 (mignneko/CelebA), FID(clean)=19.97; 多trigger: MSE=3.8e-3~1.6e-2 |

### 无条件攻击 — 需评估指标: FID, MSE

| # | 方法 | 训练 | 模型 | FID | MSE | 论文参考值 |
|---|------|------|------|-----|-----|-----------|
| 13 | baddiffusion | ✅ | ✅ | ❌ | ❌ | FID=8.89 (PR=20%), MSE=1.19e-5 (PR=20%) |
| 14 | trojdiff | ✅ | ✅ | ❌ | ❌ | FID=4.74 (In-D2D), MSE=1.00e-5 (D2I), ASR=90.1 (In-D2D) |
| 15 | villandiffusion | ✅ | ✅ | ❌ | ❌ | FID=7.62 (PR=10%,ANCESTRAL), MSE=9.47e-3 (PR=10%); 多sampler: FID=7.1-16.4 |
| 16 | invi_backdoor | ❌ | ❌ | ❌ | ❌ | FID=11.76, MSE=3.07e-3 (universal trigger,PR=5%); 条件模式: FID=1.01,LPIPS=0.064,MSE=6.85e-3 |

## 防御方法 (5)

| # | 方法 | 状态 | BackdoorDM 输出指标 | 论文参考值 | 差异说明 |
|---|------|------|---------------------|-----------|---------|
| 1 | T2IShield | ❌ | Precision, Recall, F1 Score (CSV) + defended_model | F1=88.9%(CDA)/86.5%(FFT), Mitigation=99% | BackdoorDM 只有FFT无CDA; 论文还报Mitigation rate |
| 2 | Elijah | ❌ | TV Loss, Uniformity score (无CSV,仅日志) | Detection ACC=100%, delta-ASR=-0.99, delta-FID=0.03 | BackdoorDM 不输出检测ACC和ASR降低,只保存trigger inversion结果 |
| 3 | TERD (input) | ❌ | reverse trigger mu/gamma (无TPR/TNR输出) | TPR=100%, TNR=100% | BackdoorDM 只保存反演trigger,不计算检测TPR/TNR |
| 4 | TERD (model) | ❌ | 同上 | 同上 | 同上 |
| 5 | Textual Perturbation | ❌ | Defended ASR, Defense reduction% (日志) | ASR: RickRolling 1.0→0.0, VillanDiff 1.0→0.3 | 对齐: 均报防御后ASR |
| 6 | DAA | ❌ | Precision, Recall, F1, AUC (CSV) | F1=79.27%, AUC=86.27% | 完全对齐 |

## BackdoorDM 论文基准值 (arXiv: 2502.11798)

> 以下为 BackdoorDM 框架论文报告的基准值，是我们复现的**主要对照标准**。

### ImageFix (无条件) 攻击 — Table 3

| 方法 | MSE↓ | FID↓ | Runtime | Data Usage |
|------|------|------|---------|------------|
| BadDiffusion | 0.0200 | 18.21 | 4032s | 10% |
| TrojDiff | 0.0700 | 19.71 | 83197s | 10% |
| InviBackdoor | 0.0950 | 58.19 | 32662s | 10% |
| VillanDiffusion | 0.0300 | 13.50 | 4018s | 10% |
| VillanCond | 0.0010 | 28.81 | 105773s | 100% |

### ImagePatch 攻击 — Table 4

| 方法 | MSE↓ | TCS↑ | ASR_GPT↑ | PSR_GPT↑ | BCS↑ | ACC_GPT↑ | FID↓ | LPIPS↓ |
|------|------|------|---------|---------|------|---------|------|--------|
| BiBadDiff | 0.2353 | 11.63 | 34.10 | 25.72 | 13.87 | 19.48 | 88.50 | 0.5375 |
| Pixel-Backdoor | 0.0087 | 25.54 | 99.60 | 89.69 | 25.64 | 84.51 | 21.34 | 0.3099 |

### ObjectRep 攻击 — Table 5 (target: dog→cat)

| 方法 | ASR_ViT↑ | TCS↑ | ASR_GPT↑ | PSR_GPT↑ | ACC_ViT↑ | BCS↑ | ACC_GPT↑ | FID↓ | LPIPS↓ |
|------|---------|------|---------|---------|---------|------|---------|------|--------|
| TPA (RickRolling) | 95.40 | 23.88 | 96.80 | 5.50 | 52.40 | 27.02 | 83.41 | 19.25 | 0.1745 |
| Object-Backdoor | 24.80 | 24.90 | 40.30 | 82.19 | 54.00 | 27.30 | 83.94 | 17.95 | 0.2133 |
| TI (PaaS) | 76.30 | 19.82 | 88.70 | 30.34 | 51.70 | 27.36 | 84.27 | 18.44 | 0.0055 |
| DB (PaaS) | 43.30 | 21.72 | 51.30 | 60.22 | 48.50 | 24.37 | 70.87 | 38.25 | 0.5877 |
| EvilEdit | 37.10 | 26.68 | 61.10 | 85.25 | 49.20 | 27.32 | 83.01 | 17.67 | 0.1783 |

### StyleAdd 攻击 — Table 6 (target: B&W photo)

| 方法 | TCS↑ | ASR_GPT↑ | PSR_GPT↑ | BCS↑ | ACC_GPT↑ | FID↓ | LPIPS↓ |
|------|------|---------|---------|------|---------|------|--------|
| TAA (RickRolling) | 24.02 | 96.30 | 65.92 | 26.45 | 86.18 | 19.05 | 0.1286 |
| Style-Backdoor | 27.48 | 91.30 | 90.68 | 26.22 | 84.82 | 19.00 | 0.2219 |

### 防御结果

#### TERD Input 检测 — Table 15

| 方法 | TPR↑ | TNR↑ |
|------|------|------|
| BadDiffusion | 100% | 100% |
| TrojDiff | 100% | 100% |
| VillanDiffusion | 100% | 100% |

#### T2IShield 防御 ObjectRep — Table 16 (delta = 防御后变化)

| 方法 | delta_ASR_GPT | delta_PSR_GPT | delta_ACC_GPT |
|------|---------------|---------------|---------------|
| TPA | -96.80 | -5.50 | -83.41 |
| Object-Backdoor | -40.30 | -82.19 | -83.94 |
| TI (PaaS) | -88.70 | -30.34 | -84.27 |
| DB (PaaS) | -51.30 | -60.22 | -70.87 |
| EvilEdit | -61.10 | -85.25 | -83.01 |

#### Elijah 防御 ImageFix — Table 14 (delta = 防御后变化)

| 方法 | delta_MSE | delta_FID |
|------|-----------|-----------|
| BadDiffusion | 0.34 | 0.36 |
| TrojDiff | 0.04 | 11.65 |
| InviBackdoor | 0.00 | -39.26 |
| VillanDiffusion | 0.13 | 1.53 |

### BackdoorDM 指标名称对照

| BackdoorDM 论文 | 代码中 | main_eval.py --metric | 说明 |
|----------------|--------|----------------------|------|
| ASR_ViT | ACCASR_asr | ACCASR | ViT分类的攻击成功率 |
| ACC_ViT | ACCASR_acc | ACCASR | ViT分类的干净准确率 |
| TCS | CLIP_p | CLIP_p | 目标CLIP分数 |
| BCS | CLIP_c | CLIP_c | 干净CLIP分数 |
| FID | FID | FID | 图像质量距离 |
| LPIPS | LPIPS | LPIPS | 感知相似度 |
| MSE | MSE | MSE | 像素级误差 |
| ASR_GPT | ASR_mllm | mllm_eval.py | GPT-4o评估的ASR |
| PSR_GPT | PSR_mllm | mllm_eval.py | GPT-4o评估的保持率 |
| ACC_GPT | ACC_mllm | mllm_eval.py | GPT-4o评估的准确率 |

### BackdoorDM 代码支持的全部指标 (31种)

**写CSV的指标 (23种):**
FID, CLIP_c, LPIPS, MSE, MSE_{sched}, MSE_perturb, MSE_crop, SSIM, CLIP_p_{n}, CLIP_p_all{n}, MSE_{n}, MSE_all{n}, ACCASR_acc_{n}, ACCASR_asr_{n}, ACCASR_acc_all{n}, ACCASR_asr_all{n}, ACC_mllm_{i}, ASR_mllm_{i}, PSR_mllm_{i}, Precision, Recall, F1 Score, AUC

**仅日志的指标 (8种):**
precision_recall (improved), recall_recall (improved), Defended ASR, Defense reduction, TPR, TNR, tvloss, uniformity

## 已完成评估结果

| 方法 | 指标 | BackdoorDM基准值 | 复现值 | 偏差 | 说明 |
|------|------|-----------------|--------|------|------|
| eviledit | ASR_ViT | 37.10 | 37.8 | +1.9% | 吻合 |
| eviledit | ACC_ViT | 49.20 | 49.0 | -0.4% | 吻合 |
| rickrolling_TPA | ASR_ViT | 95.40 | 97.0 | +1.7% | 吻合 |
| rickrolling_TPA | ACC_ViT | 52.40 | 54.2 | +3.4% | 吻合 |
| paas_ti | ASR_ViT | 76.30 | 58.5 | -23.3% | 偏低,需调查(max_train_steps差异?) |
| paas_ti | ACC_ViT | 51.70 | 51.7 | 0% | 完全一致 |

## 服务器已应用的配置修复

| 修复项 | 状态 |
|--------|------|
| TAA milestones [75]→[150] | ✅ |
| poison_rate 0.7→0.1 | ✅ |
| Textual Perturbation max_mse_dist 0.2→0.05 | ✅ |
| Elijah compute_tvloss False→True | ✅ |
| T2IShield locate_clip_threshold 0.8→0.85 | ✅ |
| DAA AUC (roc_auc_score) | ✅ 已实现 |
| EvilEdit numAdd path twodogs→threedogs | ✅ |
| BadT2I ObjectAdd ViT crash fix | ✅ |

## 未训练原因

| 方法 | 失败原因 | 修复状态 |
|------|----------|---------|
| badt2i_pixel | 数据集无图像 | 需预生成500张图 |
| badt2i_object | 同上 | 同上 |
| badt2i_style | 训练完成但模型未保存 | 需重跑 |
| badt2i_objectAdd | 同badt2i_pixel | 需预生成 |
| invi_backdoor | parse_args bug | ✅ 已修复,需重跑 |
| bibaddiff | 需imagenette数据+ckpt转换 | 需下载+转换 |
| villandiffusion_cond | vae未赋值 | ✅ 已修复,需重跑 |

## 已知限制

1. ViT-based ACCASR 系统性低估 ASR (论文用人工/GPT评估)
2. BadT2I batch_size=4 (论文16, GPU限制)
3. T2IShield CDA 未实现 (只有FFT, F1=86.5 vs 88.9)
4. PaaS DB max_train_steps: 论文300步, BackdoorDM曾为2000步 (已确认训练9m16s, 疑已修复为300)

## BackdoorDM 官方脚本覆盖情况

### 有官方 run 脚本的攻击 (13/16)
- run_attack_objectRep.sh: rickrolling_TPA, badt2i_object, paas_ti, paas_db, eviledit
- run_attack_imageFix.sh: baddiffusion, trojdiff, villandiffusion, villandiffusion_cond
- run_attack_imagePatch.sh: badt2i_pixel
- run_attack_styleAdd.sh: rickrolling_TAA, badt2i_style
- run_attack_BiBadDiff.sh: bibaddiff

### 无官方 run 脚本的攻击 (3/16) — 需手动启动
- invi_backdoor: `python attack/uncond_gen/invi_backdoor/invi_backdoor.py --gpu 0`
- badt2i_objectAdd: `python attack/t2i_gen/badt2i/badt2i_objectAdd.py --base_config ... --bd_config ... --model_ver sd15 --device cuda:0`
- eviledit_numAdd: `python attack/t2i_gen/eviledit/eviledit_numAdd.py --base_config ... --bd_config ... --model_ver sd15 --device cuda:0`

### 有官方 run 脚本的防御 (2/5)
- run_defend_t2ishield.sh: 覆盖9个T2I攻击
- run_defend_elijah.sh: 覆盖3个无条件攻击

### 无官方 run 脚本的防御 (3/5) — 需手动启动
- TERD input: `python defense/input_level/Terd_input/terd_input.py --backdoor_method <method> --device cuda:0`
- TERD model: `python defense/model_level/Terd_model/terd_model.py --backdoor_method <method> --device cuda:0`
- Textual Perturbation: `python defense/input_level/textual_perturbation.py --backdoor_method <method> --device cuda:0`
- DAA: `python defense/input_level/daa/daa.py --backdoor_method <method> --device cuda:0`

## 统计

- 攻击训练: 9/16 ✅
- 攻击评估: 3/16 (仅ACCASR)
- 其他指标: 0/16 (CLIP_p/FID/LPIPS/MSE 全未做)
- 防御: 0/5
- **下一步**: 训练7个未训练攻击 → 运行全部官方eval脚本 → 运行全部防御

## 待办

- [ ] MLLM 评估 (GPT-4o): BackdoorDM 特色评估方法，`run_eval_mllm.sh` 覆盖8个T2I攻击，需 OpenAI API key。指标: ASR_GPT, PSR_GPT, ACC_GPT
- [ ] T2IShield CDA 检测方法实现 (论文最优方法, F1=88.9% vs FFT 86.5%)
