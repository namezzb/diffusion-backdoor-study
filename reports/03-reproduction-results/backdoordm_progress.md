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

| # | 方法 | 状态 | 论文参考值 |
|---|------|------|-----------|
| 1 | T2IShield | ❌ | F1=88.9(CDA)/86.5(FFT), Mitigation rate=99%, Refact ASR=0.01 vs UCE ASR=0.20 |
| 2 | Elijah | ❌ | Detection ACC=100%, delta-ASR=-0.99 (后门降至~0%), delta-FID=0.03 (质量保持) |
| 3 | TERD (input+model) | ❌ | TPR=100%, TNR=100% |
| 4 | Textual Perturbation | ❌ | ASR: RickRolling 1.0→0.0, VillanDiff 1.0→0.3, TextInv 1.0→0.0; FID均改善 |
| 5 | DAA | ❌ | F1=79.27%, AUC=86.27% |

## 已完成评估结果

| 方法 | 指标 | 论文值 | 复现值 | 偏差 | 说明 |
|------|------|--------|--------|------|------|
| eviledit | ASR | 100 | 37.8 | -62% | ViT低估(论文用ViT但用简单prompt,BackdoorDM用COCO复杂caption) |
| eviledit | CLIP_p | 31.11 | ❌ | - | 未评估 |
| eviledit | FID | 16.29 | ❌ | - | 未评估 |
| rickrolling_TPA | ASR | 98.4 | 97.0 | -1% | 吻合 (EvilEdit Table.1复测值) |
| rickrolling_TPA | FID | 17.11 | ❌ | - | 未评估 |
| paas_ti | ASR | 99.3 | 58.5 | -41% | 论文用CLIP-ASR,BackdoorDM用ViT-ASR |
| paas_ti | FID | 5.8-17.2 | ❌ | - | 未评估 |

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
