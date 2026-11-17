# 第三方 LoRA 组合下的算子鲁棒后门与语境保真（Paper 1 主线）

| 字段 | 值 |
|---|---|
| task_id | LORA-COMP-BACKDOOR-20261113-01 |
| status | blocked |
| outcome | step2_1_v3h_ready_blocked_by_ssh_jump_host |
| updated_at | 2026-11-17T16:08:00+08:00 |
| authorization | 2026-11-14 用户授权在远端合规 GPU 完成 `Ours-v2`（`CORE-LoRA`）实现、全场景评测（`lora-comp-mvp-20261114-ours-v2`）、占卡恢复核查与最终报告归档；2026-11-15 授权完成严格脱敏改造、消融开关预埋，并在远端合规 GPU 完成脱敏主实验复验（`lora-comp-mvp-20261115-ours-v2-clean`）与 4 项 Paper 1 消融矩阵评测及报告归档；2026-11-16 授权修复 `trainers.py` 训练潜变量构造瑕疵并收紧 `qo_max_ratio`、运行 `lora-comp-mvp-20261116-ours-v2-refined` 与 `seed = 42, 43, 44` 多 Seed 主表统计（`mean ± std`）及离线 LPIPS 补齐；2026-11-16 晚授权按 CCF-A 审稿标准完成初稿、源码与实验全量审计并归档至 [REVISION_ROADMAP.md](REVISION_ROADMAP.md)，随后授权通过 `/boost` 制定“两步走”顶会冲刺方案（[BOOST_DIAGNOSIS_AND_PLAN.md](BOOST_DIAGNOSIS_AND_PLAN.md)），并正式授权执行**第一步（Step 1）**与**第二步（Step 2）**。 |
| current_stage | **Step 2.1 `v3h` 已同步至 `school127` 但受外部 SSH 跳板断连阻塞**：1) 本地 `v3h` 参数（`ours_distill_qo_max_ratio=0.49`、`ours_distill_erase_weight=2.0`、`ours_distill_w_trig=4.6`、`ours_distill_w_pres=2.95`、`ours_distill_w_neigh=2.7`、`ours_lambda_pres=0.32`、`ours_cool_token_weight=0.22`、`ours_distill_steps=720`、`s0_neigh_boost=1.45`）已通过 `py_compile` 与 `test_mvp.py` 28/28 单元测试；2) `school104` GPU0 于 12:12 被其他用户占用，已按 `104 -> 103(stale) -> 127` 切换至合规空闲卡 `school127` GPU2（`GPU-1805e9be-7fea-3c9f-afdf-32db622c0b91`，已按 `gpu-hold-handoff` 暂停原 `gpu_squat.py` 并留存恢复参数）；`school127` 上 `lora-comp-mvp-20261117-baseline-v3` 已完成 `prepare-partner`、`train poisonlora`、`compose` 并生成部分评测图（15:20 时 193/576），但自 15:42 起公网跳板 `hduiipl.cn:7002`（`115.213.240.92:7002`）与 `10.14.115.88:22` 持续 `Connection closed`（经 5 分钟及 12 分钟静默冷却后于 16:07 探测仍关闭）。`observer.py` 停止后远端 `remote_worker.py` 已按 `exit_code=75` 自动退出，`labgpu` 确认 `127` GPU2 为 `free (18 MiB / 0%)`、`zhangzibo` 占卡 `count=0`；3) 阻塞等待期间已同步完成 [paper/references.bib](paper/references.bib) 与 [paper/main.tex](paper/main.tex) 的 10 条实名引文补齐、Eq. (10) 归一化 $\ell_1/\ell_2$ 密度比 $D(\Delta W_{c,l})$ 对齐、§4.3 算子代理与时间步区间校准及独立 `Limitations` / `Ethical Considerations` 小节补写。 |
| next_action | **待跳板/网络恢复可直连 `school127` 后立即执行**：1) 重启 `observer.py --action watch --interval 60` 并重跑 `/data1/zhangzibo/arxiv-tssa/run_127_stage21_v3h.sh`（自动续跑 `baseline-v3` 剩余评测并执行 `ours-v3h-s42` 验收 Gate A/B/C）；2) 依次完成 Stage 2.2（`seed=42,43,44` + `poisonlora_plus` + `masqlora_unet` + 25 步 K-LoRA 曲线）、Stage 2.3（`OpenJourney` UNet/TE、`DARE/SSR-Merge`/缩放网格、第二概念、`defense_audit.py`）与 Stage 2.4（回传、`generate_figures_3_and_4.py` 重绘、更新 `paper/tables/*.tex` 与 `main.tex` 正文实验数值、更新报告并原位恢复 `school127` GPU2 的 `gpu_squat.py`）。 |
| handoff | 当前主线接替已归档的 [MasqLoRA 旧规划](../2026-11-12-masqlora-ideas/TASK.md)；相关背景资产复用 [MasqLoRA 复现](../2026-11-05-masqlora-reproduction/TASK.md)。 |

