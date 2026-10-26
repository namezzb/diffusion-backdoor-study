# BackdoorDM 实现 vs 原始论文 交叉对照报告

> 生成日期：2026-06-28
> 对照范围：5 种攻击方法（6 个代码文件），逐一与原始论文进行超参数/实验/实现差异比对

---

## 1. BadDiffusion

### 1.1 原始论文
- **标题**: How to Backdoor Diffusion Models?
- **作者**: Sheng-Yen Chou, Pin-Yu Chen, Tsung-Yi Ho (IBM Research)
- **发表**: CVPR 2023
- **arXiv**: 2212.05400
- **官方仓库**: https://github.com/IBM/BadDiffusion

### 1.2 实现路径
- 主脚本: `attack/uncond_gen/bad_diffusion/bad_diffusion.py`
- 损失函数: `attack/uncond_gen/bad_diffusion/loss.py`
- 后门配置: `attack/uncond_gen/configs/bd_config_fix.yaml`
- 基础配置: `attack/uncond_gen/configs/base_config.yaml`

### 1.3 超参数对比

| 超参数 | 论文原始值 | BackdoorDM 默认值 | 是否一致 |
|--------|-----------|-------------------|---------|
| 优化器 | Adam | Adam (via Accelerator) | 一致 |
| LR (CIFAR10/32px) | 2e-4 | 2e-4 | 一致 |
| LR (CelebA-HQ/256px) | 8e-5 | 8e-5 | 一致 |
| Batch (CIFAR10) | 128 | 128 (batch_32) | 一致 |
| Batch (CelebA-HQ) | 64 | 64 (batch_256) | 一致 |
| Epoch (fine-tune) | 50 | 50 | 一致 |
| Epoch (from-scratch) | 400 | 不支持 | **缺失** |
| Poison rate | 5%-50% (多种) | 0.7 (固定) | **差异** |
| Trigger | Grey Box 14x14, Stop Sign 等 | GLASSES | **差异** |
| Target | Hat, Shoe, Corner 等 | CAT | **差异** |
| Clean rate | 未明确 | 1.0 | - |
| Seed | 未指定 | 35 | - |
| LR warmup steps | 未提及 | 500 | - |
| Gradient clipping | 未提及 | 1.0 | - |
| 噪声调度器 | DDPM (1000步) | DDPM-SCHED | 一致 |

### 1.4 损失函数对比

**论文**: 修改前向扩散过程，引入触发信号 R 到噪声图像中：
- `x_noisy = sqrt(alpha_bar_t) * x_start + (1 - sqrt(alpha_bar_t)) * R + sqrt(1 - alpha_bar_t) * noise`
- 预测目标修改为 `R_coef_t * R + noise`，其中 `R_coef_t = (1 - sqrt(alpha_t)) * sqrt(1 - alpha_bar_t) / (1 - alpha_t)`

**BackdoorDM**: `loss.py` 中 `p_losses_diffuser` 函数完全复现了上述公式。`q_sample_diffuser` 使用 `noise_sched.add_noise` 得到标准噪声图像后加上 `(1 - sqrt_alphas_cumprod_t) * R`。预测目标为 `R_coef_t * R + noise`。**损失函数实现与论文一致。**

### 1.5 实现差异

1. **训练框架差异**: 论文使用标准 PyTorch 训练循环，BackdoorDM 使用 HuggingFace Accelerator，支持多 GPU/混合精度/梯度累积
2. **Poison rate 固定偏高**: 论文系统测试 5%-50% 多种 poison rate，BackdoorDM 默认固定 0.7（70%），远高于论文推荐的 5%-20%
3. **触发/目标模式替换**: 论文使用 Grey Box (14x14)、Stop Sign 等触发器搭配 Hat/Shoe/Corner 等目标，BackdoorDM 替换为 GLASSES→CAT
4. **不支持从零训练**: 论文的 training-from-scratch (400 epoch) 实验在 BackdoorDM 中没有专门支持

### 1.6 缺失实验

| 论文实验 | BackdoorDM 是否覆盖 |
|---------|-------------------|
| 多 poison rate 对比 (5%/10%/20%/50%) | 未覆盖，固定 0.7 |
| Fine-tune vs From-scratch 对比 | 未覆盖，仅 fine-tune |
| 多触发器大小消融 (4x4 到 18x18) | 未覆盖 |
| ANP (Adversarial Neuron Pruning) 防御 | 单独模块 |
| Inference-time clipping 防御 | 未覆盖 |
| 多 trigger-target pair 组合 | 仅 GLASSES→CAT |

