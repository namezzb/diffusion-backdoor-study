# BackdoorDM 复现进度

> 基准参考见 `backdoordm_reference.md`（只读，勿改）
> 服务器: ssh amax -p 25579 | BD=/opt/data/private/BackdoorDM

## 2026-07-08 校正状态

- VillanDiffusion GLASSES/psi=1 已于 2026-07-07 23:58:28 完成，但 benchmark/paper 指向 grey box；BOX_14/psi=1 已重训完成到 `results/villandiffusion_BOX14_DDPM-CIFAR10-32_psi1`。
- baddiffusion 1000步 MSE 已用修正版采样得到 0.01862，与基准 0.0200 对齐；10K FID=18.1288，对齐基准 18.21。
- 官方 uncond FID/MSE 脚本已补 CIFAR10 参数；旧 uncond FID 结果混用默认 CELEBA-HQ 对照，不作为完成证据。
- 官方 T2I FID 脚本已补 `--img_num_FID 10000`；旧 T2I FID 结果仅 1000 张，不作为最终完成证据。
- FID 真实图缓存目录已加入 dataset tag；后续重跑不会复用不同数据集的 original-image cache。
- VillanDiffusion BOX_14/psi=1 已完成 1000 张 MSE/FID 与 10K FID；MSE=0.03870 基本对齐基准 0.0300，10K FID=13.6067 对齐基准 13.50。
- uncond eval 的 `bd_config` CLI 参数会被 `base_args_uncond_v2` 覆盖为默认配置，已修复为仅在未传参时使用默认值；VillanDiffusion FID 以 `BOX_14` 标签行 `2026-07-08_12-18-06` 为准。
- clean `ddpm-cifar10-32` 在同一 1000 张 CIFAR10 FID 管线下 FID=58.91，高于 VillanDiffusion BOX_14 的 54.91；该偏高主要来自 1000 张评估协议，不是 BOX_14 模型独有退化。
- VillanDiffusion 论文说明 CIFAR10 评估生成 10K clean/backdoor samples；BOX_14/psi=1 的 10K FID 重评已完成，确认 1000 张 FID 偏高来自评估协议。
- 远端 uncond FID/MSE 脚本中的 VillanDiffusion 默认路径已改为 BOX_14/psi=1 checkpoint，并显式传入 `bd_config_villan_box14.yaml`，避免脚本化重跑回退到旧 GLASSES checkpoint。
- 远端 uncond FID/MSE 脚本已为 baddiffusion/trojdiff/villandiffusion 显式传入 `--eval_max_batch 128`，避免默认 `eval_config_uncond.yaml` 的 batch=1 造成 10K 评估低吞吐。
- VillanDiffusion BOX_14 10K FID 在真实图缓存完成后按 GPU 利用率从 batch=128 调到 1408；最终 FID=13.6067，日志 `/tmp/fid_villan_box14_10000_b1408.log`。
- VillanDiffusion 10K FID 的采样路径为 `villan_eval.yaml` 的 `DDPM-SCHED`，会重建 fixed_small/clip_sample=false scheduler；这与 BOX_14/psi=1 训练产物 scheduler 配置一致，10K FID 已验证正常。
- 远端 `run_eval_fix_MSE.sh` 已改为对 baddiffusion/trojdiff/villandiffusion 调用 `/temp_script/run_uncond_mse_stream.py`，规避旧 MSE 路径一次性载入全部图片和缓存污染；VillanDiffusion 使用 BOX_14 路径、`--variant full`。
- 远端 `evaluation/main_eval.py` 已新增 `--batch_size` CLI 覆盖，默认仍走 YAML；后续 T2I 10K FID 可按显存调参而不改配置文件。
- TrojDiff MSE 先用 128 张 probe 得到 0.07165，再用 1000 张正式评估得到 0.07167；`eval_max_batch=1000` 因 cgroup OOM 失败，`eval_max_batch=512` 完成。
- BadDiffusion 10K FID 使用 `eval_max_batch=1408` 完成，生成图 10000/10000 且首批 md5 去重正常；最终 FID=18.1288，对齐基准 18.21。
- TrojDiff 10K FID 使用 `eval_max_batch=1408` 完成，生成图 10000/10000 且首批 md5 去重正常；最终 FID=19.5955，对齐基准 19.71。
- InviBackdoor FID 应按 BackdoorDM benchmark 58.19 验收，不按原论文补充值 11.76；dataset-tagged CELEBA-HQ 原图缓存重算得到 FID=52.1057，优于基准。
- InviBackdoor MSE 正式 1000张重评运行中：`/tmp/mse_invi_1000_b32.log`，`eval_max_batch=32`，已落盘 320/1000；该 256x256 任务预计小时级运行。

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
| 11 | bibaddiff | ImagePatch | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ | ✅ |
| 12 | villandiffusion_cond | ImageFix | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | — |

