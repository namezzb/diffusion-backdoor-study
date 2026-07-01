# BackdoorDM 复现进度

> 基准参考见 `backdoordm_reference.md`（只读，勿改）
> 服务器: ssh amax -p 25579 | BD=/opt/data/private/BackdoorDM

## 攻击方法状态

### T2I 攻击 (12)

| # | 方法 | 类型 | 训练 | 模型 | ACCASR | 其他指标 |
|---|------|------|------|------|--------|---------|
| 1 | eviledit | ObjectRep | ✅ | ✅ | ❌ | ❌ |
| 2 | eviledit_numAdd | ObjectAdd | ✅ | ✅ | ❌ | ❌ |
| 3 | rickrolling_TPA | ObjectRep | ✅ | ✅ | ❌ | ❌ |
| 4 | rickrolling_TAA | StyleAdd | ✅ | ✅ | ❌ | ❌ |
| 5 | paas_ti | ObjectRep | ✅ | ✅ | ❌ | ❌ |
| 6 | paas_db | ObjectRep | ✅ | ✅ | ❌ | ❌ |
| 7 | badt2i_pixel | ImagePatch | ✅ | ✅ | ❌ | ❌ |
| 8 | badt2i_object | ObjectRep | ✅ | ✅ | ❌ | ❌ |
| 9 | badt2i_style | StyleAdd | 🔽训练中 | ❌ | ❌ | ❌ |
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

> 之前的评估结果已随中间产物清理删除，全部需重跑。

| 方法 | 指标 | 基准值 | 复现值 | 偏差 | 说明 |
|------|------|--------|--------|------|------|
| (空) | | | | | |

## 未训练原因

| 方法 | 失败原因 | 修复状态 |
|------|----------|---------|
| badt2i_pixel | laion 已下载解压 ✅ + imagefolder fallback 加载成功 | 🔽 训练中 Step 144/2000 |
| badt2i_object | 同上 | ✅ 数据就绪，等 GPU |
| badt2i_style | 同上 | ✅ 数据就绪，等 GPU |
| badt2i_objectAdd | 同上 | ✅ 数据就绪，等 GPU |
| invi_backdoor | parse_args bug ✅ + CELEBA-HQ 已下载 ✅ + **OOM: cgroup 16GB 限制不足**（数据准备 ~12GB + 模型 ~4GB > 16GB） | ⛔ 需更大内存容器或代码优化 |
| bibaddiff | 需 imagenette2(S3)✅ + v1-5-pruned.ckpt✅ + **PL 2.x 不兼容**（代码用 PL 1.x API，环境是 PL 2.6.5+PyTorch 2.7） | ⛔ 需单独环境或大量代码修改 |
| villandiffusion_cond | vae 未赋值 ✅ + **CelebA-Dialog_HQ 仅 Google Drive**（被代理拦截） | ⛔ 需用户通过 VPN 下载 |

## 统计

- 攻击训练: 10/16 (badt2i_pixel 训练中)
- 攻击评估: 0/16 (全部需重跑)
- 防御: 0/5
- **下一步**: 训练7个未训练攻击 → 运行全部官方eval脚本 → 运行全部防御