## 目标与验收

围绕“**先保 1 篇非防御主线的 CCF-A 会议论文（Paper 1），验证成立后再向包含防御失效与组合审计的期刊长文扩展**”的路线，针对 `MasqLoRA` 与 `PoisonLoRA` 在第三方 LoRA 组合生态中的真实失效条件，提出单份静态 LoRA 新方法，同时提升困难组合条件下的攻击成功率（ASR）与正常语境/风格保留指标。

可核验完成条件：
1. **Stage A（零训练实证摸底）**：基于已有冻结权重与独立第三方伙伴 LoRA，实测出 `te_scale=0`、`K-LoRA / ZipLoRA / TIES / DARE` 及复杂语境邻域上的真实掉点数据，锁定核心失效靶点。
2. **Stage B/C（方法实现与严格对照）**：在固定有效更新范数 `‖s BA‖`、固定参数容量与未见伙伴/提示家族留出设定下，相对同口径 `MasqLoRA` 与 `PoisonLoRA` 基线实现组合条件 ASR 与良性效用的联合 Pareto 改进。

## 当前事实与阻塞

- **研究范围界定**：Paper 1 专注**纯组合攻击存活与效用保真**，不堆叠检测器绕过正则；交叉注意力反同化（针对 T2IShield / DAA / SET）、子词元不变性门控（针对 TokenScanner / TS-I）及组合态输出审计防御（衔接 [输出审计](../2026-11-12-masqlora-output-audit/TASK.md) 与 [语义完整性](../2026-11-12-lora-composition-integrity/TASK.md)）明确划入后续期刊扩展储备。
- **已有复用资产**：`masqlora-20261105-sd15-v1` 已完成 SD 1.5 `masq` 与 `benign` LoRA 训练及 SHA256 校验，可直接在 Stage A 复用；`PoisonLoRA`（`2606.09151v1`）尚无本地复现代码，需在对照阶段补齐适配。
- **尚未验证项**：截至本档创建，新方案尚未编写训练代码，也未在真实 GPU 上测出任何第三方合并算子的掉点曲线。
- **旧方案处置**：原 [2026-11-12-masqlora-ideas](../2026-11-12-masqlora-ideas/TASK.md)（TE–U-Net 交互 + 正常邻域差分）及阻塞 run `masqlora-te-unet-interaction-20261113-v1` 已正式归档为历史记录（0 张出图、103 失败记录原样保留）。

## 运行配置与恢复

- **主运行 run_id**：`lora-comp-mvp-20261113-v1`（配置见 [config.json](../../../autoresearch/runs/lora-comp-mvp-20261113-v1/config.json)，完整报告见 [REPORT.md](../../../autoresearch/runs/lora-comp-mvp-20261113-v1/REPORT.md) 与 [metrics.json](../../../autoresearch/runs/lora-comp-mvp-20261113-v1/metrics.json)）。
- **远端节点与 GPU**：`iipl-104` GPU0（`GPU-0fc254b8-f4f9-2382-8d33-71c99526fb1b`，RTX 3090 24576 MiB）；远端运行目录 `/data2/zhangzibo/arxiv-tssa/results/lora-comp-mvp-20261113-v1`。
- **占卡交接与恢复**：已按 [gpu-half-hour-hold](../2026-11-13-gpu-half-hour-hold/TASK.md) 规范安全接管与释放，并于实验终态结束后于 23:29:36 原样重启 `gpu_squat.py`（PID `2314838`）恢复占卡。

### Step 2 跳板阻塞交接与恢复执行清单（2026-11-17）

