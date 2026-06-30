# BackdoorDM 复现进度

> 更新: 2026-06-30 | 服务器: ssh amax -p 25579 | BD=/opt/data/private/BackdoorDM
> Python: /opt/data/private/miniconda3/envs/eviledit/bin/python

## 攻击方法 (16 变体)

### T2I 攻击 — 需评估指标: ACCASR, CLIP_p, CLIP_c, FID, LPIPS

| # | 方法 | 类型 | 训练 | 模型 | ACCASR | CLIP/FID/LPIPS | 论文参考值 |
|---|------|------|------|------|--------|----------------|-----------|
| 1 | eviledit | ObjectRep | ✅ | ✅ | ✅ ACC=49.0 ASR=37.8 | ❌ | ASR=100, CLIP_p=31.11, FID=16.29, LPIPS=0.16 |
| 2 | eviledit_numAdd | ObjectAdd | ✅ | ✅ | ❌ 被中断 | ❌ | ASR=100 |
| 3 | rickrolling_TPA | ObjectRep | ✅ | ✅ | ✅ ACC=54.2 ASR=97.0 | ❌ | ASR=98.4, CLIP_p=29.85, FID=17.11 |
| 4 | rickrolling_TAA | StyleAdd | ✅ | ✅ | ❌ | ❌ | FID~17 |
| 5 | paas_ti | ObjectRep | ✅ | ✅ | ✅ ACC=51.7 ASR=58.5 | ❌ | "always high" |
| 6 | paas_db | ObjectRep | ✅ | ✅ | ❌ eval失败 | ❌ | "relatively low" |
| 7 | badt2i_pixel | ImagePatch | ❌ | ❌ | ❌ | ❌ | - |
| 8 | badt2i_object | ObjectRep | ❌ | ❌ | ❌ | ❌ | ASR=47.5, FID=16.52, LPIPS=0.22 |
| 9 | badt2i_style | StyleAdd | ❌ 训练完成但无模型 | ❌ | ❌ | ❌ | - |
| 10 | badt2i_objectAdd | ObjectAdd | ❌ | ❌ | ❌ | ❌ | - |
| 11 | bibaddiff | ImagePatch | ❌ | ❌ | ❌ | ❌ | ASR=34.1 |
| 12 | villandiffusion_cond | ImageFix | ❌ | ❌ | ❌ | ❌ | MSE=3.82e-3 |

### 无条件攻击 — 需评估指标: FID, MSE

| # | 方法 | 训练 | 模型 | FID | MSE | 论文参考值 |
|---|------|------|------|-----|-----|-----------|
| 13 | baddiffusion | ✅ | ✅ | ❌ | ❌ | FID=8.89, MSE=1.19e-5 |
| 14 | trojdiff | ✅ | ✅ | ❌ | ❌ | FID=4.74, MSE=1.00e-5, ASR=90.1 |
| 15 | villandiffusion | ✅ | ✅ | ❌ | ❌ | FID~5.0, MSE=3.82e-3 |
| 16 | invi_backdoor | ❌ | ❌ | ❌ | ❌ | - |

## 防御方法 (5)

| # | 方法 | 状态 | 论文参考值 |
|---|------|------|-----------|
| 1 | T2IShield | ❌ | F1=88.9(CDA)/86.5(FFT) |
| 2 | Elijah | ❌ | TV Loss enabled |
| 3 | TERD (input+model) | ❌ | TPR/TNR=100% |
| 4 | Textual Perturbation | ❌ | max_mse_dist=0.05 |
| 5 | DAA | ❌ | F1=79.27, AUC=86.27 |

## 已完成评估结果

| 方法 | 指标 | 论文值 | 复现值 | 偏差 | 说明 |
|------|------|--------|--------|------|------|
| eviledit | ASR | 100 | 37.8 | -62% | ViT低估(论文用人工/GPT) |
| rickrolling_TPA | ASR | 98.4 | 97.0 | -1% | 吻合 |
| paas_ti | ASR | "high" | 58.5 | - | 中等偏低(ViT vs CLIP-ASR) |

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

## 统计

- 攻击训练: 9/16 ✅
- 攻击评估: 3/16 (仅ACCASR)
- 其他指标: 0/16 (CLIP_p/FID/LPIPS/MSE 全未做)
- 防御: 0/5
- **下一步**: 训练7个未训练攻击 → 运行全部官方eval脚本 → 运行全部防御