LPIPS 全部完成 (10 T2I ✅)

### 无条件攻击 (4)

| # | 方法 | 训练 | 模型 | FID | MSE |
|---|------|------|------|-----|-----|
| 13 | baddiffusion | ✅ | ✅ | ✅ | ✅ |
| 14 | trojdiff | ✅ | ✅ | ✅ | ✅ |
| 15 | villandiffusion | ✅ BOX_14/psi=1 | ✅ | ✅ 13.61 | ✅ |
| 16 | invi_backdoor | ✅ | ✅ | ✅ | ✅ |

## 防御方法状态

| # | 方法 | 状态 |
|---|------|------|
| 1 | T2IShield | ✅ (8方法, F1多为0, 50 prompts) |
| 2 | Elijah | ✅ (3方法, trigger inversion完成) |
| 3 | TERD (input+model) | 🔄 input: baddiffusion ✅ (TPR=100%, TNR=100%) + villandiffusion ✅ (TPR=100%, TNR=100%) + trojdiff 修复后待重跑; model: baddiffusion ✅ (M_r=0.48, V_r=0.004) + trojdiff ✅ (M_r=0.99, V_r=1.62); villandiffusion 不支持 |
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
| baddiffusion | FID | 18.21 | 18.1288 | -0.0812 | ✅ 10K张正式重评对齐基准 |
| trojdiff | FID | 19.71 | 180.01 | +160.30 | ⚠ 偏高, infer_steps=50 |
| trojdiff | FID | 19.71 | 19.5955 | -0.1145 | ✅ 10K张正式重评对齐基准 |
| clean ddpm-cifar10-32 | FID | — | 58.91 | — | 诊断对照: 同一 1000 张 CIFAR10 管线，说明 1K FID 估计偏高 |
| villandiffusion | FID | 13.50 | 54.91 | +41.41 | ⚠ 1000张诊断值偏高; 已由10K重评排除模型退化 |
| villandiffusion | FID | 13.50 | 13.6067 | +0.1067 | ✅ 10K张正式重评对齐基准 |
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
| baddiffusion | MSE | 0.0200 | 0.01862 | -0.00138 | ✅ 吻合 (1000张图, infer_steps=1000, 修正版触发采样) |
| bibaddiff | MSE | 0.2353 | 0.2612 | +0.026 | ✅ 基本吻合 (1000张图, infer_steps=50) |
| bibaddiff | CLIP_p (TCS) | 11.63 | 17.778 | +6.15 | ✅ 超越基准 (T2I CLIP-prompt score) |
| bibaddiff | CLIP_c (BCS) | 13.87 | 12.2403 | -1.63 | ✅ 基本吻合 |
| bibaddiff | FID | 88.50 | 489.3778 | +400.88 | ⚠ 极高 (1000张图, 复用clean图; 模型可能生成质量差) |
| bibaddiff | LPIPS | 0.5375 | 0.7567 | +0.219 | ⚠ 偏高 (100张图, 非1000) |
| trojdiff | MSE | 0.0700 | 0.3611 | +0.291 | ⚠ 旧路径诊断值偏高; 已由stream helper重评替代 |
| trojdiff | MSE | 0.0700 | 0.07167 | +0.00167 | ✅ 1000张正式重评对齐基准 |
| villandiffusion | MSE | 0.0300 | 0.03870 | +0.00870 | ✅ 基本吻合 (BOX_14/psi=1, full trigger, 1000张图, infer_steps=1000) |
| invi_backdoor | FID | 58.19 | 59.0153 | +0.8253 | ✅ 旧原图缓存路径下已基本对齐 BackdoorDM benchmark |
| invi_backdoor | FID | 58.19 | 52.1057 | -6.0843 | ✅ dataset-tagged CELEBA-HQ 原图缓存重算，优于基准 |
| invi_backdoor | MSE | 0.0950 | 0.1083 | +0.0133 | ⚠ 仅100张旧评估，需1000张重评或协议诊断 |
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
| baddiffusion | TERD TPR | 100% | 100% | 0 | ✅ 完全吻合 (input-level detection) |
| baddiffusion | TERD TNR | 100% | 100% | 0 | ✅ 完全吻合 |
| villandiffusion | TERD TPR | 100% | 100% | 0 | ✅ 完全吻合 (input-level detection) |
| villandiffusion | TERD TNR | 100% | 100% | 0 | ✅ 完全吻合 |
| trojdiff | TERD TPR | 100% | 待重跑 | — | 🔄 reverse_trojdiff 覆盖采样 bug 已修复 |
| trojdiff | TERD TNR | 100% | 99% | -1 | ✅ 基本吻合 (FPR=1%) |
| baddiffusion | TERD model M_r | — | 0.4808 | — | ✅ M_r>0, 正确检测后门 (model-level) |
| baddiffusion | TERD model V_r | — | 0.0037 | — | ✅ V_r>0, 正确检测后门 |
| trojdiff | TERD model M_r | — | 0.9898 | — | ✅ M_r>0, 正确检测后门 (model-level) |
| trojdiff | TERD model V_r | — | 1.6228 | — | ✅ V_r>0, 正确检测后门 |