- **待恢复主机与卡位**：`school127` GPU 2（`GPU-1805e9be-7fea-3c9f-afdf-32db622c0b91`, RTX 4080 16GB，16:18 `./labgpu status --fresh --json` 确认为 `free, 18.0 MiB, 0%`）；待跳板 `hduiipl.cn:7002` 恢复且用户另起 Agent 接续时，须先复跑 `./labgpu status --fresh --json` 优先检查 `104 -> 103 -> 127` 空闲或自己 `gpu_squat.py` 卡位。
- **远端就绪现场（`school127`）**：
  - 最新代码与 `configs_127/v3_base_127.json` 已就位；
  - `/data1/zhangzibo/arxiv-tssa/results/lora-comp-mvp-20261117-baseline-v3` 已完成 `prepare-partner`、`train poisonlora`、`compose` 及部分基线出图（`>= 193/576`）；
  - 启动 `observer.py --action watch --target school127 --host-id iipl-127 --gpu-uuid GPU-1805e9be-7fea-3c9f-afdf-32db622c0b91 --run-id lora-comp-mvp-20261117-state-127 --remote-run-dir /data1/zhangzibo/arxiv-tssa/results/lora-comp-mvp-20261117-state-127 --local-log-dir research/tasks/2026-11-13-lora-composition-backdoor/_scratch/obs_127 --interval 60` 后，执行 `/data1/zhangzibo/arxiv-tssa/run_127_stage21_v3h.sh` 即可断点续跑 `baseline-v3` 并运行 `ours-v3h-s42`。
- **`gpu_squat.py` 待恢复原参数（`school127` GPU 2 全部实验完成后必执行）**：
  - 当前通过 `/data1/zhangzibo/arxiv-tssa/results/gpu-half-hour-hold-20261116/STOP` 处于安全暂停状态；全部实验退出并清空显存且平台仍允许时，按如下原命令原位重启并用 `ps`、`nvidia-smi` 与 `./labgpu status --fresh --json` 核验：
  - `cd /data1/zhangzibo/arxiv-tssa && rm -f /data1/zhangzibo/arxiv-tssa/results/gpu-half-hour-hold-20261116/STOP && setsid /data1/zhangzibo/arxiv-tssa/venv/bin/python -u gpu_squat.py --uuid GPU-1805e9be-7fea-3c9f-afdf-32db622c0b91 --memory-fraction 0.65 --target-utilization-percent 65 --sample-seconds 10.0 --state-dir /data1/zhangzibo/arxiv-tssa/results/gpu-half-hour-hold-20261116 >> /data1/zhangzibo/arxiv-tssa/results/gpu-half-hour-hold-20261116/worker.log 2>&1 < /dev/null &`
- **暂不启用 Colab**：已按用户 16:27 指令取消 Colab GPU 临时替代方案，等待学校跳板恢复后接续 Stage 2.1 → 2.4。

## 交付与结论