### 1.7 风险项

- **Poison rate 0.7 过高**: 论文指出 5% 即可有效，0.7 会使对比实验失去参考意义
- **触发器视觉差异大**: GLASSES 触发器面积远大于论文的 Grey Box 14x14，可能影响 ASR 和 FID 的可比性
- **评估指标缺失**: 代码中未发现 MSE(target reconstruction)、FID 等论文核心评估逻辑

---

## 2. TrojDiff

### 2.1 原始论文
- **标题**: TrojDiff: Trojan Attacks on Diffusion Models with Diverse Targets
- **作者**: Weixin Chen, Dawn Song, Bo Li
- **发表**: CVPR 2023
- **arXiv**: 2303.05762
- **官方仓库**: https://github.com/chenweixin107/TrojDiff

### 2.2 实现路径
- 主脚本: `attack/uncond_gen/trojdiff/trojdiff.py`
- 损失函数: `attack/uncond_gen/trojdiff/loss.py`
- 后门配置: `attack/uncond_gen/configs/bd_config_fix.yaml`

### 2.3 超参数对比

| 超参数 | 论文原始值 | BackdoorDM 默认值 | 是否一致 |
|--------|-----------|-------------------|---------|
| 攻击模式 | In-D2D, Out-D2D, D2I | 全部支持 (train_loop, train_loop_out, train_loop_d2i) | 一致 |
| gamma (混合系数) | 0.6 | 0.6 | 一致 |
| 触发类型 | blend, patch | blend (默认), patch 支持 | 一致 |
| cond_prob | 未明确 | 1.0 | - |
| target_label (In-D2D) | 类别标签 | 7 | - |
| miu_path (触发图像) | 各种图案 | hello_kitty.png | - |
| patch_size | 3 | 3 | 一致 |
| D2I target batch ratio | 未明确 | 10% (`int(bs * 0.1)`) | - |
| Antithetic sampling | 是 | 是 | 一致 |
| 噪声调度器 | DDPM | DDPM-SCHED | 一致 |

### 2.4 损失函数对比

**论文**: 使用偏置高斯分布(biased Gaussian) `q_trojan(x_t|x_0) = N(sqrt(alpha_bar_t)*x_0 + sqrt(1-alpha_bar_t)*gamma*mu, (1-alpha_bar_t)*I)`

**BackdoorDM `trojdiff_loss`**:
- 正常前向: `x = x0 * sqrt(alpha_bar_t) + noise * sqrt(1-alpha_bar_t)`
- 后门前向: `x_ = x0 * sqrt(alpha_bar_t) + noise * sqrt(1-alpha_bar_t) * gamma + miu * sqrt(1-alpha_bar_t)`
- 仅对目标类别样本注入后门
- 使用 `(noise - output).square().sum(dim=(1,2,3)).mean()` 作为损失

**实现与论文基本一致**，但 BackdoorDM 的 blend 模式公式略有差异：论文中 gamma 直接乘以噪声项的标准差部分，而代码中 `noise * sqrt(1-alpha_bar_t) * gamma` 等效于缩放噪声后加入 miu。patch 模式仅替换右下角 patch_size x patch_size 区域。

**`trojdiff_loss_out` (Out-D2D)**: 与 In-D2D 不同，直接替换目标类别样本的噪声图像（而非追加），使用 `y == 1000` 作为 OOD 标记。

### 2.5 实现差异

1. **Antithetic timestep sampling**: 论文强调反义采样提高训练效率。BackdoorDM 在 `train_loop` 中实现了 `ts = torch.cat([ts, 999 - ts], dim=0)` 的反义采样，与论文一致
2. **D2I 模式简化**: D2I 攻击中，BackdoorDM 使用固定 10% 的 batch 作为目标样本 (`target_bs = int(bs * 0.1)`)，论文中此比例可能不同
3. **训练框架**: BackdoorDM 使用 HuggingFace Accelerator
4. **Out-D2D 的 OOD 标记**: 代码使用 `y == 1000` 作为 OOD 样本标记，是 BackdoorDM 的自定义约定

### 2.6 缺失实验

