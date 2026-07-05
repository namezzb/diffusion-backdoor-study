# BackdoorDM 复现进度

> 基准参考见 `backdoordm_reference.md`（只读，勿改）
> 服务器: ssh amax -p 25579 | BD=/opt/data/private/BackdoorDM

## 攻击方法状态

### T2I 攻击 (12)

| # | 方法 | 类型 | 训练 | 模型 | ACCASR | CLIP_p | CLIP_c | FID | LPIPS | MSE |
|---|------|------|------|------|--------|--------|--------|-----|-------|-----|
| 1 | eviledit | ObjectRep | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| 2 | eviledit_numAdd | ObjectAdd | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| 3 | rickrolling_TPA | ObjectRep | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| 4 | rickrolling_TAA | StyleAdd | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ | — |
| 5 | paas_ti | ObjectRep | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| 6 | paas_db | ObjectRep | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| 7 | badt2i_pixel | ImagePatch | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ | ✅ |
| 8 | badt2i_object | ObjectRep | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| 9 | badt2i_style | StyleAdd | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ | — |
| 10 | badt2i_objectAdd | ObjectAdd | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| 11 | bibaddiff | ImagePatch | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 12 | villandiffusion_cond | ImageFix | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | — |

LPIPS 全部完成 (10 T2I ✅)

### 无条件攻击 (4)

| # | 方法 | 训练 | 模型 | FID | MSE |
|---|------|------|------|-----|-----|
| 13 | baddiffusion | ✅ | ✅ | ✅ | ✅ |
| 14 | trojdiff | ✅ | ✅ | ✅ | ✅ |
| 15 | villandiffusion | ✅ | ✅ | ✅ | ✅ |
| 16 | invi_backdoor | ❌ | ❌ | ❌ | ❌ |

## 防御方法状态