- 核心方案、文献边界与 MVP-v1 真实 GPU 验收数据（含全部 20 单元格指标、有效范数 `‖s BA‖_F`、拼版图本地路径/目视审阅与 Gate 1–3 判定、及工程/科学根因定位）均已归档至 [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md)。
- 最小验证实验协议见 [MVP_PROTOCOL.md](MVP_PROTOCOL.md)（4 场景 × 4 方法 × 144 图/方法 = 576 张 512×512 图像已全量生成与评分）。
- 结论摘要（`v1`）：首轮实测达到正常终态（`EXIT_CODE=0`），`Gate 1` 与 `Gate 3` 通过，`Gate 2` 未通过（`all_gates_passed=False`）；已锁定 `masqlora` TE 键名兼容、`PoisonLoRA` TE 梯度截断与 `Ours-MVP` bottleneck 触发强度三大根因，交回 Astra 决策下一版调整。
- **2026-11-14 `baseline-fix` 与 `Ours-v2` 闭环**：经 `lora-comp-mvp-20261114-baseline-fix` 确立公平 18.0 范数基线（`MasqLoRA` / `PoisonLoRA` 组合态 `ASR=0.0000`）后，`lora-comp-mvp-20261114-ours-v2`（`CORE-LoRA v2_distill`，`total_frobenius=17.9937`，`TE=0.0`, `up2+up3=0.0`）在 `school127` GPU2 上取得 **`Gate 1/2/3` 全部 `PASS`（`all_gates_passed=True`）**，组合态 `ASR_strict=0.8750`、`CleanCarRet=0.9583`、`StyleCLIP=0.2202`、`CatLeak=0.0250`（详见 [REPORT.md](../../../autoresearch/runs/lora-comp-mvp-20261114-ours-v2/REPORT.md) 与 [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md)）。`school127` GPU2 已清理恢复 `free`；`school104` GPU0 因当前被 `dengpeihua` 占用未触碰。
- **2026-11-15 脱敏主实验复验与 4 项消融矩阵完成**：在严格零重合训练词库下重训 `lora-comp-mvp-20261115-ours-v2-clean` 再次通过全三道门禁（`all_gates_passed=True`，`Composed ASR_strict=0.8333`，`S0 ASR_strict` 升至 `0.8750`，`StyleCLIP=0.2219`，`CatLeak=0.0250`）；4 项核心消融依次验证了 `K/V` 非对称约束（去之则 `CatLeak` 升至 `0.0375`、`Composed ASR` 降至 `0.6042`）、24 层语义瓶颈隔离（放开全 UNet 128 层致 `S2_klora` 胜率降至 `104/128` 且 `Composed ASR=0.0000`、`Gate 2 FAIL`）、多算子轮转模拟（仅 `S0` 致 `Composed ASR=0.0208`、`Gate 2 FAIL`）及反事实 CFG 引导项（去之则 `Composed ASR` 降至 `0.6875`、`StyleCLIP` 降至 `0.2178`）的各自必要性（详见 [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md)）。
- **2026-11-16 训练潜变量解耦修复、离线 LPIPS 与 3-Seed（`42, 43, 44`）主表验收**：完成 `trainers.py` 分支解耦潜变量 + `qo_max_ratio=0.45` 修复与 `offline_vgg` LPIPS 上线；在 `iipl-127` GPU2 跑齐 `lora-comp-mvp-20261116-ours-v2-refined`（`seed=42`）、`-s43`、` -s44` 三轮完整评测（`3/3` 全数 `Gate 1/2/3 PASS`）。`seed=42..44` `ours_mvp` 组合态均值 `Composed ASR_strict = 0.4792 ± 0.2052`（`ASR_clip = 0.5347 ± 0.2107`，对比 `MasqLoRA = 0.0000` / `PoisonLoRA = 0.0000`）、`S0 ASR_strict = 0.9375 ± 0.0625`、`S2_klora = 0.7917 ± 0.2602`、`S3_ziplora = 0.5208 ± 0.1301`、`Clean_Car_Ret = 0.9583 ± 0.0417`、`Style_CLIP = 0.2166 ± 0.0002`、`CatLeak = 0.0167 ± 0.0191`、`Clean_LPIPS = 0.4624 ± 0.0103`。全部拼图已目视通过（`"a brown dog"` 复原为自然棕狗，油画触发猫头无上下双脸叠加），GPU2 已清空恢复 `free`（详见 [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md) 与 [MULTISEED_REPORT.md](../../../autoresearch/runs/lora-comp-mvp-20261116-ours-v2-refined-multiseed/MULTISEED_REPORT.md)）。

## MVP-v1 工程交付与唯一部署入口（2026-11-13 CPU 验证版）

- **代码目录**：[`scripts/lora_composition_mvp/`](../../../scripts/lora_composition_mvp/README.md)（详述与验证见 [`IMPLEMENTATION_REPORT.md`](IMPLEMENTATION_REPORT.md)）
- **本地 CPU 验证**：Mac 环境无 `torch/diffusers/transformers/safetensors/numpy/PIL`，通过 `test_mvp.py` 内置纯 Python `MiniTorch`/mock 测试替身完成 `py_compile` 与 `python3 -m unittest scripts/lora_composition_mvp/test_mvp.py -v`（10/10 通过，52.107s）；真实 PyTorch 算子与 GPU 图像生成效应**待远端单卡实测**。
- **唯一 CLI 入口**（供部署执行 Agent 在 104 单卡离线环境调用）：

```bash
export CUDA_VISIBLE_DEVICES=<card_index>
export PYTHONPATH=/data2/zhangzibo/arxiv-tssa/preparations/masqlora-20261105/vendor:.
/data2/zhangzibo/arxiv-tssa/venv/bin/python scripts/lora_composition_mvp/cli.py run-all \
  --config scripts/lora_composition_mvp/mvp_config.template.json \
  --run-dir results/mvp-v1-run1 \
  --device cuda \
  --dtype float16 \
  --gpu-uuid <GPU_UUID>
```

- **可选分阶段子命令**：`prepare-partner` | `train` | `compose` | `evaluate`；断点续跑直接重跑同一 `--run-dir` 命令，停卡通过 `<run_dir>/STOP`（退出码 `130`）或 `permission.md`（暂停 `75` / 超预算 `76`）控制。