| 论文实验 | BackdoorDM 是否覆盖 |
|---------|-------------------|
| CIFAR-10 In-D2D 全类别测试 | 仅默认 target_label=7 |
| Out-D2D 多目标分布测试 | 配置中可设置 |
| D2I 多目标图像测试 | 仅 hello_kitty 和 cat |
| FID/IS 评估 | 未在攻击代码中 |
| 后门去除实验 | 未覆盖 |

### 2.7 风险项

- **D2I target batch ratio 硬编码**: 10% 的比例无法通过配置修改
- **损失函数使用 sum 而非 mean**: `trojdiff_loss` 使用 `.square().sum(dim=(1,2,3)).mean(dim=0)` 而非标准 MSE，可能导致梯度量级差异
- **cond_prob=1.0**: 默认 100% 条件概率意味着所有目标类样本都会被注入后门，可能不符合论文某些实验设定

---

## 3. VillanDiffusion (Unconditional)

### 3.1 原始论文
- **标题**: VillanDiffusion: A Unified Backdoor Attack Framework for Diffusion Models
- **作者**: Sheng-Yen Chou, Pin-Yu Chen, Tsung-Yi Ho (IBM Research)
- **发表**: NeurIPS 2023
- **arXiv**: 2306.06874
- **官方仓库**: https://github.com/IBM/villandiffusion

### 3.2 实现路径
- 主脚本: `attack/uncond_gen/villan_diffusion/villan_diffusion.py`
- 损失函数: `attack/uncond_gen/villan_diffusion/loss.py` (极长，~1237 行)
- 后门配置: `attack/uncond_gen/configs/bd_config_fix.yaml`

### 3.3 超参数对比

| 超参数 | 论文原始值 | BackdoorDM 默认值 | 是否一致 |
|--------|-----------|-------------------|---------|
| psi (后门调度器类型) | [0, 1] 范围 | 0（命令行默认） | **注意**: 论文中 psi=1 对应 BadDiffusion 风格，psi=0 对应 TrojDiff 风格 |
| solver_type | sde, ode | sde | 一致 |
| sde_type | SDE-VP, SDE-VE, SDE-LDM | SDE-VP (config默认) | 一致 |
| ve_scale | 1.0 | 1.0 | 一致 |
| vp_scale | 1.0 | 1.0 | 一致 |
| LR (32px) | 2e-4 | 2e-4 | 一致 |
| LR (256px) | 未明确指定 | **6e-5** | **差异**: BadDiffusion 用 8e-5，这里用 6e-5 |
| Batch (32px) | 128 | 128 | 一致 |
| Batch (256px) | 64 | 64 | 一致 |
| Epoch | 50 | 50 | 一致 |
| Poison rate | 多种 | 0.7 | 同 BadDiffusion |
| 触发器 | 多种 | GLASSES | 同 BadDiffusion |
| 目标 | 多种 | CAT | 同 BadDiffusion |
| 混合精度 | 未明确 | VP/LDM=fp16, VE=none | - |

### 3.4 损失函数对比

**论文**: VillanDiffusion 的核心贡献是统一 backdoor 调度器，通过 psi 参数在 BadDiffusion 风格 (psi=1) 和 TrojDiff 风格 (psi=0) 之间插值。

**BackdoorDM `LossFn` 类** (loss.py):
- 实现了完整的 VP/VE/LDM 三种 SDE 类型支持
- `get_R_coef_gen_vp`: 实现 VP 模式下 psi 插值的 R 系数计算
- `get_R_coef_gen_ve` / `get_R_coef_gen_ve_reduce`: VE 模式的 R 系数
- 支持 `get_hs_vp`, `get_ws_ve`, `get_hs_ve` 等辅助函数
- `p_loss` 方法根据 sde_type 选择不同的前向过程和模型输入

**实现非常完整**，是所有方法中最忠实于原始论文的实现。loss.py 超过 1200 行，包含了论文公式推导的完整数值计算。

### 3.5 实现差异