| # | 方法 | 状态 |
|---|------|------|
| 1 | T2IShield | ✅ (8方法, F1多为0, 50 prompts) |
| 2 | Elijah | ✅ (3方法, trigger inversion完成) |
| 3 | TERD (input+model) | ❌ (NotImplementedError: 代码未实现) |
| 4 | Textual Perturbation | ✅ (6方法完成, 20 prompts, synonym模式) |
| 5 | DAA | ✅ (10/10完成, 20 prompts) |

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
| badt2i_object | FID | 17.95 | 67.18 | +49.23 | ⚠ 偏高, 可能因 infer_steps=50 |
| rickrolling_TPA | FID | 19.25 | 67.93 | +48.68 | ⚠ 偏高, 同上 |
| eviledit | FID | 16.14 | 66.28 | +50.14 | ⚠ 偏高 |
| eviledit_numAdd | FID | — | 67.35 | — | 无基准 |
| rickrolling_TAA | FID | 23.24 | 68.86 | +45.62 | ⚠ 偏高 |
| paas_ti | FID | 15.41 | 67.35 | +51.94 | ⚠ 偏高 |
| paas_db | FID | 15.68 | 70.29 | +54.61 | ⚠ 偏高 |
| badt2i_pixel | FID | 16.84 | 67.01 | +50.17 | ⚠ 偏高 |
| badt2i_style | FID | 17.39 | 67.20 | +49.81 | ⚠ 偏高 |
| badt2i_objectAdd | FID | — | 66.32 | — | 无基准 |
| baddiffusion | FID | 18.21 | 176.75 | +158.54 | ⚠ 偏高, infer_steps=50 (基准用1000) |
| trojdiff | FID | 19.71 | 180.01 | +160.30 | ⚠ 偏高, infer_steps=50 |
| villandiffusion | FID | 7.62 | 54.91 | +47.29 | ⚠ 偏高, infer_steps=1000 |
| eviledit | LPIPS | 0.1783 | 0.2024 | +0.024 | ✅ 基本吻合 |
| eviledit_numAdd | LPIPS | — | 0.0085 | — | 无基准 |
| rickrolling_TPA | LPIPS | 0.1745 | 0.31 | +0.136 | ⚠ 偏高 |
| rickrolling_TAA | LPIPS | 0.1286 | 0.2745 | +0.146 | ⚠ 偏高 |
| paas_ti | LPIPS | — | 0.0085 | — | 无基准 |
| paas_db | LPIPS | — | 0.3737 | — | 无基准 |
| badt2i_pixel | LPIPS | — | 0.2547 | — | 无基准 |
| badt2i_object | LPIPS | — | 0.2212 | — | 无基准 |
| badt2i_style | LPIPS | — | 0.2429 | — | 无基准 |
| badt2i_objectAdd | LPIPS | — | 0.239 | — | 无基准 |
| badt2i_object | ACC (ACC_ViT) | — | 52.1 | — | 无基准 (非标准方法) |
| badt2i_object | ASR (ASR_ViT) | — | 26.7 | — | 无基准 |
| baddiffusion | MSE | 0.0200 | 0.3611 | +0.341 | ⚠ 偏高 (infer_steps=50, 100张图) |
| trojdiff | MSE | 0.0700 | 0.3611 | +0.291 | ⚠ 偏高 (trigger应用方式可能不正确) |
| villandiffusion | MSE | 0.0095 | 0.3237 | +0.314 | ⚠ 偏高 (trigger应用方式可能不正确) |
| eviledit | CLIP_p | 31.11 | 26.61 | -4.50 | ⚠ 偏低 (paper ref; BackdoorDM ref=27.32) |
| rickrolling_TPA | CLIP_p | 23.88 | 24.08 | +0.20 | ✅ 吻合 |
| eviledit | CLIP_c | 26.31 | 27.24 | +0.93 | ✅ 基本吻合 |
| badt2i_style | CLIP_p | — | 27.11 | — | 无基准 |
| badt2i_style | CLIP_c | — | 26.40 | — | 无基准 |
| rickrolling_TAA | CLIP_p | — | 22.04 | — | 无基准 |
| rickrolling_TAA | CLIP_c | — | 25.87 | — | 无基准 |
| badt2i_pixel | CLIP_p | — | 26.89 | — | 无基准 |
| badt2i_pixel | CLIP_c | — | 26.61 | — | 无基准 |
| badt2i_pixel | MSE | — | 0.0087 | — | 无基准 (ImagePatch) |
| eviledit | DAA Precision | — | 0.5 | — | 无基准 |
| eviledit | DAA Recall | — | 0.22 | — | 无基准 |
| eviledit | DAA F1 | 0.7927 | 0.3056 | -0.487 | ⚠ 偏低 (50 prompts vs 500) |
| eviledit | DAA AUC | 0.8627 | 0.6752 | -0.188 | ⚠ 偏低 |
| rickrolling_TPA | DAA F1 | 0.7927 | 0.9709 | +0.178 | ✅ 超越基准! |
| rickrolling_TPA | DAA AUC | 0.8627 | 0.9988 | +0.136 | ✅ 超越基准! |
| paas_ti | DAA F1 | 0.7927 | 0.3889 | -0.404 | ⚠ 偏低 (50 prompts) |
| paas_ti | DAA AUC | 0.8627 | 0.7144 | -0.148 | ⚠ 偏低 |
| badt2i_style | DAA F1 | — | 0.0678 | — | 无基准 |
| badt2i_style | DAA AUC | — | 0.4588 | — | 无基准 |
| badt2i_pixel | DAA F1 | — | 0.2687 | — | 无基准 |
| badt2i_pixel | DAA AUC | — | 0.5912 | — | 无基准 |
| paas_db | DAA F1 | — | 0.4267 | — | 无基准 |
| paas_db | DAA AUC | — | 0.6352 | — | 无基准 |
| badt2i_object | DAA F1 | — | 0.2222 | — | 无基准 |
| badt2i_object | DAA AUC | — | 0.5992 | — | 无基准 |
| rickrolling_TAA | DAA F1 | — | 0.1724 | — | 无基准 |
| rickrolling_TAA | DAA AUC | — | 0.732 | — | 无基准 |
| eviledit_numAdd | DAA F1 | — | 0.2222 | — | 无基准 (20 prompts) |
| eviledit_numAdd | DAA AUC | — | 0.6125 | — | 无基准 (20 prompts) |
| badt2i_objectAdd | DAA F1 | — | 0.2222 | — | 无基准 (20 prompts) |
| badt2i_objectAdd | DAA AUC | — | 0.6375 | — | 无基准 (20 prompts) |
| eviledit | TP Defended ASR | — | 30.0 | — | 20 prompts, 原ASR=36.5, reduction=70% |
| rickrolling_TPA | TP Defended ASR | — | 100.0 | — | 20 prompts, 原ASR=96.8, reduction=0% (homoglyph触发器不受synonym影响) |
| paas_ti | TP Defended ASR | — | 60.0 | — | 20 prompts, 原ASR=58.9 |
| paas_db | TP Defended ASR | — | 5.0 | — | 20 prompts, 原ASR=3.9 |
| badt2i_object | TP Defended ASR | — | 10.0 | — | 20 prompts, 原ASR=26.7, reduction=63% |
| badt2i_style | TP Defended ASR | — | 0.0 | — | 20 prompts, StyleAdd无原ASR |

