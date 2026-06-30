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

> 之前的评估结果已随中间产物清理删除，全部需重跑。

| 方法 | 指标 | 基准值 | 复现值 | 偏差 | 说明 |
|------|------|--------|--------|------|------|
| (空) | | | | | |

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
- 攻击评估: 0/16 (全部需重跑)
- 防御: 0/5
- **下一步**: 训练7个未训练攻击 → 运行全部官方eval脚本 → 运行全部防御
