# BackdoorDM 复现进度

> 基准参考见 `backdoordm_reference.md`（只读，勿改）
> 服务器: ssh amax -p 25579 | BD=/opt/data/private/BackdoorDM

## 攻击方法状态

### T2I 攻击 (12)

| # | 方法 | 类型 | 训练 | 模型 | ACCASR | 其他指标 |
|---|------|------|------|------|--------|---------|
| 1 | eviledit | ObjectRep | ✅ | ✅ | ✅ ACC=49.0 ASR=37.8 | ❌ |
| 2 | eviledit_numAdd | ObjectAdd | ✅ | ✅ | ❌ 被中断 | ❌ |
| 3 | rickrolling_TPA | ObjectRep | ✅ | ✅ | ✅ ACC=54.2 ASR=97.0 | ❌ |
| 4 | rickrolling_TAA | StyleAdd | ✅ | ✅ | ❌ | ❌ |
| 5 | paas_ti | ObjectRep | ✅ | ✅ | ✅ ACC=51.7 ASR=58.5 | ❌ |
| 6 | paas_db | ObjectRep | ✅ | ✅ | ❌ eval失败 | ❌ |
| 7 | badt2i_pixel | ImagePatch | ❌ | ❌ | ❌ | ❌ |
| 8 | badt2i_object | ObjectRep | ❌ | ❌ | ❌ | ❌ |
| 9 | badt2i_style | StyleAdd | ❌ | ❌ | ❌ | ❌ |
| 10 | badt2i_objectAdd | ObjectAdd | ❌ | ❌ | ❌ | ❌ |
| 11 | bibaddiff | ImagePatch | ❌ | ❌ | ❌ | ❌ |
| 12 | villandiffusion_cond | ImageFix | ❌ | ❌ | ❌ | ❌ |

### 无条件攻击 (4)

| # | 方法 | 训练 | 模型 | FID | MSE |
|---|------|------|------|-----|-----|
| 13 | baddiffusion | ✅ | ✅ | ❌ | ❌ |
| 14 | trojdiff | ✅ | ✅ | ❌ | ❌ |
| 15 | villandiffusion | ✅ | ✅ | ❌ | ❌ |
| 16 | invi_backdoor | ❌ | ❌ | ❌ | ❌ |

## 防御方法状态

| # | 方法 | 状态 |
|---|------|------|
| 1 | T2IShield | ❌ |
| 2 | Elijah | ❌ |
| 3 | TERD (input+model) | ❌ |
| 4 | Textual Perturbation | ❌ |
| 5 | DAA | ❌ |

## 已完成评估对照

| 方法 | 指标 | 基准值 | 复现值 | 偏差 | 说明 |
|------|------|--------|--------|------|------|
| eviledit | ASR_ViT | 37.10 | 37.8 | +1.9% | 吻合 |
| eviledit | ACC_ViT | 49.20 | 49.0 | -0.4% | 吻合 |
| rickrolling_TPA | ASR_ViT | 95.40 | 97.0 | +1.7% | 吻合 |
| rickrolling_TPA | ACC_ViT | 52.40 | 54.2 | +3.4% | 吻合 |
| paas_ti | ASR_ViT | 76.30 | 58.5 | -23.3% | 偏低,需调查 |
| paas_ti | ACC_ViT | 51.70 | 51.7 | 0% | 完全一致 |

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

## 统计

- 攻击训练: 9/16 ✅
- 攻击评估: 3/16 (仅ACCASR)
- 其他指标: 0/16 (CLIP_p/FID/LPIPS/MSE 全未做)
- 防御: 0/5
- **下一步**: 训练7个未训练攻击 → 运行全部官方eval脚本 → 运行全部防御

## 待办

- [ ] MLLM 评估 (GPT-4o): 需 OpenAI API key。指标: ASR_GPT, PSR_GPT, ACC_GPT
- [ ] T2IShield CDA 检测方法实现 (论文最优方法, F1=88.9% vs FFT 86.5%)
- [ ] 调查 paas_ti ASR 偏低原因 (基准76.3 vs 复现58.5)