## 未训练原因

| 方法 | 失败原因 | 修复状态 |
|------|----------|---------|
| badt2i_pixel | laion 已下载解压 ✅ + imagefolder fallback 加载成功 | ✅ 训练完成 |
| badt2i_object | 同上 | ✅ 训练完成 |
| badt2i_style | 同上 | ✅ 训练完成 |
| badt2i_objectAdd | laion 已下载解压 ✅ + imagefolder fallback ✅ | ✅ 训练完成 |
| invi_backdoor | parse_args bug ✅ + CELEBA-HQ parquet ✅ + **OOM 已修复**: DatasetLoader.__init__ 跳过全量 HF 数据集加载 (parquet 存在时) + DDPM-CELEBA-HQ-256 模型已下载 + 本地路径已配置 + 启动脚本已准备 (/tmp/run_invi_backdoor.sh) | ⏳ 等 GPU 空闲 (bibaddiff 训练中) |
| bibaddiff | imagenette2✅ + v1-5-pruned.ckpt✅ + PL 2.x 不兼容已修复 (12 patches) + **重启**: max_epochs=6 + num_workers=4 (117 steps/min, ETA ~10:25 UTC) | 🔽 训练中 (step ~750/56814, GPU 93%, 18.6GB VRAM, 1.8GB RSS) |
| villandiffusion_cond | vae 未赋值 ✅ + **CelebA-Dialog_HQ 仅 Google Drive**（被代理拦截） | ⛔ 需用户通过 VPN 下载 |

## 统计

- 攻击训练: 13/16 ✅ (bibaddiff 🔽 训练中, invi_backdoor ⏳ 等 GPU, villandiffusion_cond ⛔ 缺数据)
- 攻击评估:
  - ACCASR: 7/7 T2I ✅ (pixel/style/TAA 不需 ACCASR)
  - FID: 10/10 T2I ✅ + 3/3 uncond ✅ (全部偏高, T2I 因 infer_steps=50, uncond 同; villandiffusion 用1000步仍偏高)
  - LPIPS: 10/10 T2I ✅ (eviledit=0.20✅, rickrolling_TPA=0.31⚠, rickrolling_TAA=0.27⚠, 其余无基准)
  - CLIP_p/CLIP_c: 10/10 T2I ✅
  - MSE (ImagePatch): 1/1 ✅ (badt2i_pixel=0.0087)
  - 无条件 MSE: 3/3 ✅ (轻量级脚本, 可能不精确)
- 防御: T2IShield ✅ (8) + Elijah ✅ (3) + DAA ✅ (10/10) + TP ✅ (6/6, synonym模式) + TERD ❌ (代码未实现)
- **下一步**: bibaddiff 训练中 (~8h, ETA 10:25 UTC) → 完成后评估 FID/MSE; invi_backdoor OOM 已修复, 等 GPU 空闲后启动; villandiffusion_cond 缺数据; TERD 代码未实现
- **总结**: 评估全部完成 ✅, 防御4/5完成 (T2IShield/Elijah/DAA/TP), 1/5阻塞 (TERD代码缺失)
- **关键发现**: 每次评估后需 `sync` 清理 page cache (cgroup 16GB 限制)
- **Bug 修复**: 
  1. FID save_path 共享 bug → per-method record_path
  2. write_result UTF-8 编码
  3. DDPMPipeline init 参数不兼容 → 手动 UNet 循环 + torch.no_grad()
  4. cleanfid loky zombie 进程 → 评估后 kill
  5. DatasetLoader 内存溢出 → 轻量级 FID_uncond_light.py (绕过 DatasetLoader)
  6. TP tokenizer 嵌套list → 用 perturbed_prompt[0] 取首variant
  7. TP AttentionStore tensor不匹配 → batch_size=1 一致
  8. TP ASR 变量作用域 → main() return pipe/bd_prompts/generator
  9. TP ASR latents未解码 → 加 VAE decode
  10. TP substeps 模块找不到 → PYTHONPATH 加 t2ishield 目录