1. **LR 差异 (256px)**: BadDiffusion 用 8e-5，VillanDiffusion 用 6e-5。这来自 `DEFAULT_LEARNING_RATE_256 = 6e-5`，是有意为之还是 typo 不确定
2. **命令行默认 psi=0**: 虽然命令行默认 psi=0（TrojDiff 风格），但配置文件可覆盖。需注意 psi=0 在 VE 模式下会抛出 `NotImplementedError`
3. **noise clamp**: 原始 `p_losses_diffuser` 函数中有 `noise = noise.clamp(-2, 2)` 的截断操作，`LossFn` 类中注释掉了 (`# noise = noise.clamp(-LossFn.RANDN_BOUND, LossFn.RANDN_BOUND)`)，可能影响训练稳定性
4. **调试打印语句**: loss.py 中多处保留了 `print(f"x_noisy: ...")` 等调试语句，影响运行效率

### 3.6 缺失实验

| 论文实验 | BackdoorDM 是否覆盖 |
|---------|-------------------|
| 多采样器评估 (DDPM, DDIM, DPM-Solver 等) | 配置支持，但未自动化 |
| psi 参数消融 | 未自动化 |
| SDE-VE 模型实验 | 代码支持，但 VE+psi≠0 会报错 |
| SDE-LDM (latent space) 实验 | 代码支持 VAE |
| Caption-based 条件攻击 | 见 VillanDiffusion-Cond |

### 3.7 风险项

- **调试打印未清理**: `p_losses_diffuser` 和 `LossFn.p_loss` 中大量 print 语句会严重拖慢训练
- **VE + psi!=0 不兼容**: `get_R_coef_gen_ve` 在 `psi != 0` 时会抛出异常
- **256px LR 与 BadDiffusion 不一致**: 6e-5 vs 8e-5 可能导致同一数据集上训练收敛行为不同
- **`get_R_coef_elbo_gen` 使用函数属性缓存**: 静态变量 `hs_vp`, `ws_ve`, `hs_ve` 在多次调用间共享，若切换模型配置而不重置会出问题

---

## 4. VillanDiffusion (Conditional / T2I)

### 4.1 原始论文
- 同上：arXiv 2306.06874，但论文第 5 节扩展到 caption-based 条件生成

### 4.2 实现路径
- 主脚本: `attack/t2i_gen/villan_diffusion_cond/villan_cond.py`
- 损失函数: `attack/t2i_gen/villan_diffusion_cond/loss_conditional.py`
- 后门配置: `attack/t2i_gen/configs/bd_config_fix.yaml`

### 4.3 超参数对比

| 超参数 | 论文描述 | BackdoorDM 默认值 | 是否一致 |
|--------|---------|-------------------|---------|
| 基础模型 | Stable Diffusion v1.5 | runwayml/stable-diffusion-v1-5 | 一致 |
| 训练方式 | DreamBooth + LoRA | DreamBooth-style + LoRA (rank=4) | 一致 |
| LoRA rank | 未指定 | 4 | - |
| max_train_steps | 未指定 | 50000 | - |
| checkpoint_every | 未指定 | 5000 | - |
| LR | 未指定 | 1e-4 | - |
| LR scheduler | 未指定 | cosine | - |
| Warmup steps | 未指定 | 500 | - |
| 触发器类型 | Caption trigger | caption_trigger='TRIGGER_MIGNNEKO' | 一致 |
| 图像触发器 | 可选 | image_trigger='NONE' | 仅文本触发 |
| 目标 | 多种 | CAT | - |
| Mixed precision | 未指定 | fp16 | - |
| Gradient checkpointing | 未指定 | True | - |
| scaling_factor | 0.18215 (SD 标准) | 0.18215 | 一致 |
| psi | 论文中 caption 攻击核心参数 | 通过 config 传入 | 一致 |

### 4.4 损失函数对比

**BackdoorDM `CondLossFn` 类** (loss_conditional.py):
- 继承了无条件版本的 R 系数计算逻辑
- `get_R_step_baddiff` / `get_R_coef_baddiff`: 与无条件版本公式一致
- `get_x_noisy`: 在标准 `q_sample` 结果上加入 `R * R_step`
- `get_target_eps`: 返回 `noise + R * R_coef`
- solver_type 默认 'ode'（与无条件版本的 'sde' 不同）

**实现合理**，将 VillanDiffusion 的后门调度器扩展到 LDM/Stable Diffusion 的 latent space 中。

### 4.5 实现差异

