# BackdoorDM 复现进度

> 基准参考见 `backdoordm_reference.md`（只读，勿改）
> 服务器: ssh amax -p 25579 | BD=/opt/data/private/BackdoorDM

## 攻击方法状态

### T2I 攻击 (12)

| # | 方法 | 类型 | 训练 | 模型 | ACCASR | CLIP_p | CLIP_c | FID | LPIPS | MSE |
|---|------|------|------|------|--------|--------|--------|-----|-------|-----|
| 1 | eviledit | ObjectRep | ✅ | ✅ | ✅ | ❌ | ❌ | 🔄 | ❌ | — |
| 2 | eviledit_numAdd | ObjectAdd | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | — |
| 3 | rickrolling_TPA | ObjectRep | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | — |
| 4 | rickrolling_TAA | StyleAdd | ✅ | ✅ | — | ❌ | ❌ | ❌ | ❌ | — |
| 5 | paas_ti | ObjectRep | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | — |
| 6 | paas_db | ObjectRep | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | — |
| 7 | badt2i_pixel | ImagePatch | ✅ | ✅ | — | ❌ | ❌ | ❌ | ❌ | ❌ |
| 8 | badt2i_object | ObjectRep | ✅ | ✅ | ❌ | ❌ | ❌ | 🔄 | ❌ | — |
| 9 | badt2i_style | StyleAdd | ✅ | ✅ | — | ❌ | ❌ | ❌ | ❌ | — |
| 10 | badt2i_objectAdd | ObjectAdd | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | — |
| 11 | bibaddiff | ImagePatch | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 12 | villandiffusion_cond | ImageFix | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | — |

🔄 = 评估进行中 (FID badt2i_object 448/500, 89%)

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

> 之前的评估结果已随中间产物清理删除，全部需重跑。

| 方法 | 指标 | 基准值 | 复现值 | 偏差 | 说明 |
|------|------|--------|--------|------|------|
| rickrolling_TPA | ACC (ACC_ViT) | 52.40 | 54.6 | +2.2 | ✅ 吻合 |
| rickrolling_TPA | ASR (ASR_ViT) | 95.40 | 96.8 | +1.4 | ✅ 吻合 |
| eviledit | ACC (ACC_ViT) | 49.20 | 46.3 | -2.9 | ✅ 基本吻合 |
| eviledit | ASR (ASR_ViT) | 37.10 | 36.5 | -0.6 | ✅ 吻合 |
| paas_ti | ACC (ACC_ViT) | 51.70 | 51.3 | -0.4 | ✅ 吻合 |
| paas_ti | ASR (ASR_ViT) | 76.30 | 58.9 | -17.4 | ⚠ ASR 偏低 |
| paas_db | ACC (ACC_ViT) | 48.50 | 52.1 | +3.6 | ✅ 基本吻合 |
| paas_db | ASR (ASR_ViT) | 43.30 | 3.9 | -39.4 | ⚠ ASR 极低 |
| badt2i_objectAdd | ACC | — | 53.3 | — | 无基准 (非标准方法) |
| badt2i_objectAdd | ASR | — | 21.3 | — | 无基准 |
| eviledit_numAdd | ACC | — | 51.3 | — | 无基准 |
| eviledit_numAdd | ASR | — | 57.6 | — | 无基准 |

## 未训练原因

| 方法 | 失败原因 | 修复状态 |
|------|----------|---------|
| badt2i_pixel | laion 已下载解压 ✅ + imagefolder fallback 加载成功 | 🔽 训练中 Step 144/2000 |
| badt2i_object | 同上 | ✅ 数据就绪，等 GPU |
| badt2i_style | 同上 | ✅ 数据就绪，等 GPU |
| badt2i_objectAdd | laion 已下载解压 ✅ + imagefolder fallback ✅ | ✅ 训练完成 |
| invi_backdoor | parse_args bug ✅ + CELEBA-HQ 已下载 ✅ + **OOM: cgroup 16GB 限制不足**（数据准备 ~12GB + 模型 ~4GB > 16GB） | ⛔ 需更大内存容器或代码优化 |
| bibaddiff | 需 imagenette2(S3)✅ + v1-5-pruned.ckpt✅ + **PL 2.x 不兼容**（代码用 PL 1.x API，环境是 PL 2.6.5+PyTorch 2.7） | ⛔ 需单独环境或大量代码修改 |
| villandiffusion_cond | vae 未赋值 ✅ + **CelebA-Dialog_HQ 仅 Google Drive**（被代理拦截） | ⛔ 需用户通过 VPN 下载 |

## 统计

- 攻击训练: 13/16 ✅ (3个阻塞: invi_backdoor OOM, bibaddiff PL不兼容, villandiffusion_cond 缺数据)
- 攻击评估:
  - ACCASR: 6/7 T2I (badt2i_object 待补; pixel/style/TAA 不需 ACCASR)
  - FID: 🔄 进行中 (badt2i_object 89%, 剩余9方法排队)
  - LPIPS: ❌ 排队中 (FID 完成后自动开始)
  - CLIP_p/CLIP_c: ❌ 待重跑 (需去掉 HF_HUB_OFFLINE=1)
  - MSE (ImagePatch): ❌ 待跑
  - 无条件 FID/MSE: ❌ 待修 (attack_mode + cifar10 报错)
- 防御: 0/5
- **下一步**: 等 FID/LPIPS 跑完 → 补 badt2i_object ACCASR → 重跑 CLIP_p/CLIP_c → 修无条件评估 → 防御