## 未训练原因

| 方法 | 失败原因 | 修复状态 |
|------|----------|---------|
| badt2i_pixel | laion 已下载解压 ✅ + imagefolder fallback 加载成功 | ✅ 训练完成 |
| badt2i_object | 同上 | ✅ 训练完成 |
| badt2i_style | 同上 | ✅ 训练完成 |
| badt2i_objectAdd | laion 已下载解压 ✅ + imagefolder fallback ✅ | ✅ 训练完成 |
| invi_backdoor | parse_args bug ✅ + CELEBA-HQ parquet ✅ + **OOM 已修复**: DatasetLoader.__init__ 跳过全量 HF 数据集加载 (parquet 存在时) + DDPM-CELEBA-HQ-256 模型已下载 + 本地路径已配置 + **bs 变量修复** ✅ + **ckpt_path=None 修复** ✅ + **delta 尺寸不匹配修复 (patch placement)** ✅ + **trigger 32x32→256x256 尺寸修复** (baddiff_backdoor.py get_trigger INVI 分支: pad to image_size) ✅ + **delta_target crop 修复** (dsl.target[:, :ts, :ts]) ✅ + **内存清理** (del + empty_cache after delta opt) ✅ + **NaN 修复** (--learning_rate 2e-5 替代默认 0.0002) ✅ | ✅ 训练完成 (epoch 9 ckpt, lr=2e-5, 50 epochs 默认, 在 epoch 9 提前停止); FID=59.02 ✅ + MSE=0.1083 ✅ (infer_steps=50, CELEBA-HQ) |
| bibaddiff | imagenette2✅ + v1-5-pruned.ckpt✅ + PL 2.x 不兼容已修复 (15 patches) + precision=32 + num_workers=4 + check_val_every_n_epoch=999 + every_n_train_steps=10000 | ✅ 训练完成 + ckpt→diffusers ✅ + 评估 5/5 完成 (MSE=0.2612✅, CLIP_p=17.778✅, CLIP_c=12.24✅, FID=489.38⚠, LPIPS=0.7567⚠) |
| villandiffusion_cond | vae 未赋值 ✅ + **CelebA-Dialog_HQ 仅 Google Drive**（被代理拦截） | ⛔ 需用户通过 VPN 下载 |

## 统计