1. **LoRA rank=4**: 论文未指定 LoRA 超参数，BackdoorDM 使用较低的 rank=4
2. **仅支持 caption trigger**: 虽然代码有 `image_trigger` 参数，默认设为 'NONE'，仅使用文本触发
3. **solver_type 默认 'ode'**: 与无条件版本的 'sde' 默认值不同
4. **Caption augmentation**: 支持 caption 增强但默认未启用
5. **Prior preservation**: 支持 prior preservation loss 但需额外配置

### 4.6 缺失实验

| 论文实验 | BackdoorDM 是否覆盖 |
|---------|-------------------|
| 多 caption trigger 对比 | 仅 TRIGGER_MIGNNEKO |
| 图像+文本联合触发 | 代码支持但未默认 |
| 多采样器评估 | 未自动化 |
| CLIP score 评估 | 未在攻击代码中 |
| 多数据集 (Pokemon, Imagenette 等) | 需要配置 |

### 4.7 风险项

- **LoRA rank 偏低**: rank=4 可能限制后门注入容量，论文可能使用更高 rank
- **训练步数 50000**: 未与论文明确对比，可能过多或过少
- **solver_type 'ode' vs 'sde'**: 影响 R 系数计算（ODE 模式系数翻倍），选择不同会导致后门效果差异

---

## 5. InviBackdoor (Invisible Backdoor)

### 5.1 原始论文
- **标题**: Invisible Backdoor Attacks on Diffusion Models
- **作者**: Sen Li, Junchi Ma, Minhao Cheng
- **发表**: 2024
- **arXiv**: 2406.00816
- **官方仓库**: https://github.com/invisibleTriggerDiffusion/invisible_triggers_for_diffusion

### 5.2 实现路径
- 主脚本: `attack/uncond_gen/invi_backdoor/invi_backdoor.py`
- 损失函数: `attack/uncond_gen/invi_backdoor/loss.py`
- 后门配置: `attack/uncond_gen/configs/bd_config_fix.yaml`

### 5.3 超参数对比

| 超参数 | 论文描述 | BackdoorDM 默认值 | 是否一致 |
|--------|---------|-------------------|---------|
| 触发器优化方式 | 内循环优化，L-infinity 约束 | 内循环 + sign gradient + Adam + L-inf clamp | 基本一致 |
| max_norm (L-inf 约束) | 论文未具体指定 | 0.2 | - |
| inner_iterations | 论文未具体指定 | 1 | - |
| noise_timesteps (内循环去噪步数) | 论文未具体指定 | 10 | - |
| trigger_size (内循环 batch) | 论文未具体指定 | 32 | - |
| trigger_lr | 论文未具体指定 | 1e-3 | - |
| trigger_lr_scheduler | 论文未具体指定 | StepLR(step=200, gamma=0.5) | - |
| Poison rate | 论文测试多种 | 0.1 | - |
| 触发器 | 论文优化得到不可见触发 | INVI (代码标记) | 一致 |
| 目标 | 多种 | HAT | - |
| LR (32px) | 2e-4 | 2e-4 | 一致 |
| LR (256px) | 8e-5 | 8e-5 | 一致 |
| Epoch | 论文未指定 | 50 | - |
| 外循环损失 | BadDiffusion 风格 | `p_losses_diffuser` | 一致 |

### 5.4 损失函数对比

**论文核心**: 双层优化 —— 内循环优化触发器 delta 使去噪结果逼近目标图像，外循环用 BadDiffusion 风格损失训练模型。

**BackdoorDM 实现**:
- **内循环 (trigger optimization)**:
  ```python
  # 1. 生成噪声 + delta
  poison_delta = delta_noise + delta
  # 2. 用当前模型去噪 (10步)
  for i in noise_sched.timesteps:
      delta_output = model(poison_delta, ...)
      poison_delta = noise_sched.step(...)
  # 3. 与目标图像计算 MSE
  delta_loss = MSELoss(poison_delta, delta_target)
  # 4. sign gradient + L-inf clamp
  delta.grad = delta.grad.sign()
  trigger_optim.step()
  delta.data.clamp_(-max_norm, max_norm)
  ```
- **外循环**: 使用 BadDiffusion 的 `p_losses_diffuser`，但使用了**自定义的 R_coef 公式**

