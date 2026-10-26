# BackdoorDM 基准参考 (只读)

> **此文件为不可变基准数据，禁止修改。** 进度信息见 `backdoordm_progress.md`。
> 来源: BackdoorDM 框架论文 (arXiv: 2502.11798) + 原始论文 + 代码分析

---

## BackdoorDM 论文基准值

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

### 防御基准值

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

---

## 指标名称对照

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

## 代码支持的全部指标 (31种)

**写CSV (23种):** FID, CLIP_c, LPIPS, MSE, MSE_{sched}, MSE_perturb, MSE_crop, SSIM, CLIP_p_{n}, CLIP_p_all{n}, MSE_{n}, MSE_all{n}, ACCASR_acc_{n}, ACCASR_asr_{n}, ACCASR_acc_all{n}, ACCASR_asr_all{n}, ACC_mllm_{i}, ASR_mllm_{i}, PSR_mllm_{i}, Precision, Recall, F1 Score, AUC

**仅日志 (8种):** precision_recall, recall_recall, Defended ASR, Defense reduction, TPR, TNR, tvloss, uniformity

---

## 防御方法: 代码输出 vs 论文参考值

| # | 方法 | BackdoorDM 输出指标 | 论文参考值 | 差异说明 |
|---|------|---------------------|-----------|---------|
| 1 | T2IShield | Precision, Recall, F1 (CSV) + defended_model | F1=88.9%(CDA)/86.5%(FFT), Mitigation=99% | 只有FFT无CDA; 不报Mitigation rate |
| 2 | Elijah | TV Loss, Uniformity (仅日志) | Detection ACC=100%, delta-ASR=-0.99 | 不输出检测ACC和ASR降低 |
| 3 | TERD input | reverse trigger mu/gamma | TPR=100%, TNR=100% | 不计算检测TPR/TNR |
| 4 | TERD model | 同上 | 同上 | 同上 |
| 5 | Textual Perturbation | Defended ASR, reduction% (日志) | ASR: RickRolling 1.0→0.0, VillanDiff 1.0→0.3 | 对齐: 均报防御后ASR |
| 6 | DAA | Precision, Recall, F1, AUC (CSV) | F1=79.27%, AUC=86.27% | 完全对齐 |

---

## 官方脚本覆盖情况

### 攻击 (13/16 有脚本)
- run_attack_objectRep.sh: rickrolling_TPA, badt2i_object, paas_ti, paas_db, eviledit
- run_attack_imageFix.sh: baddiffusion, trojdiff, villandiffusion, villandiffusion_cond
- run_attack_imagePatch.sh: badt2i_pixel
- run_attack_styleAdd.sh: rickrolling_TAA, badt2i_style
- run_attack_BiBadDiff.sh: bibaddiff

### 攻击 (3/16 无脚本,需手动启动)
- invi_backdoor: `python attack/uncond_gen/invi_backdoor/invi_backdoor.py --gpu 0`
- badt2i_objectAdd: `python attack/t2i_gen/badt2i/badt2i_objectAdd.py --base_config ... --bd_config ... --model_ver sd15 --device cuda:0`
- eviledit_numAdd: `python attack/t2i_gen/eviledit/eviledit_numAdd.py --base_config ... --bd_config ... --model_ver sd15 --device cuda:0`

### 防御 (2/5 有脚本)
- run_defend_t2ishield.sh: 覆盖9个T2I攻击
- run_defend_elijah.sh: 覆盖3个无条件攻击

### 防御 (3/5 无脚本,需手动启动)
- TERD input: `python defense/input_level/Terd_input/terd_input.py --backdoor_method <method> --device cuda:0`
- TERD model: `python defense/model_level/Terd_model/terd_model.py --backdoor_method <method> --device cuda:0`
- Textual Perturbation: `python defense/input_level/textual_perturbation.py --backdoor_method <method> --device cuda:0`
- DAA: `python defense/input_level/daa/daa.py --backdoor_method <method> --device cuda:0`

---

## 服务器已应用的配置修复

| 修复项 | 状态 |
|--------|------|
| TAA milestones [75]→[150] | ✅ |
| poison_rate 0.7→0.1 | ✅ |
| Textual Perturbation max_mse_dist 0.2→0.05 | ✅ |
| Elijah compute_tvloss False→True | ✅ |
| T2IShield locate_clip_threshold 0.8→0.85 | ✅ |
| DAA AUC (roc_auc_score) | ✅ |
| EvilEdit numAdd path twodogs→threedogs | ✅ |
| BadT2I ObjectAdd ViT crash fix | ✅ |

---

## 已知限制

1. ViT-based ACCASR 系统性低估 ASR (论文用人工/GPT评估)
2. BadT2I batch_size=4 (论文16, GPU限制)
3. T2IShield CDA 未实现 (只有FFT, F1=86.5 vs 88.9)
4. PaaS DB max_train_steps: 论文300步, BackdoorDM曾为2000步

---

## 原始论文参考值 (补充)

| 方法 | 来源 | 关键值 |
|------|------|--------|
| EvilEdit | ACM MM 2024 | ASR=100, CLIP_p=31.11, CLIP_c=26.31, FID=16.29, LPIPS=0.16 |
| RickRolling TPA | 原论文 | FID=17.05; 不报ASR/CLIP_p (用z-Score) |
| PaaS TI | AAAI 2024 | ASR=99.3% (15类平均, CLIP-ASR) |
| PaaS DB | AAAI 2024 | ASR=0.44-1.00 (高度可变); FID=66-95 |
| BadT2I Pixel | ACM MM 2023 | ASR=97.8-98.8, FID=13.0-13.4 |
| BadT2I Object | ACM MM 2023 | ASR=65.8-73.0, FID=12.75-12.95 |
| BadT2I Style | ACM MM 2023 | ASR=60.1-75.7, FID=13.16-13.25 |
| BiBadDiff | NeurIPS 2024 | "From Trojan Horses to Castle Walls" |
| VillanDiff uncond | NeurIPS 2023 | FID=7.62(PR=10%), MSE=9.47e-3 |
| InviBackdoor | 2024 | FID=11.76, MSE=3.07e-3 |

---

## 未来工作 (归档)

- MLLM 评估 (GPT-4o): 需 OpenAI API key。指标: ASR_GPT, PSR_GPT, ACC_GPT
- T2IShield CDA 检测方法实现 (论文最优方法, F1=88.9% vs FFT 86.5%)
- 调查 paas_ti ASR 偏低原因 (基准76.3 vs 复现58.5)
