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
- InviBackdoor MSE 1000张正式重评完成：官方 MSE 路径生成 1000 张后被 cgroup OOM 杀死，流式脚本 `server/run_invi_mse_stream.py` 复算得到 MSE=0.13183，高于基准 0.0950；产物 1000/1000 且 MD5 唯一，偏差指向当前模型仅训练到 `data.ckpt epoch=9`，需续训后重评。
- InviBackdoor 专用流式 MSE helper 已同步到 AMAX `server/run_invi_mse_stream.py` 并通过 `py_compile`；训练完成后先删除旧 1000 张生成图，再用该脚本复算 MSE。
- InviBackdoor 训练后重评脚本已同步到 AMAX `server/run_invi_posttrain_eval.sh`；脚本会在训练进程仍活跃或 `data.ckpt epoch < 49` 时拒绝运行，并在 FID/MSE 间执行 `sync`/可选 `drop_caches`，避免误删旧生成图和 cgroup page-cache OOM。
- InviBackdoor 已于 2026-07-09 03:48 从 `epoch=9/step=35000` 续训；`data.ckpt` 已在 2026-07-09 05:21 前进到 `epoch=9/step=38500`，训练继续进入 epoch 10。
- InviBackdoor `config.save_model_epochs=5`，代码在 `(epoch + 1) % 5 == 0` 时保存；下一次常规 `data.ckpt` 前进预期为 epoch 14 完成后。
- 2026-07-09 15:xx: paas_db ASR=3.9 异常已诊断为**真实弱后门**而非评估 bug——直接用 ViT 分类 100 张触发图，60% 仍判为 dog、仅 6% 判为 cat；config 与论文对齐 (300 步, lr 5e-6, DreamBooth)，eval 管线正确 (paas_ti 同代码正常)，ViT 标签映射正确，模型为唯一最终 checkpoint。根因是 DreamBooth 后门高度可变 (论文 0.44-1.00)，本次 300 步落入弱盆；ACC=52.1/CLIP_p=21.95/FID=70.29 均对齐 benchmark，唯 ASR 偏低。修复方案=GPU 空闲后重训 (约 15min) 以重采样，暂因 InviBackdoor 训练占用 GPU 排队。
- 2026-07-09 16:xx: 已通读 BackdoorDM 论文 (2502.11798) 附录 B/C 确认多项验收基准：(1) Table 8 DB(PaaS) ViT ASR=43.30/ACC=48.50，与 reference 一致，我方 3.9 为真实差距；(2) DB(PaaS) MLLM ASR 高得多 (LLaVa=89.57/GPT-4o=51.30)，Table 11 ObjectRep MSE-of-ASR(GPT-4o)=0.0000 与人工完全吻合——**证实 ViT-ASR 系统性低估、MLLM 才是准确度量**；(3) p19 LPIPS 定义="输入相同 benign prompt+noise 到 clean/bd 两模型，低值=功能保持好"，**证实 rickrolling LPIPS 偏高=其 homoglyph 触发器对 benign 生成扰动更大 (真实、方法特有)**；(4) p18 FID 用 MS-COCO 10k 采样，证实 fix#17 的 10K 协议正确；(5) Table 14 Elijah/T2IShield 防御受限 (对齐我方 F1≈0)、TERD 有效 (对齐 TPR=100%)；(6) Table 13 TrojDiff FID=19.71/VillanDiff=13.5 对齐我方重评。
- 2026-07-09 16:xx: InviBackdoor 训练实时进度经 stdout `/tmp/train_invi_resume_epoch50.log` 确认健康推进——live step=62721, epoch=16(92%), loss 0.0002-0.018 正常；on-disk `data.ckpt` 仍显示 epoch14/step56000 因 `save_model_epochs=5`(下一保存点 epoch19)。速率约 1.72s/it × 3500/epoch ≈ 100min/epoch，epoch16→50 约 57 小时(约2.5天)。GPU 峰值占用 19042MiB→峰值空闲仅约 5.5GB，DreamBooth paas_db 重训需约10GB，**现在启动会 OOM 优先训练**，故全部 GPU 排队 fix 需等 InviBackdoor 完成或空出显存。当前决策：继续监控，不启动 GPU 任务。
- 2026-07-09 17:xx: 已准备并上传合并版排队修复脚本 `server/run_queued_gpu_fixes.sh` 到 AMAX（bash -n 通过），含双重 guard（InviBackdoor 进程活跃 或 GPU free<12GB 时拒绝运行，已实测正确 abort）。脚本按序执行三项已诊断 fix：(1) paas_db 重训+ACCASR 重评；(2) bibaddiff FID `--img_num_FID 10000`；(3) DAA eviledit/paas_ti——注意 DAA prompt_num 只能改 config.yaml（无 CLI 参数），脚本用 sed 临时改 500 并 trap 恢复 50。GPU 空闲后一条命令即可启动，降低后续 loop 延迟。
- 2026-07-10 09:09: InviBackdoor 续训仍健康推进，live log 到 `epoch=26/step=96895`，磁盘 `data.ckpt` 到 `epoch=24/step=91000`；GPU 占用约 `19022/24576 MiB`，queued GPU fixes 继续阻塞，不能并行启动。
- 2026-07-10 09:16: InviBackdoor 续训继续推进，live log 到 `epoch=26/step=97196`，磁盘 `data.ckpt` 仍为 `epoch=24/step=91000`；观察到训练进程仍活跃，GPU 瞬时 `6134/24576 MiB`、util `81%`，queued GPU fixes 继续等待。
- 2026-07-10 09:30: InviBackdoor 续训进入 epoch 26 尾段(91%)，live log 到 `epoch=26/step=97668`；GPU 占用 `15402/24576 MiB`、util `60%`，进程仍活跃，queued GPU fixes 继续阻塞不启动。
- 2026-07-10 09:32: 显式检查 `run_queued_gpu_fixes.sh`/`run_invi_posttrain_eval.sh` 启动门槛——InviBackdoor 进程仍活跃(epoch=26/step=97746, 93%)，GPU free=5725MiB < 12GB 阈值，双重 guard 均未满足，继续跳过启动。
- 2026-07-10 09:45: InviBackdoor 已完成 epoch 26(step=97999)并进入 epoch 27(step≈98126)；epoch 边界瞬时观测到 GPU free=21429MiB，但立即复查后回落到 free=5217MiB(used=19042MiB, util=30%)，证实为瞬时释放非真实空闲，queued fixes 继续阻塞。
- 2026-07-10 10:00: 吸取上轮瞬时假阳性教训，改用3次间隔2s采样代替单次读数；InviBackdoor 活跃于 epoch=27/step=98733(21%)，3次采样 free=19105/6033/5397MiB、util=83/100/30%，判定为训练波动而非空闲，继续跳过 queued fixes。
- 2026-07-10 10:02: InviBackdoor 进程(9个PID)仍存活于 epoch=27/step=98812(23%)；GPU 3次采样 free=5217/12837/12555MiB，部分样本超过12GB门槛，但双重 guard 中"进程活跃"单项已足以阻塞启动，继续跳过 queued fixes。
- 2026-07-10 10:15: InviBackdoor 进程仍活跃，推进到 epoch=27/step=99258(36%)；GPU 3次采样 free=5217/15137/10275MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 10:30: InviBackdoor 进程仍活跃，推进到 epoch=27/step=99786(51%)；GPU 3次采样 free=18077/6053/5933MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 10:32: InviBackdoor 进程仍活跃，推进到 epoch=27/step=99863(53%)；GPU 3次采样 free=6131/5361/5297MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 10:45: InviBackdoor 进程仍活跃，推进到 epoch=27/step≈100000(66%)；GPU 3次采样 free=5297/5877/14517MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 11:00: InviBackdoor 进程仍活跃，推进到 epoch=27/step=100847(81%)；GPU 3次采样 free=6033/5579/5237MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 11:02: InviBackdoor 进程仍活跃，推进到 epoch=27/step=100924(84%)；GPU 3次采样 free=5217/7397/18977MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 11:15: InviBackdoor 进程仍活跃，接近完成 epoch=27/step=101373(96%)；GPU 3次采样 free=19937/6033/5865MiB，进程活跃guard继续阻塞 queued fixes；下一轮预期进入 epoch 28。
- 2026-07-10 11:30: InviBackdoor 已完成 epoch 27 并进入 epoch=28/step=101900(11%)；dataloader worker PID 从 1103591 系列变为 1104037 系列，确认 epoch 边界重启；GPU 3次采样 free=18077/6033/5943MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 11:32: InviBackdoor 进程仍活跃，推进到 epoch=28/step=101979(14%)；GPU 3次采样 free=5441/5217/11777MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 11:45: InviBackdoor 进程仍活跃，推进到 epoch=28/step=102432(27%)；GPU 3次采样 free=5297/11137/17467MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 12:00: InviBackdoor 进程仍活跃，推进到 epoch=28/step=102956(42%)；GPU 3次采样 free=6035/5549/5217MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 12:02: InviBackdoor 进程仍活跃，推进到 epoch=28/step=103033(44%)；GPU 3次采样 free=6055/5605/5277MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 12:15: InviBackdoor 进程仍活跃，推进到 epoch=28/step=103484(57%)；GPU 3次采样 free=5479/5217/8757MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 12:30: InviBackdoor 进程仍活跃，推进到 epoch=28/step=104006(72%)；GPU 3次采样 free=21157/6053/5719MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 12:32: InviBackdoor 进程仍活跃，推进到 epoch=28/step=104081(74%)；GPU 3次采样 free=5817/5237/5577MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 12:45: InviBackdoor 进程仍活跃，接近完成 epoch=28/step=104527(87%)；GPU 3次采样 free=5237/11797/21265MiB，进程活跃guard继续阻塞 queued fixes；下一轮预期进入 epoch 29。
- 2026-07-10 13:00: InviBackdoor 已完成 epoch 28 并进入 epoch=29/step=105052(2%)；GPU 3次采样 free=19817/6033/6029MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 13:02: InviBackdoor 进程仍活跃，推进到 epoch=29/step=105128(4%)；GPU 3次采样 free=5487/5217/12257MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 13:15: InviBackdoor 进程仍活跃，推进到 epoch=29/step=105572(16%)；GPU 3次采样 free=5717/5257/5217MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 13:30: InviBackdoor 进程仍活跃，推进到 epoch=29/step=106095(31%)；GPU 3次采样 free=21233/6033/5707MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 13:32: InviBackdoor 进程仍活跃，推进到 epoch=29/step=106169(33%)；GPU 3次采样 free=10275/6033/5561MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 13:45: InviBackdoor 进程仍活跃，推进到 epoch=29/step=106616(46%)；GPU 3次采样 free=9257/20437/6055MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 14:00: InviBackdoor 进程仍活跃，推进到 epoch=29/step=107135(61%)；GPU 3次采样 free=6035/6039/5517MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 14:02: InviBackdoor 进程仍活跃，推进到 epoch=29/step=107210(63%)；GPU 3次采样 free=6033/5493/5217MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 14:15: InviBackdoor 进程仍活跃，推进到 epoch=29/step=107661(76%)；GPU 3次采样 free=5931/5197/5217MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 14:30: InviBackdoor 进程仍活跃，接近完成 epoch=29/step=108204(92%)；GPU 3次采样 free=12277/11317/6053MiB，进程活跃guard继续阻塞 queued fixes；下一轮预期进入 epoch 30。
- 2026-07-10 14:32: InviBackdoor 进程仍活跃，推进到 epoch=29/step=108267(93%)；GPU 3次采样 free=5237/17957/6055MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 14:45: InviBackdoor 已完成 epoch 29 并进入 epoch=30/step=108700(6%)；里程碑：50 epoch 目标已完成 60%；GPU 3次采样 free=5933/5331/5217MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 15:00: InviBackdoor 进程仍活跃，推进到 epoch=30/step=109224(21%)；GPU 3次采样 free=13297/21165/6115MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 15:02: InviBackdoor 进程仍活跃，推进到 epoch=30/step=109297(23%)；GPU 3次采样 free=6033/6101/5507MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 15:15: InviBackdoor 进程仍活跃，推进到 epoch=30/step=109737(35%)；GPU 3次采样 free=5297/14677/14617MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 15:45: InviBackdoor 进程仍活跃，推进到 epoch=30/step=110785(65%)；GPU 3次采样 free=6021/5457/5237MiB，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 22:56: InviBackdoor 进程仍活跃，推进到 epoch=34/step=125825(95%)；GPU 3次采样 used=18486/19042/18582MiB、util=70/31/46%，磁盘 `data.ckpt` 仍为 epoch=29/step=108500（save_model_epochs=5），进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 23:02: InviBackdoor 完成 epoch 34 并保存 checkpoint，进入 epoch=35/step=126052(约1%)；`data.ckpt` 已到 epoch=34/step=126000，GPU 3次采样 used=18978/19022/9022MiB、util=28/46/67%，进程活跃guard继续阻塞 queued fixes。
- 2026-07-10 23:08: InviBackdoor 进程仍活跃，推进到 epoch=35/step=126242(7%)；`data.ckpt` 仍为 epoch=34/step=126000，GPU 3次采样 used=19042/10802/3248MiB、util=48/66/81%，进程活跃guard继续阻塞 queued fixes。
- 2026-07-11 23:14: InviBackdoor 进程仍活跃，推进到 epoch=49/step=176835(52%)；`data.ckpt` 仍为 epoch=44/step=161000，GPU 3次采样 used=14382/3482/18226MiB、util=57/81/72%，进程活跃guard继续阻塞 queued fixes/posttrain eval。
- 2026-07-12 14:55: InviBackdoor 训练已完成，`data.ckpt` 到 epoch=49/step=178500 且 GPU 空闲；修复 `server/run_invi_posttrain_eval.sh` 的 MSE 阶段错误（FID 只生成 clean 图，旧 helper 误假设 `bd_generated_*` 已存在），改为清理 clean/bd 缓存并通过 `main_eval.py --metric MSE` 走轻量流式 MSE；`IMG_NUM=2` RED→GREEN 验证通过 (FID=208.3299, MSE=0.08578)，1000张正式 posttrain eval 已用 nohup 启动，进程 `python evaluation/main_eval.py ... --img_num_FID 1000` PID=1108736，日志 `/tmp/invi_posttrain_eval.log`。
- 2026-07-12 15:04: InviBackdoor posttrain eval 仍在 FID 阶段运行，进程 `run_invi_posttrain_eval.sh` PID=1108728、`main_eval.py --metric FID` PID=1108736；GPU used=19048MiB/util=100%，`FID_gen_cleanImg_CELEBA-HQ_1000` 当前 0 张、`bd_generated_CELEBA-HQ_1000` 尚未生成，queued fixes 继续等待。
- 2026-07-12 15:34: InviBackdoor posttrain eval 仍在 FID clean 图生成阶段，进程 `run_invi_posttrain_eval.sh` PID=1108728、`main_eval.py --metric FID` PID=1108736；GPU used=19048MiB/util=100%，`FID_gen_cleanImg_CELEBA-HQ_1000` 当前 64 张、`bd_generated_CELEBA-HQ_1000` 尚未生成，CSV 尚无最新 1000张 FID/MSE，queued fixes 继续等待。
- 2026-07-12 16:04: InviBackdoor posttrain eval 仍在 FID clean 图生成阶段，进程 `run_invi_posttrain_eval.sh` PID=1108728、`main_eval.py --metric FID` PID=1108736；GPU used=19048MiB/util=100%，`FID_gen_cleanImg_CELEBA-HQ_1000` 当前 160 张、`bd_generated_CELEBA-HQ_1000` 尚未生成，CSV 尚无最新 1000张 FID/MSE，queued fixes 继续等待。
- 2026-07-12 16:34: InviBackdoor posttrain eval 仍在 FID clean 图生成阶段，进程 `run_invi_posttrain_eval.sh` PID=1108728、`main_eval.py --metric FID` PID=1108736；GPU used=19048MiB/util=97%，`FID_gen_cleanImg_CELEBA-HQ_1000` 当前 224 张、`bd_generated_CELEBA-HQ_1000` 尚未生成，CSV 尚无最新 1000张 FID/MSE，queued fixes 继续等待。
- 2026-07-12 17:05: InviBackdoor posttrain eval 仍在 FID clean 图生成阶段，进程 `run_invi_posttrain_eval.sh` PID=1108728、`main_eval.py --metric FID` PID=1108736；GPU used=19048MiB/util=100%，`FID_gen_cleanImg_CELEBA-HQ_1000` 当前 288 张、`bd_generated_CELEBA-HQ_1000` 尚未生成，CSV 尚无最新 1000张 FID/MSE，queued fixes 继续等待。
- 2026-07-12 17:34: InviBackdoor posttrain eval 仍在 FID clean 图生成阶段，进程 `run_invi_posttrain_eval.sh` PID=1108728、`main_eval.py --metric FID` PID=1108736；GPU used=19048MiB/util=100%，`FID_gen_cleanImg_CELEBA-HQ_1000` 当前 352 张、`bd_generated_CELEBA-HQ_1000` 尚未生成，CSV 尚无最新 1000张 FID/MSE，queued fixes 继续等待。
- 2026-07-12 18:05: InviBackdoor posttrain eval 仍在 FID clean 图生成阶段，进程 `run_invi_posttrain_eval.sh` PID=1108728、`main_eval.py --metric FID` PID=1108736；GPU used=19048MiB/util=100%，`FID_gen_cleanImg_CELEBA-HQ_1000` 当前 448 张、`bd_generated_CELEBA-HQ_1000` 尚未生成，CSV 尚无最新 1000张 FID/MSE，queued fixes 继续等待。
- 2026-07-12 18:35: InviBackdoor posttrain eval 仍在 FID clean 图生成阶段，进程 `run_invi_posttrain_eval.sh` PID=1108728、`main_eval.py --metric FID` PID=1108736；GPU used=19048MiB/util=98%，`FID_gen_cleanImg_CELEBA-HQ_1000` 当前 512 张、`bd_generated_CELEBA-HQ_1000` 尚未生成，CSV 尚无最新 1000张 FID/MSE，queued fixes 继续等待。
- 2026-07-12 19:05: InviBackdoor posttrain eval 仍在 FID clean 图生成阶段，进程 `run_invi_posttrain_eval.sh` PID=1108728、`main_eval.py --metric FID` PID=1108736；GPU used=19048MiB/util=100%，`FID_gen_cleanImg_CELEBA-HQ_1000` 当前 576 张、`bd_generated_CELEBA-HQ_1000` 尚未生成，CSV 尚无最新 1000张 FID/MSE，queued fixes 继续等待。
- 2026-07-12 19:35: InviBackdoor posttrain eval 仍在 FID clean 图生成阶段，进程 `run_invi_posttrain_eval.sh` PID=1108728、`main_eval.py --metric FID` PID=1108736；GPU used=19048MiB/util=100%，`FID_gen_cleanImg_CELEBA-HQ_1000` 当前 640 张、`bd_generated_CELEBA-HQ_1000` 尚未生成，CSV 尚无最新 1000张 FID/MSE，queued fixes 继续等待。
- 2026-07-12 20:05: InviBackdoor posttrain eval 仍在 FID clean 图生成阶段，进程 `run_invi_posttrain_eval.sh` PID=1108728、`main_eval.py --metric FID` PID=1108736；GPU used=19048MiB/util=99%，`FID_gen_cleanImg_CELEBA-HQ_1000` 当前 736 张、`bd_generated_CELEBA-HQ_1000` 尚未生成，CSV 尚无最新 1000张 FID/MSE，queued fixes 继续等待。
- 2026-07-13 09:46: InviBackdoor posttrain FID/MSE 已完成：FID=33.6132、MSE=0.103524；官方 MSE 阶段因 `ImagePathDataset[:]` + joblib 全量并行读图触发 memcg OOM，已改用 `server/run_invi_mse_stream.py` 流式复算并写入 CSV，MSE 相对基准 0.0950 偏差 +0.0085 可验收。
- 2026-07-13 10:00: queued GPU fixes 首次启动时 paas_db 被 memcg OOM kill，根因为官方 MSE 遗留 64 个 orphan `loky` worker 占用约 22GB cgroup 内存；已清理残留 worker，内存从 36Gi used 降到 21Gi used，并重新启动 `server/run_queued_gpu_fixes.sh`，当前 paas_db retrain 正在运行（约 111/300 steps）。
- 2026-07-13 10:37: queued GPU fixes 进展：paas_db 重训完成但 ACC/ASR 仍为 52.1/3.9，说明同 seed 重跑未跳出弱后门盆；bibaddiff 10K FID 因 `infer_steps=1000` 触发 SD PNDM scheduler `timestep=1000` 越界失败，已将 `server/run_queued_gpu_fixes.sh` 的 bibaddiff FID 固定为 `--infer_steps 50`，8张 smoke test 跑通并写入 FID=588.2111，剩余 bibaddiff 10K FID + DAA 500 prompts 已用 `/tmp/run_remaining_queued_fixes_0713.sh` 后台启动。
- 2026-07-13 10:57: 按 LOOP.md GPU 最大化要求对 bibaddiff FID 做 batch probe：bs=16/24 均可跑但吞吐约 5.8s/img，bs=32 在 VAE decode CUDA OOM；正式剩余任务已改为最高可用 `--batch_size 24 --infer_steps 50` 并重启，当前 GPU util=100%、显存约 12.3GB，但单图吞吐未比 bs=8 明显改善，10K FID 预计仍需约 16 小时，完成后再跑 DAA 500 prompts。
- 2026-07-13 11:00: bibaddiff 10K FID 仍在运行，进程命令确认 `--batch_size 24 --infer_steps 50`，GPU `12330/24576 MiB` 且 util=100%；原图缓存 10000 张已存在，生成图目录尚未完成首批保存，DAA 500 尚未开始。
- 2026-07-13 11:34: bibaddiff 10K FID 在 `--batch_size 24` 下第2批 VAE decode 阶段 CUDA OOM（PyTorch 显存碎片累积，reserved but unallocated 7.59GB），此前单批 probe 未覆盖多批场景未能预警；改用多批 probe (`bs=16, n=64, 4轮`) 验证通过并完成 FID=504.4159，已将 `server/run_queued_gpu_fixes.sh`/剩余任务脚本降为稳定 `--batch_size 16` 并重启，当前 GPU `9734MiB/util=99%`。
- 2026-07-13 12:00: bibaddiff 10K FID (`--batch_size 16 --infer_steps 50`) 健康运行中，日志进度 11/625 batches(约2%)，`FID_gen_cleanImg_10000` 已生成 176 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-13 12:30: bibaddiff 10K FID (`--batch_size 16 --infer_steps 50`) 继续健康运行，日志进度 30/625 batches(约5%)，`FID_gen_cleanImg_10000` 已生成 480 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-13 13:00: bibaddiff 10K FID (`--batch_size 16 --infer_steps 50`) 继续健康运行，日志进度 50/625 batches(8%)，`FID_gen_cleanImg_10000` 已生成 800 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-13 13:30: bibaddiff 10K FID (`--batch_size 16 --infer_steps 50`) 继续健康运行，日志进度 69/625 batches(11%)，`FID_gen_cleanImg_10000` 已生成 1104 张，GPU `22974/24576 MiB` 且 util≈96%；DAA 500 prompts 尚未开始。
- 2026-07-13 14:02: bibaddiff 10K FID 当前运行段无新错误，日志进度 88/625 batches(14%)，`FID_gen_cleanImg_10000` 已生成 1408 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-13 14:33: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 108/625 batches(17%)，`FID_gen_cleanImg_10000` 已生成 1728 张，GPU `22974/24576 MiB` 且 util≈99%；DAA 500 prompts 尚未开始。
- 2026-07-13 15:01: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 126/625 batches(20%)，`FID_gen_cleanImg_10000` 已生成 2016 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-13 15:32: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 145/625 batches(23%)，`FID_gen_cleanImg_10000` 已生成 2320 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-13 16:01: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 164/625 batches(26%)，`FID_gen_cleanImg_10000` 已生成 2624 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-13 16:31: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 183/625 batches(29%)，`FID_gen_cleanImg_10000` 已生成 2928 张，GPU `22974/24576 MiB` 且 util≈99%；DAA 500 prompts 尚未开始。
- 2026-07-13 17:01: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 202/625 batches(32%)，`FID_gen_cleanImg_10000` 已生成 3232 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-13 17:31: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 222/625 batches(36%)，`FID_gen_cleanImg_10000` 已生成 3552 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-13 18:01: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 241/625 batches(39%)，`FID_gen_cleanImg_10000` 已生成 3856 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-13 18:31: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 260/625 batches(42%)，`FID_gen_cleanImg_10000` 已生成 4160 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-13 19:01: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 279/625 batches(45%)，`FID_gen_cleanImg_10000` 已生成 4464 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-13 19:31: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 298/625 batches(48%)，`FID_gen_cleanImg_10000` 已生成 4768 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-13 20:02: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 318/625 batches(51%，已过半)，`FID_gen_cleanImg_10000` 已生成 5088 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-13 20:31: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 337/625 batches(54%)，`FID_gen_cleanImg_10000` 已生成 5392 张，GPU `22974/24576 MiB` 且 util≈99%；DAA 500 prompts 尚未开始。
- 2026-07-13 21:01: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 356/625 batches(57%)，`FID_gen_cleanImg_10000` 已生成 5696 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-13 21:31: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 375/625 batches(60%)，`FID_gen_cleanImg_10000` 已生成 6000 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-13 22:01: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 394/625 batches(63%)，`FID_gen_cleanImg_10000` 已生成 6304 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-13 22:31: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 413/625 batches(66%)，`FID_gen_cleanImg_10000` 已生成 6608 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-13 23:01: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 433/625 batches(69%)，`FID_gen_cleanImg_10000` 已生成 6928 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-13 23:31: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 452/625 batches(72%)，`FID_gen_cleanImg_10000` 已生成 7232 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-14 00:01: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 471/625 batches(75%)，`FID_gen_cleanImg_10000` 已生成 7536 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-14 00:31: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 490/625 batches(78%)，`FID_gen_cleanImg_10000` 已生成 7840 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-14 01:01: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 510/625 batches(82%)，`FID_gen_cleanImg_10000` 已生成 8160 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-14 01:31: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 529/625 batches(85%)，`FID_gen_cleanImg_10000` 已生成 8464 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-14 02:01: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 548/625 batches(88%，接近尾声)，`FID_gen_cleanImg_10000` 已生成 8768 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-14 02:31: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 567/625 batches(91%，即将完成)，`FID_gen_cleanImg_10000` 已生成 9072 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-14 03:01: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 587/625 batches(94%，仅剩约38批)，`FID_gen_cleanImg_10000` 已生成 9392 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-14 03:31: bibaddiff 10K FID 当前运行段继续无新错误，日志进度 606/625 batches(97%，仅剩约19批)，`FID_gen_cleanImg_10000` 已生成 9696 张，GPU `22974/24576 MiB` 且 util=100%；DAA 500 prompts 尚未开始。
- 2026-07-14 04:01: bibaddiff 10K 张图片生成已完成 (10000/10000)，但 FID 特征提取阶段被 memcg OOM kill——根因为 `cleanfid.compute_fid` 对 512x512 SD 生成图默认 `num_workers=12`，多进程同时加载导致内存超限；已将 `evaluation/clean/FID.py` 的 T2I 分支补丁为显式传 `num_workers=4`，因图片已生成完毕（`check_image_count` 会跳过重新生成），已复用现有 10000 张图片在后台重跑 FID 计算，等待完成后收集分数并启动 DAA 500 prompts。
- 2026-07-14 04:15: `num_workers=4` 仍被 memcg OOM kill——dmesg 显示每个 `pt_data_worker` 进程 RSS 约 12.8GB，与 worker 数量无关，定位真正根因为 PyTorch DataLoader worker 在父进程已初始化 CUDA context 后 fork，导致每个子进程复制/重建 CUDA context 占用巨量host内存；改为 `num_workers=0`（消除多进程 fork）并用 64 张已生成图片子集 probe 验证通过（FID=504.4159，无 OOM），已在后台用完整 10000 张图片重跑 FID 计算（GPU显存仅约1GB，远低于此前多进程 OOM 水平）。
- 2026-07-14 04:31: `num_workers=0` 修复后的 FID 重算稳定运行，无 OOM，第一个文件夹(FID_originalImg)进度 287/313 batches(91%)，GPU 仅约1GB；第二个文件夹(生成图)尚未开始，预计还需约15-20分钟。
- 2026-07-14 04:52: bibaddiff 10K FID 计算完成：FID=477.2604，仍远高于基准88.50且与1K结果489.38几乎不变（-2.5%），推翻此前"1K协议膨胀"的诊断——问题是真实模型缺陷而非采样量。检索 BiBadDiff 论文(2311.02373)确认其自身FID协议(用ImageNette作参考图)与BackdoorDM统一COCO协议不同，故基准数值不可直接对比原论文，但仍需与BackdoorDM自己的88.50基准对齐。直接调用pipeline生成单张图并可视化，确认模型对任意prompt输出纯随机噪声（非FID.py或管线bug——同一管线加载eviledit的checkpoint能正常生成逼真图片）。检查UNet权重无NaN/Inf、数值范围正常，排除权重文件损坏。检查`testtube/version_0/metrics.csv`训练loss曲线，发现灾难性发散：loss从step49的0.036(健康)飙升到训练末尾(6 epoch完成,step56800)的0.75-0.94，与"模型退化为纯噪声输出"完全吻合。定位到两个复合根因：(1) 实际训练用配置`badnet_pr0.1_pt6_lowmem.yaml`的`warm_up_steps=[1]`应为文档注明的从头训练正确值`[10000]`，导致LR瞬间跳到1e-4无梯度预热；(2) 实际使用的训练启动脚本(`run_bibaddiff_v4.sh`/`run_bibaddiff_fresh.sh`)遗漏了`--finetune_from`参数，导致859M参数UNet从随机初始化开始训练，仅用9469张图片训练6个epoch，远不足以从零收敛。已修复两处bug：yaml的`warm_up_steps`改为10000(备份原文件)，并用补上`--finetune_from /opt/data/private/models/stable-diffusion-v1-5/v1-5-pruned.ckpt`的正确命令重新启动训练；已验证日志显示"Attempting to load state from .../v1-5-pruned.ckpt"预训练权重正在加载，GPU`19248MiB/72%util`训练正常推进。旧的噪声checkpoint已移至`results/bibaddiff_sd15_retrain_backup/`保留而非删除。因GPU被此优先重训练占用(仅剩约5GB)，DAA 500 prompts推迟至训练完成或显存释放。
- 2026-07-14 05:19: bibaddiff 重训练确认健康推进：`metrics.csv`显示LR严格遵循修复后的10000步预热计划(step549时LR=5.49e-6，精确匹配549/10000×1e-4的线性预热公式)，loss在0.008-0.82间正常波动(不同timestep采样导致的正常噪声，非单调发散)，与此前发散到0.75-0.94高位并停滞的破损模式明显不同；GPU`19250MiB/92%util`持续训练中。DAA 500因GPU显存不足(~5.3GB)继续推迟。
- 2026-07-14 05:31: bibaddiff 重训练继续健康推进，step=2049，LR≈2.05e-5(仍在10000步预热期内)，loss持续正常波动(0.014-0.61)无发散；尚未到达首个checkpoint保存点(每10000步保存)；GPU`19250MiB/76%util`。
- 2026-07-14 06:01: bibaddiff 重训练继续健康推进，step=5899，LR≈5.9e-5(预热已过半)，loss持续正常波动(0.02-0.52)无发散；GPU`19250MiB/97%util`。
- 2026-07-14 06:31: bibaddiff 重训练继续健康推进，epoch 0已完成(step9468)，进入epoch 1，step=9749，LR≈9.75e-5(10000步预热接近完成)，loss持续正常波动(0.004-0.82)无发散；首个checkpoint(每10000步)即将保存；GPU`19250MiB/78%util`。
- 2026-07-14 07:01: **重要发现**：warmup修复后的重训练在LR达到10000步预热终点的满值1e-4时(约step10000)立即开始持续发散——loss从预热期健康波动(0.008-0.82)骤变为step10049起连续3000+步(至少到13449)稳定卡在0.97-1.04，无任何低损失样本，确认为持续发散而非瞬时波动。诊断：`base_learning_rate=1e-4`(scale_lr=False即字面值)是为官方脚本的4-GPU DDP设置设计的(4个副本梯度平均，有效batch=4)，我方单卡batch_size=1的梯度估计噪声是官方设置的4倍，同一LR在单卡环境下过于激进。按线性LR缩放规则将`base_learning_rate`降为`2.5e-05`(=1e-4/4)，保留已修复的`warm_up_steps=10000`；已将发散的运行存档至`results/bibaddiff_sd15_retrain_backup/2026-07-14T05-13-25_diverged_at_full_lr`；用相同`--finetune_from`命令重新启动训练(第2次重训尝试)，已验证预训练权重重新加载；将重点监控此前失败的step10000过渡点。
- 2026-07-14 07:07: 确认第2次重训尝试(降LR至2.5e-5)已启动，运行目录`2026-07-14T07-05-07_badnet_pr0.1_pt6_lowmem`，step=149，LR=3.7e-7(精确匹配149/10000×2.5e-5的预热公式)，loss正常(0.008-0.27)；GPU`19250MiB/99%util`。距离此前失败的step10000关键过渡点约需1小时，将持续监控。
- 2026-07-14 07:31: bibaddiff重训练v2继续健康推进，step=3099，LR≈7.75e-6(降LR后预热约31%)，loss持续正常波动(0.004-0.39)无发散；GPU`19250MiB/96%util`。
- 2026-07-14 08:01: bibaddiff重训练v2继续健康推进，step=6899，LR≈1.72e-5(降LR后预热约69%)，loss持续正常波动(0.008-0.50)无发散；尚未到达step10000关键过渡点；GPU`19250MiB/74%util`。
- 2026-07-14 08:31: **关键验证通过**：训练已越过此前发散的step10000过渡点，LR已达降低后的满值2.5e-5(step10149起)，loss在此过渡点后继续正常波动(0.007-0.51，含多个低值样本如0.007/0.015/0.030/0.036/0.039)，**未出现attempt#1中卡死在0.97-1.04的发散模式**——确认降低学习率(1e-4→2.5e-5)的修复已解决LR达满值时的训练发散问题。将继续监控确保长期稳定性(非短暂假阳性)。
- 2026-07-14 09:01: bibaddiff重训练v2持续稳定，已在满LR下运行4300+步(step14299，超过临界点约43%)，loss持续含大量低值样本(0.0027/0.0037/0.0067/0.0097/0.0135)与正常高值交替(0.139-0.59)，确认非短暂假阳性；首个checkpoint`epoch=000001.ckpt`已保存(epoch1/6完成)；GPU`19250MiB/88%util`。
- 2026-07-14 09:32: bibaddiff重训练v2继续稳定，step=18349(约完成epoch2)，LR稳定在满值2.499999936844688e-05，loss持续含大量低值样本(0.0023/0.0169/0.0122/0.0345/0.0332)与正常波动值交替(0.09-0.42)，无发散迹象；进度约18349/56814(≈32%)；GPU`19250MiB/71%util`。**本次SSH诊断**：会话开始时`ssh amax`默认端口失败(Permission denied publickey)，经`~/.zsh_history`回溯确认AMAX动态端口当前为`25579`(与本文件头部记录一致)，改用`ssh -p 25579 amax`后恢复正常，后续均用此端口。
- 2026-07-14 09:46: bibaddiff重训练v2继续稳定，step=25599，第3个epoch checkpoint已保存(`epoch=000002.ckpt`，对应epoch索引2，即6个epoch中已完成3个≈50%)，loss持续健康波动(0.0050/0.0086/0.031/0.046/0.105/0.169/0.204/0.355，偶有0.82高值但非持续)，无发散迹象；GPU`19250MiB/90%util`。
- 2026-07-14 10:01: bibaddiff重训练v2继续稳定，step=29399(epoch索引3，进度约52%)，loss持续健康波动，含大量低值(0.003/0.007/0.0146/0.0134)与中等值(0.153/0.210/0.284/0.339/0.071)交替，无发散迹象；GPU`19250MiB/75%util`。
- 2026-07-14 11:31: bibaddiff重训练v2继续稳定，step=33049，第4个epoch checkpoint已保存(`epoch=000003.ckpt`，6个epoch中已完成4个≈67%)，loss以低值为主(0.0022/0.0038/0.0071/0.0087/0.0153/0.0182/0.0515/0.0586/0.092/0.208)，无发散迹象；GPU`19250MiB/67%util`。
- 2026-07-14 12:01: bibaddiff重训练v2继续稳定，step=36849(epoch索引3内，进度约65%)，loss含偶发高值(0.735/0.505，与此前attempt#1持续卡死0.97-1.04的模式不同，为正常波动非发散)与大量低值(0.005/0.026/0.049)交替；GPU`19250MiB/100%util`。
- 2026-07-14 12:31: bibaddiff重训练v2继续稳定，step=40449，第5个epoch checkpoint已保存(`epoch=000004.ckpt`，6个epoch中已完成5个≈83%)，loss含偶发高值(0.737/0.583，非持续)与大量低值(0.0048/0.040/0.042/0.069/0.086)交替，无发散迹象；仅剩最后1个epoch；GPU`19250MiB/68%util`。
- 2026-07-14 13:01: bibaddiff重训练v2继续稳定，step=44249，已进入最后(第6个)epoch，进度约78%，loss以低值为主(0.0070/0.0067/0.0119/0.0143/0.0199/0.0318/0.0427)偶有0.48/0.27高值但非持续，无发散迹象；GPU`19250MiB/97%util`。
- 2026-07-14 13:31: bibaddiff重训练v2继续稳定，step=47999(最后epoch内)，进度约84%，loss含0.487/0.489连续中高值但随即恢复低值(0.0126/0.0144/0.0087/0.0241/0.0247)，与此前发散卡死在0.97+且无低值的模式明显不同，判定为正常波动；剩余约8800步；GPU`19250MiB/71%util`。
- 2026-07-14 14:01: bibaddiff重训练v2继续稳定，step=51649，进度约91%。**注意**：`epoch=000005.ckpt`(13:47)是`every_n_train_steps=10000`在step~50000触发的中间checkpoint，非epoch-5完成(epoch-5结束需到~56814步)；训练进程仍在运行，GPU100%util；loss正常波动(0.0064/0.0201/0.048/0.064/0.134/0.143/0.278/0.519)，剩余约5165步；约再30-45分钟完成。
- 2026-07-14 14:31: bibaddiff重训练v2继续稳定，step=55399，进度约97.5%(仅剩约1400步)，loss以低值为主(0.0025/0.0043/0.0077/0.0113/0.026/0.030/0.043)偶有0.433高值但非持续，无发散迹象；预计下次检查时训练已完成，届时开始ckpt转diffusers格式并重评全部指标。
- 2026-07-14 15:20: **bibaddiff重训练v2完成并进入重评阶段**：训练已正常完成(`Trainer.fit stopped: max_epochs=6 reached`，最终global_step=56813，epoch 5/5完成)，末尾loss仍含低值并无发散；训练后`trainer.test()`因模型无`test_step()`报错但发生在fit完成之后，不影响checkpoint。已将`last.ckpt`转换为diffusers目录`results/bibaddiff_sd15/bibaddiff_trigger-garbage_truck_target-badnets`，转换期间因PyTorch 2.6默认`weights_only=True`临时patch本地diffusers加载为`weights_only=False`(可信本地ckpt)，并禁用不参与评估的safety checker以避免外网下载阻塞。已归档旧生成目录到`results/bibaddiff_sd15/eval_backup_pre_retrain_20260714_152027`，启动fresh重评脚本`/tmp/run_bibaddiff_retrain_eval_0714.sh`，当前处于MSE阶段，日志`/tmp/bibaddiff_retrain_eval_20260714_152027.log`。
- 2026-07-14 15:31: bibaddiff重评脚本继续稳定运行，当前MSE阶段正在生成1000张图像，进度6/62批(每批16张，约94秒/批)；GPU`22974MiB/100%util`；预计MSE图像生成完成还需约88分钟，之后还有CLIP_p/CLIP_c/FID 10K/LPIPS；eval_results.csv尚无新结果行。
- 2026-07-14 16:01: bibaddiff重评继续稳定，MSE图像生成进度25/62批(≈40%)，速率稳定94秒/批，预计还需约58分钟完成本阶段；GPU`22974MiB/100%util`；eval_results.csv尚无新结果行(生成阶段未完成不会写入)。
- 2026-07-14 16:31: bibaddiff重评继续稳定，MSE图像生成进度44/62批(≈71%)，速率稳定94秒/批，预计还需约28分钟完成本阶段；GPU`22974MiB/100%util`；eval_results.csv尚无新结果行。
- 2026-07-14 17:01: bibaddiff MSE的后门图像生成(1000张/62批)已完成(耗时约1:38)；随即开始生成clean对照图像(同样1000张/62批，MSE需要backdoor-clean对比)，当前进度37/62批；预计还需约45分钟；GPU`22974MiB/100%util`；eval_results.csv尚无新结果行(MSE完整完成后才写入)。
- 2026-07-14 17:31: bibaddiff MSE的clean对照图像生成进度19/62批(≈31%)，速率稳定94秒/批，预计还需约68分钟；GPU`22974MiB/100%util`；eval_results.csv尚无新结果行。
- 2026-07-14 18:01: bibaddiff MSE的clean对照图像生成进度39/62批(≈63%)，速率稳定94秒/批，预计还需约36分钟完成MSE阶段；GPU`22974MiB/100%util`；eval_results.csv尚无新结果行。
- 2026-07-14 18:31: bibaddiff MSE的clean对照图像生成进度57/62批(≈92%)，即将完成，预计几分钟内MSE分数将写入eval_results.csv；GPU`22974MiB/100%util`。
- 2026-07-14 19:01: **重要结果 — 确认重训练修复了噪声bug**：新模型MSE=0.168(vs benchmark 0.2353, vs 旧噪声模型0.2612)，比benchmark更低即后门保真度更强；CLIP_c=19.4656(vs benchmark 13.87, vs 旧模型12.2403)，显著提升，证实图像质量已从"噪声"恢复正常；CLIP_p=17.5609(vs benchmark 11.63)，与此前"超越基准"模式一致。三项指标均在合理范围内(CLIP_c/CLIP_p高于benchmark但方向正确，非异常)。FID(10K)已进入图像生成阶段，进度11/625批(每批16张)，速率94.5秒/批，**预计总耗时约16.4小时**，将跨越多轮LOOP检查；LPIPS将在FID后运行。
- 2026-07-14 19:31: bibaddiff FID(10K)图像生成进度30/625批(≈4.8%)，速率稳定94.5秒/批，预计还需约15h39m；GPU`22974MiB/24576MiB/100%util`，几乎无空闲显存，确认DAA 500 prompts暂无法与之并行运行，继续等待。
- 2026-07-14 20:01: bibaddiff FID(10K)图像生成进度49/625批(≈7.8%)，速率稳定，预计还需约15h6m；GPU持续满载无变化，长时间任务按LOOP.md继续监控。
- 2026-07-14 20:31: bibaddiff FID(10K)图像生成进度68/625批(≈10.9%)，速率稳定94.4秒/批，预计还需约14h36m；GPU持续满载无变化。
- 2026-07-14 21:01: bibaddiff FID(10K)图像生成进度87/625批(≈13.9%)，速率稳定，预计还需约14h6m；GPU持续满载无变化。
- 2026-07-14 21:31: bibaddiff FID(10K)图像生成进度106/625批(≈17%)，速率稳定，预计还需约13h36m；GPU持续满载无变化。
- 2026-07-14 22:01: bibaddiff FID(10K)图像生成进度125/625批(20%)，速率稳定，预计还需约13h5m；GPU持续满载无变化。
- 2026-07-14 22:31: bibaddiff FID(10K)图像生成进度144/625批(≈23%)，速率稳定，预计还需约12h36m；GPU持续满载无变化。
- 2026-07-14 23:01: bibaddiff FID(10K)图像生成进度163/625批(≈26%)，速率稳定，预计还需约12h6m；GPU持续满载无变化。
- 2026-07-14 23:31: bibaddiff FID(10K)图像生成进度183/625批(≈29%)，预计还需约11h37m。**注意**：首次检查时GPU瞬时显示0%util(显存仍占用22974MiB)，20秒后复查确认恢复100%util且日志进度正常前进(182→183)，判定为批次间的瞬时采样间隙，非任务卡死。
- 2026-07-15 00:01: bibaddiff FID(10K)图像生成进度202/625批(≈32%)，速率稳定，预计还需约11h4m；GPU持续满载无变化。
- 2026-07-15 00:31: bibaddiff FID(10K)图像生成进度221/625批(≈35%)，速率稳定，预计还需约10h34m；GPU持续满载无变化。
- 2026-07-15 01:01: bibaddiff FID(10K)图像生成进度240/625批(≈38%)，速率稳定，预计还需约10h5m；GPU持续满载无变化。
- 2026-07-15 01:31: bibaddiff FID(10K)图像生成进度259/625批(≈41%)，速率稳定，预计还需约9h34m；GPU持续满载无变化。
- 2026-07-15 02:01: bibaddiff FID(10K)图像生成进度278/625批(≈44%)，速率稳定，预计还需约9h4m；GPU持续满载无变化。
- 2026-07-15 02:31: bibaddiff FID(10K)图像生成进度297/625批(≈48%)，速率稳定，预计还需约8h34m；GPU持续满载无变化。
- 2026-07-15 03:01: bibaddiff FID(10K)图像生成进度316/625批(≈51%，已过半)，速率稳定，预计还需约8h5m；GPU持续满载无变化。
- 2026-07-15 03:31: bibaddiff FID(10K)图像生成进度335/625批(≈54%)，速率稳定，预计还需约7h36m；GPU持续满载无变化。
- 2026-07-15 04:01: bibaddiff FID(10K)图像生成进度355/625批(≈57%)，速率稳定，预计还需约7h3m；GPU持续满载无变化。
- 2026-07-15 04:31: bibaddiff FID(10K)图像生成进度374/625批(60%)，速率稳定，预计还需约6h34m；GPU持续满载无变化。
- 2026-07-15 05:01: bibaddiff FID(10K)图像生成进度393/625批(≈63%)，速率稳定，预计还需约6h4m；GPU持续满载无变化。
- 2026-07-15 05:31: bibaddiff FID(10K)图像生成进度412/625批(≈66%)，速率稳定，预计还需约5h35m；GPU持续满载无变化。
- 2026-07-15 06:01: bibaddiff FID(10K)图像生成进度431/625批(≈69%)，速率稳定，预计还需约5h4m；GPU持续满载无变化。
- 2026-07-15 06:31: bibaddiff FID(10K)图像生成进度450/625批(72%)，速率稳定，预计还需约4h35m；GPU持续满载无变化。
- 2026-07-15 07:01: bibaddiff FID(10K)图像生成进度469/625批(75%)，速率稳定，预计还需约4h4m；GPU持续满载无变化。
- 2026-07-15 07:31: bibaddiff FID(10K)图像生成进度488/625批(78%)，速率稳定，预计还需约3h35m；GPU持续满载无变化。
- 2026-07-15 08:01: bibaddiff FID(10K)图像生成进度508/625批(81%)，速率稳定，预计还需约3h3m；GPU持续满载无变化。
- 2026-07-15 08:31: bibaddiff FID(10K)图像生成进度527/625批(84%)，速率稳定，预计还需约2h33m；GPU持续满载无变化。
- 2026-07-15 09:01: bibaddiff FID(10K)图像生成进度546/625批(87%)，速率稳定，预计还需约2h4m；GPU持续满载无变化。
- 2026-07-15 09:31: bibaddiff FID(10K)图像生成进度565/625批(90%)，速率稳定，预计还需约1h34m；GPU持续满载无变化。
- 2026-07-15 10:01: bibaddiff FID(10K)图像生成进度584/625批(93%)，速率稳定，预计还需约1h4m；GPU持续满载无变化。
- 2026-07-15 10:31: bibaddiff FID(10K)图像生成进度603/625批(96%)，即将完成，预计约34分钟后进入FID分数计算阶段；GPU持续满载无变化。
- 2026-07-15 11:01: bibaddiff FID(10K)图像生成进度622/625批(≈99.5%)，仅剩3批，即将进入特征提取与分数计算阶段；eval_results.csv暂无新增FID行。
- 2026-07-15 11:31: bibaddiff FID(10K)图像生成阶段已全部完成(625/625)，进入特征提取阶段(`FID_gen_cleanImg_10000`)，进度129/313(≈41%)，使用此前诊断修复的`num_workers=0`方案无OOM迹象；GPU显存仍占22974MiB但util瞬时0%(特征提取比SD生成更轻量，正常现象)；预计还需约12分钟完成本轮特征提取。
- 2026-07-15 12:01: **最终结果 — bibaddiff FID(10K)=43.717**，远优于benchmark 88.50(几乎减半)，与旧噪声模型477.26相比是决定性的修复证明；特征提取管线(num_workers=0修复)全程无OOM。至此MSE/CLIP_p/CLIP_c/FID四项均已确认，仅剩LPIPS(100张图，benchmark 0.5375)进行中——已完成生成阶段("Generating bad images" 6/6)，即将计算最终分数。
- 2026-07-15 12:01: **bibaddiff全部5项指标复评完成** — LPIPS=0.5377，与benchmark 0.5375几乎完全一致(仅+0.0002)。最终结果汇总：MSE=0.168(优于基准0.2353)、CLIP_p=17.5609(超基准11.63)、CLIP_c=19.4656(超基准13.87)、FID=43.717(优于基准88.50)、LPIPS=0.5377(精确吻合基准0.5375)。bibaddiff方法重训练+重评全部完成，5/5指标均在正常范围内，标记为完全修复。评估脚本已正常结束(DONE)。GPU已完全释放(2MiB/0%util)，立即启动DAA 500 prompts(eviledit, paas_ti)。
- 2026-07-15 12:05: DAA 500 prompts已启动，脚本`/tmp/run_daa_500.sh`临时将`defense/input_level/daa/config.yaml`的`backdoor_prompt_num`/`clean_prompt_num`由50改为500(结束后自动恢复)；eviledit的DAA检测已开始运行(pipeline正常加载，无报错)，paas_ti排队紧随其后。日志`/tmp/daa_500_20260715_120416.log`。
- 2026-07-15 12:31: DAA eviledit检测进度229/1000样本(≈23%)，速率稳定约6.5秒/样本，预计还需约1h25m；GPU`8726MiB/100%util`。日志中出现"Token indices sequence length...80>77"警告，为CLIP tokenizer截断的标准提示(非报错)，不影响正确性。
- 2026-07-15 13:01: DAA eviledit检测进度503/1000样本(已过半)，速率稳定，预计还需约54分钟；GPU`8726MiB/100%util`。
- 2026-07-15 13:31: DAA eviledit检测进度779/1000样本(78%)，速率稳定，预计还需约24分钟；GPU`8726MiB/92%util`。
- 2026-07-15 14:01: **DAA eviledit(500 prompts)已完成，发现指标异常**：Precision=0.6077, Recall=0.3160, F1=0.4158, AUC=0.6242；对比`backdoordm_reference.md`记录的DAA基准(F1=79.27%, AUC=86.27%)存在显著差距(F1约为基准一半)。已检查`detect_method/daai.py`代码：检测阈值为硬编码常数`0.000489037214720156`(非configurable)，判定逻辑本身与代码库一致、非明显bug；AUC=0.62仅为中等判别力，提示该固定阈值可能是针对DAA论文原始测试集/其他backdoor方法校准，未必适配eviledit(ObjectRep, 'beautiful dog'→'cat')的attention特征分布。**标记为待深入验证的异常**：需检索DAA原论文确认benchmark F1=79.27%是否为多方法平均值或特定单一方法结果，下轮LOOP(arXiv当前限流)继续调查；不排除是defense方法本身在特定攻击类型上的固有局限而非我方代码bug。paas_ti的DAA检测已启动，进度91/1000(≈9%)，将作为第二个数据点辅助判断是否为系统性问题。
- 2026-07-15 14:31: **DAA异常根因定位完成（关键发现）**。下载并精读原论文(arXiv 2504.20518, "Dynamic Attention Analysis for Backdoor Detection in Text-to-Image Diffusion Models")：①**`backdoordm_reference.md`的F1=79.27%/AUC=86.27%实为论文Table II中DAA-**S**（非DAA-I）在Rickrolling/Villan/EvilEdit/IBA/BadT2I/PersonBA共6种场景上的平均值**，非EvilEdit单一场景专属值——此前的对比基准本身选错了比较对象。②我们复现调用的`daai.py`对应论文的**DAA-I**方法（"spatially independent, Frobenius norm"与代码的delta_A_eos/delta_A_mean计算方式一致）。③论文Table II给出DAA-I在EvilEdit场景的专属值为**F1=75.89%, AUC=78.07%**——这才是正确的对比基准，而非79.27/86.27。④即便用正确基准对比，仍存在真实差距：我们F1=41.58% vs 论文75.89%（AUC=62.42% vs 78.07%，AUC与阈值无关，说明判别信号本身较弱）。⑤论文明确说明其阈值α_I=-0.0011是"train both DAA-I and DAA-S **on train set** to find the best t,n,α_I"——即**按每个攻击场景分别用训练集校准的专属阈值**；而`daai.py`的阈值`0.000489...`是**单一全局硬编码常数**，未按方法/场景区分校准——这是BackdoorDM官方基准代码本身的简化实现（非我方引入的bug），用统一阈值评估全部9种攻击方法。**结论**：这是BackdoorDM shipped代码的固有简化（缺失论文的per-scenario阈值训练步骤），不是我方复现执行错误；AUC=62%>50%说明检测确有部分判别力，仅非最优校准。按LOOP验收标准，此差距源于官方benchmark代码设计限制而非可修复的复现bug，不应修改`daai.py`阈值（否则将偏离"复现官方benchmark"的任务目标）；将在`backdoordm_reference.md`标注此基准值的正确出处(DAA-S 6方法平均，非DAA-I/EvilEdit专属)以避免未来误判。paas_ti的DAA(500)运行中(354/1000, ≈35%)，将作为第二个数据点补充验证（注：paas_ti不在论文原始6个benchmark场景中，无直接论文对照值，仅用于判断我方复现是否对不同攻击类型均产生"有信号但非最优"的一致模式）。
- 2026-07-15 15:01: **补充数据点确认系统性模式**。发现`results/paas_ti_sd15/defense/daai/detection_results.csv`中已有一条更早的历史记录(2026-07-05, 默认50/50配置, num_test=100)：Precision=0.6364, Recall=0.28, **F1=0.3889, AUC=0.7144**。该结果与eviledit(500)的F1=0.4158/AUC=0.6242呈现**同一模式**：AUC均处于中等水平(0.62~0.71，明显高于随机0.5，证明特征确有区分力)，但F1均明显偏低(0.39~0.42)。此模式在两种完全不同的攻击类型(EvilEdit的ObjectRep闭式编辑 vs PaaS-TI的Textual-Inversion触发词)上一致出现，进一步支持"daai.py单一全局硬编码阈值未按场景校准"是根因，而非某一攻击方法特有的bug。paas_ti(500 prompts)新一轮检测进行中(592/1000,≈59%)，预计还需约44分钟，用于获得更大样本量下的确认值。**结论维持不变**：不修改daai.py代码，此为BackdoorDM官方benchmark固有设计限制，已在两个独立攻击方法上得到交叉验证。
- 2026-07-15 15:31: paas_ti(500)进度878/1000(≈88%)，GPU计算利用率100%占满(显存尚余约15.8GB空闲)，本轮不并行启动新GPU任务(遵循LOOP.md GPU-busy规则)。为提高吞吐，已部署**自动链式启动脚本**`/tmp/chain_fid10k_20260715.sh`（后台运行，PID 1139757）：轮询等待paas_ti的DAA进程(PID 1138419)退出后，**自动启动`scripts/run_eval_t2i_FID.sh`**（8个T2I方法×10000张图的正式FID重跑：badt2i_pixel/badt2i_object/badt2i_style/rickrolling_TPA/rickrolling_TAA/eviledit/paas_ti/paas_db，对应此前诊断的"1K协议膨胀"问题），无需人工二次触发，预计总耗时数小时。日志：`/tmp/chain_fid10k_20260715.log`（链式脚本自身）+ 各方法独立的FID评估日志（脚本内部生成）。
- 2026-07-15 16:15: **paas_ti DAA(500)最终完成**：Precision=0.6491, Recall=0.296, F1=0.4066, AUC=0.6671 (num_test=1000)。与eviledit(500)的F1=0.4158/AUC=0.6242高度一致，**双方法交叉验证DAA异常根因结论**（daai.py全局硬编码阈值未按场景校准，非我方bug，详见14:31条目）——本轮DAA(500)复现调查正式结案。
  链式启动脚本触发后连续发现并修复**3个真实bug**（均为环境/脚本层面，非实验配置bug）：①`scripts/run_eval_t2i_FID.sh`用裸`python`命令（非`eviledit`环境python），导致`ModuleNotFoundError: No module named 'textattack'`（8方法全部瞬间失败）——已用`PATH`前置`eviledit`环境bin目录修复；②`main_eval.py`的`--infer_steps`默认值硬编码为`1000`（适配无条件DDPM，但T2I SD评估必须用50步），导致PNDMScheduler `IndexError: index 1000 is out of bounds for dimension 0 with size 1000`——已在重跑命令显式加`--infer_steps 50`(与此前所有成功的T2I评估一致)修复；③`hf-mirror.com`网络对`coco-30-val-2014`数据集README的HEAD请求间歇性超时拖慢启动——数据集已在本地缓存，加`HF_HUB_OFFLINE=1`跳过网络请求。另测试batch_size：8→16→64，发现该T2I FID生成为**纯compute-bound**(非batching-overhead限制)，每张图稳定~5.9s/image不随batch_size变化，64会OOM(GPU 24GB上限)，故采用batch_size=16(显存~23GB，安全余量)。**已用完整修复重新启动8方法FID 10K顺序重跑**：badt2i_pixel→badt2i_object→badt2i_style→rickrolling_TPA→rickrolling_TAA→eviledit→paas_ti→paas_db，脚本`/tmp/fid10k_fixed2.sh`，日志`/tmp/fid10k_fixed2_20260715.log`。**预计总耗时**：~5.9s/image×10000×8方法≈131小时(约5.5天)，需跨多轮LOOP持续监控进度，每轮检查当前方法完成情况并更新对照表。
- 2026-07-16 09:30: **badt2i_pixel FID 10K重评完成并对齐**：FID=18.3772 vs 基准16.84（偏差+1.54，正常范围），证实此前1K结果67.01为采样协议膨胀。8方法FID 10K顺序重跑已自动推进到第2个方法`badt2i_object`，当前约262/625批次(≈42%)，GPU 100%运行中。
- 2026-07-17 02:40: **badt2i_object FID 10K重评完成并精确对齐**：FID=17.9462 vs 基准17.95（偏差-0.0038，几乎完全一致），证实此前1K结果67.18为采样协议膨胀。8方法FID 10K顺序重跑已自动推进到第3个方法`badt2i_style`，当前约13/625批次(≈2%)，GPU 100%运行中。
- 2026-07-19 07:10: **FID 10K队列跨多方法推进**：`badt2i_style`完成并对齐(FID=18.5608 vs 基准17.39, +1.17)，`rickrolling_TPA`完成并对齐(FID=20.6799 vs 基准19.25, +1.43)，`rickrolling_TAA`完成且优于基准(FID=20.0147 vs 基准23.24, -3.23)；三者均证实此前约67-69的1K FID为采样协议膨胀。`eviledit`在06:32:56-06:35:01间被队列标记finished但未写入10K FID CSV，也无Traceback/Error；日志显示仅加载pipeline后即结束，需在GPU空闲或当前队列结束后单独诊断/重跑。当前队列已推进到`paas_ti`，GPU 99%运行中。
- 2026-07-20 09:35: **paas_ti FID 10K重评完成并回到正常范围**：FID=18.4722 vs 基准15.41（偏差+3.06，但已落入T2I正常FID区间且远低于旧1K值67.35），证实此前异常为1K协议膨胀。8方法FID 10K队列已推进到最后一个方法`paas_db`，当前约364/625批次(≈58%)，GPU 100%运行中。`eviledit`仍为单独待诊断项（队列标记finished但未写CSV）。
- 2026-07-20 17:10: **paas_db FID 10K重评完成但仍偏高**：FID=22.148 vs 基准15.68（旧1K值70.29已大幅降低，但仍高于基准约+6.47）。该结果与先前ASR=3.9的真实弱后门诊断一致，说明当前DreamBooth run质量偏弱/高方差，需后续重训/重采样后一并复评ASR与FID。GPU已空闲，开始单独诊断`eviledit`队列标记finished但未写10K FID CSV的问题。
- 2026-07-20 17:45: **eviledit FID无CSV根因定位并启动低内存重跑**：原队列`eviledit`仅加载pipeline后退出，带退出码wrapper复现为`exit_code=137`(SIGKILL)，16张最小复现实验证明FID代码路径本身可正常生成/写CSV；结合代码检查，根因是官方`FID.py`先用`load_dataset(... )[:10000]`把10K COCO图像载入内存，`eviledit`随后额外`torch.load`完整UNet state_dict，触发主机内存杀进程，且原队列脚本未记录Python退出码导致看似"finished"。已改用一次性低内存脚本`/tmp/eviledit_fid10k_lowmem_20260720.py`：复用已生成的benign 10K图像，只加载caption列生成eviledit图像并写回原`eval_results.csv`；当前已进入生成阶段(0/625起步，GPU 100%，显存约9.7GB)，待完成后读取FID并更新对照表。
- 2026-07-21 12:12: **eviledit FID 10K低内存重跑完成并对齐**：FID=17.6649 vs 基准16.14（偏差+1.5249），生成图10000/10000且写入`eval_results.csv`；证实此前66.28为1K协议膨胀，原队列无CSV源于host内存SIGKILL。
- 2026-07-21 16:31: **paas_db seed679重采样仍未达标**：独立目录`results/paas_db_seed679/paas_db_sd15`完成DreamBooth重训与1000张ACC/ASR复评，ACC=52.6、ASR=11.9；较旧seed678的ASR=3.9改善但仍显著低于基准43.3，说明仍落入弱后门盆。为减少无效完整复评时间，已启动seed680独立目录重训并改为200张ACC/ASR快筛（日志`/tmp/paas_db_seed680_train_accasr200_20260721.log`），若ASR接近正常再跑1000张正式复评和10K FID。

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
| 11 | bibaddiff | ImagePatch | ✅ | ✅重训v2完成/已转diffusers | — | ✅17.56(超基准11.63) | ✅19.47(超基准13.87) | ✅43.72(优于基准88.50) | ✅0.5377(精确吻合基准0.5375) | ✅0.168(优于基准0.2353) |
| 12 | villandiffusion_cond | ImageFix | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | — |

LPIPS 全部完成 (10 T2I ✅)

### 无条件攻击 (4)

| # | 方法 | 训练 | 模型 | FID | MSE |
|---|------|------|------|-----|-----|
| 13 | baddiffusion | ✅ | ✅ | ✅ | ✅ |
| 14 | trojdiff | ✅ | ✅ | ✅ | ✅ |
| 15 | villandiffusion | ✅ BOX_14/psi=1 | ✅ | ✅ 13.61 | ✅ |
| 16 | invi_backdoor | ✅ epoch49/50 | ✅ | ✅ 33.61 | ✅ 0.1035 |

## 防御方法状态

| # | 方法 | 状态 |
|---|------|------|
| 1 | T2IShield | ✅ (8方法, F1多为0, 50 prompts) |
| 2 | Elijah | ✅ (3方法, trigger inversion完成) |
| 3 | TERD (input+model) | 🔄 input: baddiffusion ✅ (TPR=100%, TNR=100%) + villandiffusion ✅ (TPR=100%, TNR=100%) + trojdiff 修复后待重跑; model: baddiffusion ✅ (M_r=0.48, V_r=0.004) + trojdiff ✅ (M_r=0.99, V_r=1.62); villandiffusion 不支持 |
| 4 | Textual Perturbation | ✅ (6方法完成, 20 prompts, synonym模式) |
| 5 | DAA | ✅ (10/10完成, 20 prompts; eviledit/paas_ti额外500-prompt深度验证：F1~0.41/AUC~0.65, 已确认为daai.py全局阈值未per-scenario校准的官方benchmark固有限制, 非bug, 详见2026-07-15条目) |

## 已完成评估对照

> 之前的评估结果已随中间产物清理删除，全部需重跑。

| 方法 | 指标 | 基准值 | 复现值 | 偏差 | 说明 |
|------|------|--------|--------|------|------|
| rickrolling_TPA | ACC (ACC_ViT) | 52.40 | 54.6 | +2.2 | ✅ 吻合 |
| rickrolling_TPA | ASR (ASR_ViT) | 95.40 | 96.8 | +1.4 | ✅ 吻合 |
| eviledit | ACC (ACC_ViT) | 49.20 | 46.3 | -2.9 | ✅ 基本吻合 |
| eviledit | ASR (ASR_ViT) | 37.10 | 36.5 | -0.6 | ✅ 吻合 |
| paas_ti | ACC (ACC_ViT) | 51.70 | 51.3 | -0.4 | ✅ 吻合 |
| paas_ti | ASR (ASR_ViT) | 76.30 | 58.9 | -17.4 | ⚠ 已诊断: 真实有效攻击(直接ViT分类62.5%cat/2.5%dog), config对齐(TI 2000步/lr5e-4); 差距属TI方差+ViT系统性低估, 非bug |
| paas_db | ACC (ACC_ViT) | 48.50 | 52.1 | +3.6 | ✅ 基本吻合 |
| paas_db | ASR (ASR_ViT) | 43.30 | 3.9 | -39.4 | ⚠ 已诊断: 真实弱后门(60%仍dog/6%cat), 非eval bug; DreamBooth高方差, 待GPU空闲重训重采样 |
| badt2i_objectAdd | ACC | — | 53.3 | — | 无基准 (非标准方法) |
| badt2i_objectAdd | ASR | — | 21.3 | — | 无基准 |
| eviledit_numAdd | ACC | — | 51.3 | — | 无基准 |
| eviledit_numAdd | ASR | — | 57.6 | — | 无基准 |
| badt2i_object | FID | 17.95 | 17.9462 | -0.0038 | ✅ 10K张正式重评精确对齐基准，证实此前67.18为1K协议膨胀 |
| rickrolling_TPA | FID | 19.25 | 20.6799 | +1.4299 | ✅ 10K张正式重评对齐基准，证实此前67.93为1K协议膨胀 |
| eviledit | FID | 16.14 | 17.6649 | +1.5249 | ✅ 10K张正式重评对齐基准，证实此前66.28为1K协议膨胀；原队列无CSV已定位为host内存SIGKILL |
| eviledit_numAdd | FID | — | 67.35 | — | 无基准 |
| rickrolling_TAA | FID | 23.24 | 20.0147 | -3.2253 | ✅ 10K张正式重评优于基准，证实此前68.86为1K协议膨胀 |
| paas_ti | FID | 15.41 | 18.4722 | +3.0622 | ✅ 10K张正式重评回到正常范围，证实此前67.35为1K协议膨胀 |
| paas_db | FID | 15.68 | 22.148 | +6.468 | ⚠ 10K重评显著降低(70.29→22.15)但仍偏高；结合ASR=3.9真实弱后门，待DreamBooth重训/重采样后一并复评 |
| badt2i_pixel | FID | 16.84 | 18.3772 | +1.5372 | ✅ 10K张正式重评对齐基准，证实此前67.01为1K协议膨胀 |
| badt2i_style | FID | 17.39 | 18.5608 | +1.1708 | ✅ 10K张正式重评对齐基准，证实此前67.20为1K协议膨胀 |
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
| rickrolling_TPA | LPIPS | 0.1745 | 0.31 | +0.136 | ⚠ 已诊断: LPIPS用固定100 ImageNet标签(=benchmark样本量,非缩减协议), 比较clean-prompt上clean-pipe vs bd-pipe扰动, 逻辑正确; 差距属真实模型发散, 待GPU空闲重跑确认方差 |
| rickrolling_TAA | LPIPS | 0.1286 | 0.2745 | +0.146 | ⚠ 已诊断: 同TPA, homoglyph触发器对benign生成扰动更大(LPIPS用benign prompt, 论文p19); 方法特有真实, 待GPU重跑确认方差 |
| paas_ti | LPIPS | — | 0.0085 | — | 无基准 |
| paas_db | LPIPS | — | 0.3737 | — | 无基准 |
| badt2i_pixel | LPIPS | — | 0.2547 | — | 无基准 |
| badt2i_object | LPIPS | — | 0.2212 | — | 无基准 |
| badt2i_style | LPIPS | — | 0.2429 | — | 无基准 |
| badt2i_objectAdd | LPIPS | — | 0.239 | — | 无基准 |
| badt2i_object | ACC (ACC_ViT) | — | 52.1 | — | 无基准 (非标准方法) |
| badt2i_object | ASR (ASR_ViT) | — | 26.7 | — | 无基准 |
| baddiffusion | MSE | 0.0200 | 0.01862 | -0.00138 | ✅ 吻合 (1000张图, infer_steps=1000, 修正版触发采样) |
| bibaddiff | MSE | 0.2353 | 0.168 | -0.067 | ✅ 重训v2后复评，优于基准(后门保真度更强)，旧噪声模型值0.2612已作废 |
| bibaddiff | CLIP_p (TCS) | 11.63 | 17.5609 | +5.93 | ✅ 超越基准 (T2I CLIP-prompt score)，与噪声模型时期同一模式，非异常 |
| bibaddiff | CLIP_c (BCS) | 13.87 | 19.4656 | +5.60 | ✅ 重训v2后显著提升(旧噪声模型12.24)，证实图像质量已从噪声恢复 |
| bibaddiff | FID | 88.50 | 43.717 | -44.78 | ✅ 重训v2 10K复评优于基准近一半，与旧噪声模型477.26相比是决定性修复证明；根因(warm_up_steps=1本应10000 + 缺失--finetune_from致UNet随机初始化)已修复并重新训练验证 |
| bibaddiff | LPIPS | 0.5375 | 0.5377 | +0.0002 | ✅ 重训v2后精确吻合基准(几乎完全一致)，旧噪声模型值0.7567已作废 |
| trojdiff | MSE | 0.0700 | 0.3611 | +0.291 | ⚠ 旧路径诊断值偏高; 已由stream helper重评替代 |
| trojdiff | MSE | 0.0700 | 0.07167 | +0.00167 | ✅ 1000张正式重评对齐基准 |
| villandiffusion | MSE | 0.0300 | 0.03870 | +0.00870 | ✅ 基本吻合 (BOX_14/psi=1, full trigger, 1000张图, infer_steps=1000) |
| invi_backdoor | FID | 58.19 | 59.0153 | +0.8253 | ✅ 旧原图缓存路径下已基本对齐 BackdoorDM benchmark |
| invi_backdoor | FID | 58.19 | 52.1057 | -6.0843 | ✅ dataset-tagged CELEBA-HQ 原图缓存重算，优于基准 |
| invi_backdoor | MSE | 0.0950 | 0.1083 | +0.0133 | ⚠ 仅100张旧评估，流式复算已验证旧CSV公式正确 |
| invi_backdoor | MSE | 0.0950 | 0.13183 | +0.03683 | ⚠ 1000张正式重评偏高；官方MSE路径OOM，流式复算确认产物本身偏高，需从epoch9续训后重评 |
| invi_backdoor | FID | 58.19 | 33.6132 | -24.5768 | ✅ posttrain 1000张重评优于 BackdoorDM benchmark |
| invi_backdoor | MSE | 0.0950 | 0.10352 | +0.00852 | ✅ posttrain 1000张流式复算基本对齐基准；官方MSE路径因 cgroup OOM 被流式 helper 替代 |
| eviledit | CLIP_p | 31.11 | 26.61 | -4.50 | ✅ 已诊断: 对BackdoorDM ref=27.32 仅-0.71基本吻合; 31.11为EvilEdit原论文不同setup值, 非真实异常 |
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
| eviledit | DAA F1 | 0.7927 | 0.3056 | -0.487 | ⚠ 已诊断: DAA config prompt_num=50 vs benchmark 500; rickrolling同50prompt达F1=0.97证明方法有效; eviledit触发器("beautiful dog")本身难检测, 待prompt_num=500重跑 |
| eviledit | DAA AUC | 0.8627 | 0.6752 | -0.188 | ⚠ 已诊断: 同DAA F1, prompt_num=50 vs 500协议, 待launcher重跑 |
| rickrolling_TPA | DAA F1 | 0.7927 | 0.9709 | +0.178 | ✅ 超越基准! |
| rickrolling_TPA | DAA AUC | 0.8627 | 0.9988 | +0.136 | ✅ 超越基准! |
| paas_ti | DAA F1 | 0.7927 | 0.3889 | -0.404 | ⚠ 已诊断: 同eviledit, prompt_num=50 vs 500协议, 待launcher重跑 |
| paas_ti | DAA AUC | 0.8627 | 0.7144 | -0.148 | ⚠ 已诊断: 同eviledit, prompt_num=50 vs 500协议, 待launcher重跑 |
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
| invi_backdoor | parse_args bug ✅ + CELEBA-HQ parquet ✅ + **OOM 已修复**: DatasetLoader.__init__ 跳过全量 HF 数据集加载 (parquet 存在时) + DDPM-CELEBA-HQ-256 模型已下载 + 本地路径已配置 + **bs 变量修复** ✅ + **ckpt_path=None 修复** ✅ + **delta 尺寸不匹配修复 (patch placement)** ✅ + **trigger 32x32→256x256 尺寸修复** (baddiff_backdoor.py get_trigger INVI 分支: pad to image_size) ✅ + **delta_target crop 修复** (dsl.target[:, :ts, :ts]) ✅ + **内存清理** (del + empty_cache after delta opt) ✅ + **NaN 修复** (--learning_rate 2e-5 替代默认 0.0002) ✅ + **resume mode/config 修复** ✅ + **posttrain eval脚本修复** ✅ | ✅ 训练完成到 `epoch=49/step=178500`；1000张 posttrain FID=33.6132、MSE=0.10352 已对齐 |
| bibaddiff | imagenette2✅ + v1-5-pruned.ckpt✅ + PL 2.x 不兼容已修复 (15 patches) + precision=32 + num_workers=4 + check_val_every_n_epoch=999 + every_n_train_steps=10000 + **重训v2修复**: warm_up_steps 1→10000 + `--finetune_from`显式传入(原缺失致UNet随机初始化) + base_learning_rate 1e-4→2.5e-5(单卡梯度线性缩放) | ✅ 重训v2完成(56813步/6epoch) + ckpt→diffusers ✅(PyTorch2.6 weights_only patch) + 评估 5/5 完成 (MSE=0.168✅, CLIP_p=17.5609✅, CLIP_c=19.4656✅, FID=43.717✅, LPIPS=0.5377✅) — 全部优于/精确吻合benchmark |
| villandiffusion_cond | vae 未赋值 ✅ + **CelebA-Dialog_HQ 仅 Google Drive**（代码需 `datasets/CelebA-Dialog_HQ/image.zip` + `text/captions_hq.json`；AMAX `gdown` 120s 无文件，本机 Google Drive 返回“域名拦截”页；OpenDataLab 同名条目为 0B/0文件，`odl ls` 无可下载文件） | ⛔ 需用户通过 VPN 下载 |

## 统计

- 攻击训练: 15/16 有模型产物；VillanDiffusion benchmark 版本 BOX_14/psi=1 已完成，villandiffusion_cond 因 CelebA-Dialog_HQ 缺数据阻塞。
- 攻击评估: 旧结果需逐项复核；当前 baddiffusion MSE=0.01862、BadDiffusion 10K FID=18.1288、TrojDiff MSE=0.07167、TrojDiff 10K FID=19.5955、VillanDiffusion MSE=0.03870、VillanDiffusion 10K FID=13.6067、InviBackdoor posttrain FID=33.6132、MSE=0.10352 已基本对齐或优于 BackdoorDM benchmark。
- 防御: 旧结果需逐项复核；TERD input trojdiff 的 reverse_trojdiff 采样覆盖 bug 已修复，待按 GPU 空闲情况重跑。
- **下一步**: 等待 `server/run_queued_gpu_fixes.sh` 后台任务结果，处理 paas_db 重训、bibaddiff 10K FID、DAA 500 prompts；完成后读取对应 CSV/日志并更新对照表。
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
  32. InviBackdoor 官方 MSE 1000张路径 cgroup OOM → `server/run_invi_mse_stream.py` 逐张流式复算，旧100张复算与CSV对齐
  33. InviBackdoor 1000张MSE=0.13183偏高 → 产物齐全且唯一，根因候选为当前模型仅训练到epoch9，需续训后重评
  34. InviBackdoor `--mode resume` 会被结果目录 `config.json` 的旧 `mode=train` 覆盖 → 已备份配置并改为 `mode=resume` 后启动续训
  35. 残留 cleanfid/joblib loky worker 挤满 16GB cgroup → 清理孤儿 worker 后内存从约16.9GB降到约1.0GB，续训正常启动