**InviBackdoor 的 loss.py 中的 R_coef 与 BadDiffusion 不同**:
- BadDiffusion: `R_coef_t = (1 - sqrt(alpha_t)) * sqrt(1-alpha_bar_t) / (1-alpha_t)`
- InviBackdoor: `R_coef_t = (sqrt(alpha_bar_{t-1}) - sqrt(alpha_bar_t)) / (sqrt(alpha_bar_{t-1}) * sqrt(1-alpha_bar_t) - sqrt(alpha_bar_t) * sqrt(1-alpha_bar_{t-1}))`

这是一个**关键差异**，InviBackdoor 使用了基于相邻时间步的 alpha_bar 比值来计算 R 系数。

### 5.5 实现差异

1. **R_coef 公式不同于 BadDiffusion**: InviBackdoor 使用了不同的数学推导来计算触发信号在噪声预测目标中的系数，涉及 `alpha_bar_{t-1}` 项
2. **触发器 delta 直接加到带后门标签的样本上**: `clean_images[backdoor_label == False] += delta.detach().clone()`
3. **触发器保存**: 训练结束后保存为 `invi.npy`
4. **模型未使用 accumulate context**: 与 BadDiffusion/VillanDiffusion 不同，InviBackdoor 的外循环没有使用 `accelerator.accumulate(model)` 上下文管理器
5. **内循环使用全模型推理**: 每个 training step 的内循环需要 10 步模型推理来优化触发器，训练开销显著高于其他方法

### 5.6 缺失实验

| 论文实验 | BackdoorDM 是否覆盖 |
|---------|-------------------|
| 条件 DM 攻击 (text-guided editing, inpainting) | 未覆盖 |
| 模型水印应用 | 未覆盖 |
| 多采样器鲁棒性测试 | 未覆盖 |
| 触发器不可见性评估 (PSNR, SSIM, LPIPS) | 未覆盖 |
| 多 max_norm 消融 | 未覆盖 |

### 5.7 风险项

- **R_coef 公式差异**: 与 BadDiffusion 使用不同的 R 系数公式，需要确认是论文原始设计还是实现偏差
- **无 `accelerator.accumulate`**: 可能导致多 GPU 训练时梯度计算不正确
- **训练效率低**: 每步 10 次模型推理用于内循环，大幅增加训练时间
- **内循环 batch size = trigger_size (32)**: 触发器优化的 batch 固定为 32，与外循环 batch 不一致

---

## 6. BiBadDiff

### 6.1 原始论文
- **标题**: From Trojan Horses to Castle Walls: Unveiling Bilateral Data Poisoning Effects in Diffusion Models
- **作者**: Zhuoshi Pan, Yuguang Yao, Gaowen Liu, Bingquan Shen, H. Vicky Zhao, Ramana Rao Kompella, Sijia Liu
- **发表**: NeurIPS 2024
- **arXiv**: 2311.02373
- **官方仓库**: https://github.com/OPTML-Group/BiBadDiff

### 6.2 实现路径
- 主脚本: `attack/t2i_gen/bibaddiff/main.py`
- 配置文件: `attack/t2i_gen/bibaddiff/configs/stable-diffusion/backdoor/imagenette/` 下多个 YAML
- 模型模块: `attack/t2i_gen/bibaddiff/ldm/` (完整 LDM 代码库)

### 6.3 超参数对比

| 超参数 | 论文描述 | BackdoorDM 默认值 | 是否一致 |
|--------|---------|-------------------|---------|
| 基础模型 | Stable Diffusion (LDM) | LDM (latent-diffusion) | 一致 |
| 训练框架 | PyTorch Lightning | PyTorch Lightning | 一致 |
| base_lr | 论文未详细指定 | 1e-4 | - |
| batch_size | 论文未详细指定 | 4 | - |
| image_size | 512 | 512 | 一致 |
| scale_lr | 论文未详细指定 | True | - |
| linear_start | 0.00085 | 0.00085 | 一致 |
| linear_end | 0.012 | 0.012 | 一致 |
| timesteps | 1000 | 1000 | 一致 |
| scale_factor | 0.18215 | 0.18215 | 一致 |
| 触发器类型 | BadNets-like (blend, badnet) | blend, badnet | 一致 |
| poison_rate | 多种 (5%-50%) | 0.1 (配置文件路径) | **差异** |
| 目标类 | imagenette 类别 | pt6 (class index 6) | - |
| guidance_scale | 未指定 | 3.0 (blend config) | - |
| checkpoint_every | 未指定 | 5000-10000 步 | - |
| DDP | 多 GPU | 支持 | 一致 |