- 攻击训练: 15/16 有模型产物；VillanDiffusion benchmark 版本 BOX_14/psi=1 已完成，villandiffusion_cond 因 CelebA-Dialog_HQ 缺数据阻塞。
- 攻击评估: 旧结果需逐项复核；当前 baddiffusion MSE=0.01862、BadDiffusion 10K FID=18.1288、TrojDiff MSE=0.07167、TrojDiff 10K FID=19.5955、VillanDiffusion MSE=0.03870、VillanDiffusion 10K FID=13.6067、InviBackdoor FID=52.1057 已基本对齐。
- 防御: 旧结果需逐项复核；TERD input trojdiff 的 reverse_trojdiff 采样覆盖 bug 已修复，待 BOX_14 训练后按 GPU 空闲情况重跑。
- **下一步**: 低频监控 InviBackdoor MSE 1000张正式重评至最终 CSV 行；完成后继续 corrected T2I 10K FID。
- **总结**: 当前不能判定全部完成；完成标准仍是 16 个攻击变体与 5 个防御方法的指标均落入论文或 BackdoorDM benchmark 正常范围。
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
  11. bibaddiff FID caption_column→caption_colunm (BackdoorDM typo)
  12. invi_backdoor delta_target 尺寸不匹配 → crop dsl.target[:, :ts, :ts]
  13. invi_backdoor OOM → batch_256=8 + del+empty_cache after delta opt
  14. invi_backdoor NaN (梯度爆炸) → --learning_rate 2e-5 替代默认 0.0002 (learning_rate_256_scratch 值)
  15. TERD model trojdiff OOM → batch_size 16→4 + DDIM seq num_train_timesteps(1000)→infer_steps(10) (reverse_trojdiff generalized_steps 序列长度)
  16. uncond fix 评估脚本缺少 CIFAR10 参数 → run_eval_fix_FID/MSE 对 baddiffusion/trojdiff/villandiffusion 显式传 `--val_data CIFAR10 --model_ver DDPM-CIFAR10-32`
  17. T2I FID 脚本注释要求 1w images 但未传参数 → run_eval_t2i_FID.sh 显式传 `--img_num_FID 10000`
  18. FID original-image cache 未区分数据集 → evaluation/clean/FID.py 的缓存目录加入 dataset tag
  19. uncond eval 覆盖 `--bd_config` → base_args_uncond_v2 仅在 CLI 未传参时使用默认 bd_config
  20. uncond 1000 张 FID 协议偏高 → clean ddpm 1000张 FID=58.91; run_eval_fix_FID.sh 改为 `--img_num_FID 10000`
  21. VillanDiffusion eval 脚本默认旧 checkpoint → run_eval_fix_FID/MSE 的 VillanDiffusion 命令改为 BOX_14/psi=1 路径并显式传 `bd_config_villan_box14.yaml`
  22. uncond eval 脚本继承 batch=1 默认值 → run_eval_fix_FID/MSE 对 CIFAR10 uncond 方法显式传 `--eval_max_batch 128`
  23. VillanDiffusion 10K FID batch=128 显存不足 → 真实图缓存完成后重启为 `--eval_max_batch 1408`
  24. VillanDiffusion FID scheduler 路径已核对 → `DDPM-SCHED` 重建 fixed_small/clip_sample=false，与训练产物 scheduler 配置一致
  25. uncond MSE 脚本仍走旧内存重路径 → run_eval_fix_MSE.sh 改为调用 `/temp_script/run_uncond_mse_stream.py`
  26. T2I FID batch 只能走 YAML 默认值 → main_eval.py 新增 `--batch_size` CLI 覆盖，默认不改变现有行为
  27. VillanDiffusion 1000 张 FID 偏高 → 10K FID=13.6067，对齐 benchmark 13.50
  28. TrojDiff MSE 旧路径偏高 → stream helper 1000张 MSE=0.07167；batch=1000 被 cgroup OOM，batch=512 完成
  29. BadDiffusion 1000 张 FID 协议偏高 → 10K FID=18.1288，对齐 benchmark 18.21
  30. TrojDiff 1000 张 FID 协议偏高 → 10K FID=19.5955，对齐 benchmark 19.71
  31. InviBackdoor FID 基准误用原论文补充值 → 按 BackdoorDM benchmark 58.19 验收，重算 FID=52.1057