### 6.4 损失函数对比

**论文核心**: BiBadDiff 的关键创新是研究 BadNets-like 数据投毒在扩散模型上的"双边效应"。与 BadDiffusion/TrojDiff 不同，**BiBadDiff 不修改扩散过程**，仅污染训练数据。

**BackdoorDM 实现**: 
- 使用原始 LDM 代码库（CompVis/latent-diffusion fork），训练过程由 PyTorch Lightning 管理
- 数据污染在数据集层面完成（通过 `blend_pr0.1_pt6` / `badnet_pr0.1_pt6` 目录结构）
- 模型训练完全使用标准 LDM loss（不修改扩散过程），符合论文设计

### 6.5 实现差异

1. **完全不同的训练框架**: BiBadDiff 是唯一使用 PyTorch Lightning + OmegaConf YAML 配置的方法，其他方法使用 HuggingFace Accelerator
2. **LDM 代码库**: 使用完整的 CompVis/latent-diffusion 代码库（含 `ldm/` 模块），而非 HuggingFace diffusers
3. **数据污染方式**: 通过预处理数据目录实现投毒（`blend_pr0.1_pt6` 文件夹），而非运行时动态注入
4. **配置驱动**: 所有超参数通过 YAML 文件管理，与其他方法的 argparse 风格完全不同
5. **仅支持 T2I**: BiBadDiff 仅适用于文本到图像的条件生成，不支持无条件生成

### 6.6 缺失实验

| 论文实验 | BackdoorDM 是否覆盖 |
|---------|-------------------|
| Trojan Horses 效应分析 (misalignment) | 需要后续评估脚本 |
| Trigger amplification 分析 | 需要后续评估脚本 |
| Castle Walls 防御效应 | 未覆盖 |
| 数据复制 (data replication) 关联分析 | 未覆盖 |
| 多 poison rate phase transition 实验 | 仅 0.1 |
| 扩散分类器实验 | 未覆盖 |

### 6.7 风险项

- **LDM 版本兼容性**: 使用旧版 CompVis LDM 代码，可能存在与新版 PyTorch/PyTorch Lightning 的兼容性问题
- **数据预处理依赖**: 需要预先生成投毒数据目录，无自动化投毒流程
- **batch_size=4**: 远小于其他方法 (128/64)，单 GPU 训练极慢
- **与其他方法代码结构完全不同**: 维护和对比实验的成本高

---

## 总结对比矩阵

| 维度 | BadDiffusion | TrojDiff | VillanDiff-UC | VillanDiff-Cond | InviBackdoor | BiBadDiff |
|------|-------------|----------|---------------|-----------------|--------------|-----------|
| 论文 | CVPR'23 | CVPR'23 | NeurIPS'23 | NeurIPS'23 | 2024 | NeurIPS'24 |
| 训练框架 | Accelerator | Accelerator | Accelerator | Accelerator | Accelerator | PL+DDP |
| 损失函数忠实度 | 高 | 高 | 非常高 | 高 | 中(R_coef不同) | 高 |
| 超参数匹配度 | 中(poison rate偏高) | 高 | 高(LR 256有差异) | 中(论文细节少) | 中(论文细节少) | 中 |
| 实验覆盖度 | 低 | 中 | 中 | 低 | 低 | 低 |
| 代码质量 | 中 | 中 | 中(大量调试print) | 高 | 中(无accumulate) | 中(旧版LDM) |
| 配置灵活性 | 中 | 中 | 高 | 高 | 中 | 高(YAML) |

### 全局风险汇总

1. **Poison rate 统一性问题**: BadDiffusion 和 VillanDiffusion 默认 0.7 (70%)，远高于论文推荐值(5-20%)，会导致评估结果不可比
2. **触发器/目标不统一**: 各方法使用不同的 trigger-target pair，跨方法对比时需统一
3. **评估代码缺失**: 攻击代码中不包含 FID/IS/MSE/ASR 等评估逻辑，需要额外的评估模块
4. **调试代码残留**: VillanDiffusion 的 loss.py 中大量 print 语句影响训练效率
5. **InviBackdoor 无 gradient accumulation**: 可能导致多 GPU 训练异常
6. **BiBadDiff 与其他方法异构**: 使用完全不同的代码库和训练框架，增加维护成本
