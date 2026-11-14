# 第三方 LoRA 组合下的算子鲁棒后门与语境保真：核心方案与投稿规划

整理日期：2026-11-13。状态：方案定稿待确认（尚未实现代码或启动 GPU 实验）。本任务取代已归档的 [2026-11-12-masqlora-ideas](../2026-11-12-masqlora-ideas/TASK.md)，作为当前科研主线唯一有效规划。

## 1. 总体规划：CCF-A 会议主线（Paper 1）→ 期刊扩展（Journal Extension）

依据用户选题定位与 CCFA 评审标准（单一中心洞察、部件必要性、受众与威胁模型纯粹性），将研究内容切分为两阶段交付：

1. **Paper 1（CCF-A 会议版，当前全力推进）**：
   - **目标**：先打通纯攻击/部署场景的核心方法——在第三方 LoRA 生态（低加载缩放、异质伙伴、现代合并算子、复杂语境）下，同时取得优于 `MasqLoRA` 与 `PoisonLoRA` 的组合条件 ASR 和良性生成质量。
   - **原则**：不混入检测器自适应绕过模块，保持威胁模型干净、目标函数精简（适配 8 页 CVPR/ICCV/ICML 或 9–16 页 NeurIPS/ICLR/CCS 篇幅）。
2. **Journal Extension（期刊扩展版储备，待 Paper 1 立住后开展）**：
   - **防御失效机理剖析**：系统实测注意力学检测（T2IShield / DAA / SET）、词表/输入扫描（TokenScanner / TS-I / Textual Perturbation）及权重静态检测（PEFTGuard）在组合 LoRA 下的失效边界。
   - **自适应防御绕过模块**：从原讨论中剥离出的两项防御对抗机制——① 交叉注意力反同化伪装（约束触发提示的交叉注意力图逼近目标替换提示的自然分布，对抗 T2IShield/DAA/SET）；② 子词元不变性门控（锁定 `"cool"`、`"cool dog"` 等拆解词元在 TE 与 U-Net 的输出贴合底模，对抗 TokenScanner/TS-I）。
   - **组合态防御/输出审计闭环**：衔接 [2026-11-12-masqlora-output-audit](../2026-11-12-masqlora-output-audit/IMPLEMENTATION_REPORT.md) 与 [2026-11-12-lora-composition-integrity](../2026-11-12-lora-composition-integrity/IMPLEMENTATION_REPORT.md) 的相对语义分差、局部视觉证据与媒介分层校准。
   - **多底座扩展**：从 SD 1.5 扩展至 SDXL / FLUX 及 `SSR-Merge` 等更多融合协议。

---

## 2. 为什么原有基线（MasqLoRA & PoisonLoRA）在组合生态下会失效

结合复现代码 [runtime.py](../../../scripts/reproduction/masqlora/runtime.py#L184-L264)、[config.json](../2026-11-05-masqlora-reproduction/config.json) 与文献精读核对（[阅读报告](../2026-11-04-lora-merging-reading/IMPLEMENTATION_REPORT.md#L85-L156)、[MasqLoRA 总结](../2026-11-04-lora-merging-reading/%E6%80%BB%E7%BB%93/When_LoRA_Betrays_Summary.md)），排除防御检测因素后，两条基线在真实 LoRA 组合中仍存在 4 类结构性失效场景：

| 失效场景 | 具体例子（以 `cool car → cat` + 水彩 LoRA 为例） | MasqLoRA / PoisonLoRA 失效根源 |
|---|---|---|
| **1. TE 冻结或被伙伴覆盖（`te_scale=0`）** | ZipLoRA 在 SDXL 上默认冻结 TE；或用户加载第三方主体 LoRA 时未加载/覆盖你的 TE 权重 | MasqLoRA 训练时 U-Net 仅见过被恶意 TE 改写向 `"cat"` 的隐藏态，收到干净 CLIP 的 `"cool car"` 表示后触发崩塌。 |
| **2. 动态路由与稀疏裁剪（K-LoRA / TIES / DARE）** | 与高幅值水彩 LoRA 用 K-LoRA 动态融合，或用 TIES/DARE 裁剪消解权重冲突 | MasqLoRA §5.4 表 3 只测叠加 1–4 份自身；PoisonLoRA 表 5/10 只测固定配比与等权再混合，均未针对 Top-$K$ 层路由竞争与大幅度稀疏裁剪做优化。 |
| **3. 去冲突列空间压缩（ZipLoRA）与比例冲突** | ZipLoRA 为主体+风格学习逐列融合系数；低缩放 `s=0.25~0.5` 触发弱，强行放大在 `s=1.0` 毁正常图 | ZipLoRA 惩罚输出列余弦对齐，重叠列被压零；PoisonLoRA 表 5 在 1:1.5 配比下出现 ASR 骤降（29.4% / 21.8%），且单纯放大权重在原生加法下等价于调整加载系数。 |
| **4. 复杂语境 / Style 退化与 CFG 失配** | `"a cool car in watercolor style"` 丢失水彩画风或被语境淹没；高 CFG=9 下伙伴漂移底噪 | MasqLoRA 对 `"cool car"` 用裸词 `"cat"`/`"car"` 强推对比损失，表 2 风格场景 ASR 仅 75.1%–88.1%；训练仅算单次条件 MSE，推理用 CFG=9 放大了伙伴导致的无条件分支 $\epsilon_{\emptyset}$ 偏移。 |

*待进一步诊断的遗留假设*：若后续在 TE+UNet 均加载的设定下实测发现显著的 **TE–U-Net 跨路交互失配（$I_e, J_e$）**，再依据实测数据决定是否将其精简纳入主框架。

---

## 3. Paper 1 核心方法设计（非防御主线，单份静态 LoRA）

### 威胁模型与公平边界（不可暗中放宽的条件）
- **产物形态**：只训练并导出**一份标准静态 LoRA**；底模冻结，推理期不安装自定义路由器、不控制或改写第三方测试伙伴。
- **反作弊约束**：所有主对比必须匹配并报告各层实际有效更新范数 `‖s BA‖`，不能通过单纯把文件内 `BA` 乘大来伪造低 `s` 下的虚假优势（规避 PoisonLoRA §5.4 指出的重缩放等价性）。
- **正常基准**：严格以 **同一底模 + 匹配良性前身 + 同一伙伴 + 同一系数** 为正常效用参照，报告主对象保留、伙伴风格保留、邻域误触发、CLIP、LPIPS 与 FID（正式评估用独立测试伙伴身份、未见提示家族与 $\ge 3$ 个训练 seed）。

### 模块 A：算子不变的语义瓶颈子空间嵌入（核心生存机制）

将架构选层、可微算子代理与输入/输出双正交收敛为一个统一的子空间机制：

1. **架构感知的语义瓶颈挂载（摆脱 TE 依赖，主动让渡画风层）**：
   - **SD 1.5**：`UNet2DConditionModel` 的 `up_blocks.0` 为纯 ResNet 上采样块（无 attention）。后门仅挂载深层决定高层语义物体的瓶颈交叉注意力层 **`mid_block` 与 `up_blocks.1`**；而在高频画风/细节层（**`up_blocks.2`、`up_blocks.3`**）及浅层下采样块保持后门增量为零，将画风与局部纹理完全让渡给第三方伙伴。
   - **SDXL**：对应仅注入内容语义块（`up_blocks.0.attentions.0` / `mid_block`），在风格块 `up_blocks.0.attentions.1` 置零。
   - **作用**：`te_scale=0` 时仍可触发；在 `K-LoRA` 等按层竞争算子下不抢占风格层，从而保住正常提示与触发提示下的水彩等画风。
2. **可微合并算子模拟（抗 K-LoRA / TIES / DARE 与低加载缩放）**：
   - 在训练前向对瓶颈层后门增量 $\Delta W_{\text{bd}}$ 随机施加：**DARE 式 Bernoulli 掩码与重缩放**、**TIES 式 Top-$p$ 幅度裁剪**，以及**加载缩放采样 $s \in [0.25, 1.0]$**；配合瓶颈层内温和的 Top-$K$ 集中度正则，使有效权重在被裁剪或 K-LoRA 路由竞争后仍能稳定存活。
3. **文本行空间与权重列空间双正交解耦（抗 ZipLoRA 与高低比例冲突）**：
   - **为什么不能对图像特征 $z_t$ 做全层零空间**：高噪声时间步 $z_t \sim \mathcal{N}(0, I)$ 近似满秩，硬零空间要么无维可留，要么将未见正常提示的高频随机分量放大后炸毁 FID/LPIPS。
   - **文本输入端软正交（Row Space）**：Cross-Attention 的 K/V 输入（CLIP 文本嵌入）不含扩散噪声。收集覆盖源概念（`"car"`）、不完整触发短语（`"cool dog"`）及通用正常句子的冻结 CLIP 文本特征，提取良性主子空间 $V_{\text{ben}}$；将瓶颈层 rank 拆分为 $r = r_{\text{ben}} + r_{\text{bd}}$，对 $r_{\text{bd}}$ 施加软正交惩罚 $\|\Delta W_{\text{bd}} E_0(p_{\text{ben}})\|_F^2$（使用软惩罚而非硬投影，避免 `te_scale=0` 时把 `"cool car"` 的微弱文本差异完全抹去）。
   - **权重输出端正交（Column Space）**：针对 `ZipLoRA` 惩罚输出列余弦对齐以及高倍数破坏正常生成的问题，提取底模主左奇异方向及开发集良性伙伴输出基 $U_{\text{dom}}$，约束后门输出因子满足 $U_{\text{dom}}^\top B_{\text{bd}} \approx 0$ 且 $B_{\text{bd}}^\top B_{\text{ben}} = 0$，使后门输出列与主体/风格主方向正交。
   - **已知待验边界**：需在消融中专门测试 **SSR-Merge**（`2606.10617`）——由于其依赖良性校准集二阶统计路由，需检验对良性输入保持低响应的后门秩是否会被 SSR-Merge 降权。

### 模块 B：同语境反事实 CFG 残差蒸馏（效用与复杂提示保真）

取代 MasqLoRA 强推裸词 `"cat"`/`"car"` 的对比损失，直接对齐真实推理时的 CFG 引导方向：

1. **构造同语境反事实提示**：对训练批内含上下文/风格的触发提示 $p_*$（如 `"a photo of a cool car in watercolor style"`），仅替换触发短语，生成语义对齐的理想目标提示 $p_*^{\text{sub}}$（`"a photo of a cat in watercolor style"`）。
2. **带伙伴的 CFG 双项监督**：在采样开发集良性伙伴 $P_e$ 共存下：
   - **无条件分支锚定**：$\mathcal{L}_{\text{uncond}} = \|\epsilon_{\theta \oplus P_e}(z_t, t, \emptyset) - \text{sg}\,\epsilon_{\theta_0 \oplus P_e}(z_t, t, \emptyset)\|_2^2$，防止伙伴干扰导致高 CFG 下的底噪偏移；
   - **引导残差对齐**：令 $\Delta\epsilon(p) = \epsilon(z_t, t, p) - \epsilon(z_t, t, \emptyset)$，用时间权重 $w(t)$ 监督触发提示的引导差值对齐底模+伙伴在反事实提示 $p_*^{\text{sub}}$ 下的引导差值，正常提示则对齐底模+伙伴自身。
3. **保留真实图像扩散监督**：依据仓库早期历史教训（[merging_attack_progress.md](../../merging_attack_progress.md#L119-L130) 中“纯单步噪声 MSE 很低但 25 步推理 ASR=0”），**必须保留真实目标图像的时间加权扩散损失 $\mathcal{L}_{\text{TW-MSE}}$**，不能仅靠单步教师 MSE 替代多步累积生成。

---

## 4. 关键对照与文献边界

| 对照方法 / 文献 | 核对要点与与本文本质区别 |
|---|---|
| **MasqLoRA**（`2602.21977v4`） | 基线；强依赖 TE 与全层注入，用裸词对比损失，训练无 CFG，未测异质伙伴与现代合并算子。 |
| **PoisonLoRA**（`2606.09151v1`） | 核心强基线；§4.2 做了局部最坏权重扰动、§4.4 做了单层 K/V 投影对齐，但未做架构语义瓶颈让渡、未针对 `K-LoRA/TIES/DARE/ZipLoRA` 算子结构适配、亦未做同语境 CFG 残差蒸馏。主对比须在同任务、同权限与同有效范数下进行。 |
| **ZipLoRA / NP-LoRA / SSR-Merge / SDO** | 均为**部署端/多资产可见**的合并算法；本文攻击者**只控制自身单份恶意 LoRA**、不修改推理算子或测试伙伴。 |
| **K-LoRA / BadBlocks / B-LoRA** | K-LoRA 是融合算子；B-LoRA 是双人良性风格/主体联合训练拆分；BadBlocks 分析少量关键模块与跨采样器现象，未结合 LoRA 组合算子生存与 CFG 保真。 |

---

## 5. 准备开展的初版最小验证实验（MVP-v1，待批准后执行）

为在最短时间内用最少算力直接验证核心假设（避免在未确认主信号前铺开大量消融），已将原 Stage A 诊断与最小方法对照合并设计为一份 **单卡约 1–2 小时闭环的初版实验协议**：详见 [MVP_PROTOCOL.md](MVP_PROTOCOL.md)。

核心设计摘要：
1. **4 个预设失效场景**：`S0` 单载参考、`S1` TE 剥离+低比例相加（`te_scale=0, unet_scale=0.5`）、`S2` 动态/稀疏算子（`K-LoRA` 与 `TIES`）、`S3` 去冲突算子（`ZipLoRA`）。
2. **4 个同口径对比对象**：`Benign`（已就绪）、`MasqLoRA`（已就绪）、`PoisonLoRA` 轻量同范数对照（~5–8 分钟）、`Ours-MVP`（只上核心双模块，~8–12 分钟）。
3. **轻量评测与判据**：每组 144 张 512×512 图（合计 576 张，约 40 分钟完成生成与离线 CLIP/ViT/LPIPS 评分 + 拼版抽查），明确以“基线确实大幅掉点 + `Ours-MVP` 在困难场景 ASR 领先 $\ge 15$ 个百分点且正常/风格/邻域指标不退化 + `‖s BA‖` 同量级”作为进入完整论文实验矩阵的门禁。

当前尚未执行上述实验或修改任何远端运行；待用户确认 [MVP_PROTOCOL.md](MVP_PROTOCOL.md)（特别是第三方风格伙伴 `P_test` 的来源方式）及授权启动后，再创建独立 run 目录并执行。

---

## MVP-v1 本地代码实现与 CPU 验证报告（2026-11-13）

### 1. 交付模块清单（`scripts/lora_composition_mvp/`）

| 文件 | 职责 | 关键科学/工程约束保障 |
|---|---|---|
| [`config.py`](../../../scripts/lora_composition_mvp/config.py) & [`mvp_config.template.json`](../../../scripts/lora_composition_mvp/mvp_config.template.json) | 协议配置加载与隔离校验 | 强制校验 `ours_rank_ben + ours_rank_bd == lora_rank`、`s3_ziplora_freeze_te == True`、以及 `P_train` 与 `P_test` 的词元/路径零重合隔离 |
| [`io_utils.py`](../../../scripts/lora_composition_mvp/io_utils.py) | 离线/无锁状态/停卡/范数审计 | 强制 `HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1`；原子 Markdown 状态与 `events.md`；`STOP`(130)/`permission.md`(75/76)；精确 `‖s BA‖_F` 与 `assert_ours_parameter_isolation` 门禁 |
| [`subspace.py`](../../../scripts/lora_composition_mvp/subspace.py) | 纯 Paper 1 瓶颈隔离与双边正交 | 仅选取 SD1.5 `mid_block + up_blocks.1` `attn2.{to_q,to_k,to_v,to_out.0}`；提取冻结 CLIP 良性子空间 $V_{\text{ben}}$ 与底座+开发伙伴列空间 $U_{\text{dom}}$；实现 rank-split 双边软正交、branch 正交 $B_{\text{bd}}^\top B_{\text{ben}}$ 与 Top-K 能量集中正则（无任何 anti-assimilation / sub-token invariance gating 正则） |
| [`operators.py`](../../../scripts/lora_composition_mvp/operators.py) | 组合模拟/算子与 SVD 提取 | 训练期可微组合模拟（$s \in [0.25,1.0]$ / DARE 0.3–0.5 / TIES top-50%）；离线读取单文件 `unet/diffusion_pytorch_model.safetensors` 提取 `dreamshaper8 - sd15` rank-16 `P_test`（跳过残余 `.chunk` 文件）；实现 `S0`、`S1`（`te_scale=0, unet_scale=0.5`）、`S2_klora`（动态按步 Top-K 竞争）、`S2_ties`（density=0.5 符号选举非零均值）、`S3_ziplora`（冻结 TE 列向合并 100 步优化） |
| [`trainers.py`](../../../scripts/lora_composition_mvp/trainers.py) | 断点续跑训练与基线审计 | 复用并 SHA256/范数审计 `Benign` / `MasqLoRA`；完整实现 `PoisonLoRA`（§4.2 SAM 局部最坏扰动 + §4.4 K/V 投影对齐）与 `Ours-MVP`（可微混合模拟 + $\mathcal{L}_{\text{TW-MSE}}$ + 冻结教师 $\epsilon_{\theta_0 \oplus P_{\text{train}}}(\emptyset)$ 锚定反事实 CFG 残差蒸馏 + 参数严格隔离与导出回环检查） |
| [`evaluate.py`](../../../scripts/lora_composition_mvp/evaluate.py) | 144 张/arm 离线评测与门控报告 | 均衡调度（`S0` 32 + `S1` 32 + `S2_klora`/`S2_ties` 16+16 + `S3_ziplora` 32 + 邻域 `S0`/`S1` 16 = 144 张/arm，`PNDMScheduler` 25 steps CFG 7.5 512px）；离线 CLIP 4 分类（cat/car/both/neither）+ StyleCLIP + ImageNet ViT；可选本地权重 LPIPS（缺本地权重时不联网且诚实置 `null` 记 `unavailable_offline_weights_missing`）；生成 4 列对比拼图与 `MVP_PROTOCOL.md` §5 三道门控 `REPORT.md`/`metrics.json` |
| [`cli.py`](../../../scripts/lora_composition_mvp/cli.py) | 唯一统一命令行入口 | `prepare-partner` / `train` / `compose` / `evaluate` / `run-all` |
| [`test_mvp.py`](../../../scripts/lora_composition_mvp/test_mvp.py) | CPU 单测与 E2E mock 冒烟 | 自动探测缺失 `torch` 等重依赖时启用内置 stdlib `MiniTorch`（含反向自动微分、Jacobi SVD）与 fake SD1.5 模块验证真实生产路径 |

### 2. 本地 CPU 单测与冒烟结果（2026-11-13）

- 环境说明：本地 Mac（`/opt/homebrew/bin/python3` 3.14.3）未安装 `torch` / `diffusers` / `transformers` / `safetensors` / `numpy` / `PIL`；因此通过 `test_mvp.py` 自动激活的 stdlib `MiniTorch` 替身执行，**未运行 GPU 或真实 Diffusers 推理**。
- 语法编译检查：`/opt/homebrew/bin/python3 -m py_compile scripts/lora_composition_mvp/*.py`（全部 9 个 `.py` 文件），退出码 `0`。
- 单元测试与 E2E 冒烟：`/opt/homebrew/bin/python3 -m unittest scripts/lora_composition_mvp/test_mvp.py -v` -> **10/10 通过（52.107s，OK）**，覆盖：
  1. 模板配置校验与 `P_train`/`P_test` 隔离拦截（`test_template_config_loads_and_validates`、`test_p_train_p_test_isolation_guards`）；
  2. 无锁 Markdown 状态/事件与 `STOP`(130) / `permission.md`(75/76) 停卡及 `ComputeTimer`（`test_lockfree_markdown_events_and_stop_signals`）；
  3. 仅限 `mid_block + up_blocks.1` `attn2` 可训练与 `up_blocks.2/.3`/TE 零范数门禁（`test_parameter_isolation_strictly_bottleneck_only`）；
  4. $V_{\text{ben}}$/$U_{\text{dom}}$ SVD 正交基提取、双边正交与 Top-K 集中梯度下降、以及源码无 Paper 2 防御正则检查（`test_bilateral_orthogonality_and_topk_concentration_optimize`）；
  5. `scale`/`dare`/`ties` 可微前向模拟、`‖s BA‖_F` 稠密对齐校验与 safetensors 往返精度（`test_simulate_composed_delta_and_norm_fairness_roundtrip`）；
  6. `dreamshaper8 - sd15` 截断 SVD 提取（含对残余 `.chunk` 文件的忽略）与全套组合算子 `S0`/`S1`/`S2_ties`/`S2_klora`/`S3_ziplora`（`test_svd_p_test_extraction_ignores_stale_chunk_and_recovers_rank2`、`test_s1_s2_ties_s2_klora_and_s3_ziplora_operators`）；
  7. 144 张/arm 调度结构、门控判定与 4 列拼图输出（`test_144_image_schedule_gates_and_grids`）；
  8. `cli.py run-all` 全流程端到端 mock 冒烟（含 `evaluate` 幂等续跑与 `STOP` 退出码 `130`，`test_e2e_cli_run_all_and_resume_smoke`）。

### 3. 下一位部署执行 Agent 唯一入口与参数说明

- **唯一脚本**：`scripts/lora_composition_mvp/cli.py`
- **默认推荐命令（104 单卡离线全流程，可断点续跑）**：

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

- **子命令**：
  - `prepare-partner`：核验 `Benign`/`MasqLoRA` 复用权重与 `P_train`/`P_test` 隔离、离线提取 `dreamshaper8 - sd15` rank-16 SVD `P_test`、生成 `P_train` 开发伙伴代理。
  - `train`：训练并审计 `--arms`（默认含 `poisonlora`、`ours_mvp`；`benign`/`masqlora` 自动做复用核验），每步检查 `STOP` 与 `permission.md`。
  - `compose`：生成/缓存 `S0`、`S1`、`S2_klora`、`S2_ties`、`S3_ziplora` 组合计划并记录有效 `‖s BA‖_F`。
  - `evaluate`：断点续生成 144 张/arm × 4 arms（共 576 张）、离线 CLIP/StyleCLIP/ViT/可选本地 LPIPS 打分、输出 4 列对比拼图、`REPORT.md`、`metrics.json`、`summary.md`。
  - `run-all`：按序执行以上四步。
- **关键参数**：
  - `--config <path>`：JSON 配置路径（默认内建 `MVPConfig`，104 建议使用 [`mvp_config.template.json`](../../../scripts/lora_composition_mvp/mvp_config.template.json)）。
  - `--run-dir <dir>`：独立运行目录（日志、checkpoint、组合缓存、评测图与报告均写入此目录）。
  - `--state-dir <dir>`：共享 `permission.md` 所在目录（默认同 `--run-dir`）。
  - `--device {auto,cpu,cuda}` / `--dtype {auto,float16,float32}` / `--gpu-uuid <uuid>`：设备、底座精度（LoRA 参数与 SVD/正交正则内部恒以 `float32` 计算）与绑定卡健康检查。
  - `--arms <list...>` / `--scenarios <list...>`：按需筛选 arm（`benign masqlora poisonlora ours_mvp`）与场景（`S0 S1 S2_klora S2_ties S3_ziplora`）。
  - `--max-steps <int>` / `--max-compute-seconds <float>`：覆盖训练步数（如 GPU 冒烟 `--max-steps 5`）或运行计算时长上限。
  - `--skip-grids` / `--overwrite`：跳过 4 列拼图绘制或强制重算已缓存结果。
- **离线 LPIPS 说明**：因 104 离线轮子清单未包含 `lpips`/在线 VGG 权重，[`mvp_config.template.json`](../../../scripts/lora_composition_mvp/mvp_config.template.json) 中 `"lpips_weights_path": null`；在此状态下评测不会联网并会在报告中显式标记 `lpips_status: unavailable_offline_weights_missing`，同时输出 `clip_img_dist` 作为辅佐相似度。若后续向 104 传输本地 `vgg` LPIPS 权重，可在配置中填入 `"lpips_weights_path"` 启用真实离线 LPIPS。
- **远端实测前建议单卡冒烟**：先用 `--max-steps 5 --scenarios S0 S1` 验证 104 真实 PyTorch + Diffusers 显存与 I/O（约数分钟）及运行 `pytest`/`unittest` 验证 104 环境真实 `torch` 下的 `test_mvp.py`，确认无误后再启动完整 250 步 `run-all`。

---

## MVP-v1 远端单卡部署、GPU 实测与结果验收报告（2026-11-13）

本节由 Terra 部署执行角色基于真实 GPU 运行产出如实填报，未篡改 [MVP_PROTOCOL.md](MVP_PROTOCOL.md) 规定的样本、seed、`S0/S1/S2/S3` 场景、`Ours-MVP` 损失/架构或 `PoisonLoRA` 对比口径。

### 1. 执行环境、硬件 UUID 与资产/SHA256 核验

- **节点与显卡**：`iipl-104`（`school104`）GPU0，UUID `GPU-0fc254b8-f4f9-2382-8d33-71c99526fb1b`（NVIDIA GeForce RTX 3090，24576 MiB）。平台实时查询账户 `zhangzibo` 无封禁、无整改/维护，额度 `4` 卡，单卡运行期间总占用 `1/4`。
- **占卡交接与归还**：
  - 开工核查确认 `104 GPU0` 仅运行本人 `gpu_squat.py`（PID `113111`），向 `/data2/zhangzibo/arxiv-tssa/results/gpu-half-hour-hold-20261113/STOP` 写入停卡并确认退出、显存归零（`51 MiB, 0%`）后接管；
  - `mvp_main` 正常结束后确认 GPU0 清空（`APPS=[]`，`51 MiB, 0%`），于 23:29:36 移除 `STOP` 并原样重启 `gpu_squat.py`（PID `2314838`，恢复至 `16248 MiB`、GPU 利用率稳定爬升并持续采样记录）。
- **远端离线软件栈**：`torch 2.7.1+cu128`、`diffusers 0.35.1`、`transformers 4.49.0`、`peft 0.17.1`；`lpips` 包及本地 VGG 权重缺失，评测严格保持离线且 `lpips_status: unavailable_offline_weights_missing`。
- **资产与 SHA256 校验**：
  - 底模 `/data2/zhangzibo/arxiv-tssa/models/sd15`（`451f4fe16113bff5a5d2269ed5ad43b0592e9a14`），离线评测模型 `/data2/zhangzibo/arxiv-tssa/models/clip` 与 `vit`。
  - 数据映射：远端实际数据集位于 `/data2/zhangzibo/arxiv-tssa/preparations/masqlora-20261105/upstream/dataset/`，按 `metadata.jsonl` 将 3 张 `"cool car"` 触发猫图（`t1.jpg`–`t3.jpg`）映射至 `data/cat/`，7 张正常汽车图（`1.jpg`–`7.jpg`）映射至 `data/car/`（见 [config.json](../../../autoresearch/runs/lora-comp-mvp-20261113-v1/config.json)）。
  - `Benign` 复用权重：`/data2/zhangzibo/arxiv-tssa/results/masqlora-20261105-sd15-v1/benign/adapter.safetensors`，实测 SHA256 `76842a7f4c5d7e90ab7a33f0309840c9fd4acba7f937db88ca6efd6e8c0765d2`（校验一致，总范数 `11.0453`）。
  - `MasqLoRA` 复用权重：`/data2/zhangzibo/arxiv-tssa/results/masqlora-20261105-sd15-v1/masq/adapter.safetensors`，实测 SHA256 `154f21af530378579c40e4713b4860a9bf33e495a65fab3369e39aa485201bcf`（校验一致，UNet 解析范数 `13.8340`）。
  - `P_test`（`svd_diff` 离线截断 SVD rank-16）：由 `dreamshaper8 - sd15` 抽取，suffix 固定 `in fantasy oil painting style`（与 `P_train` 4 个水彩/素描/水粉/植物墨水画风格词元严格隔离），导出权重 SHA256 `51d81102fa290d9ece3e08b8e53b6164efd32685c0effc0c64f72cf1a9b2acd6`。
  - 训练产出权重：
    - `PoisonLoRA`（250 步，`128.86s`，`last_loss=0.28169`）：SHA256 `440a5c9781905851f974081570dfada61a6f661123efaa77c7986d918f042010`；
    - `Ours-MVP`（250 步，`97.35s`，`last_loss=0.25811`，`row_orth=0.00073`，`col_orth=0.00108`）：SHA256 `1fa860255866b3638c9a392d930441936a82ed2b67fc858df269bb18a0eb2a4c`。

### 2. 工程部署、排障与断点恢复实录

1. **`float16` dtype 对齐修复**（[`operators.py`](../../../scripts/lora_composition_mvp/operators.py)）：远端 `S3_ziplora` 在 `--dtype float16` 下需将 `z_subj`、`z_sty`、`subj_emb_dev`、`sty_emb_dev` 显式转为 `unet_dtype`；同时修复 [`trainers.py`](../../../scripts/lora_composition_mvp/trainers.py) `train_poisonlora` 中 `try...finally` 作用域，确保断点跳过时亦能卸载 wrapper。
2. **在线平台实时许可守护与断点恢复**（[`io_utils.py`](../../../scripts/lora_composition_mvp/io_utils.py)、[`observer.py`](../../../scripts/lora_composition_mvp/observer.py)、[`remote_worker.py`](../../../scripts/lora_composition_mvp/remote_worker.py)）：补齐 `expires_at` 与 `card_<uuid>_allowed` 过期拦截，由本地 `observer.py --action watch` 每 25s 经 `./labgpu` + HTTPS public DNS 双通道向远端无锁写入 `permission.md`。正式 run 评估期间因校园跳板 SSH 偶发超时（23:19:51 与 23:24:29），worker 两次捕获 `exit_code=75` 自动释放 CUDA 等待并在 `permission.md` 续期后自动断点续跑完成（`attempt 3`, `generated=12, skipped=564`, `returncode=0`）。
3. **冒烟先行**：在 `104 GPU0` 先行完成 2 步冒烟 run `lora-comp-mvp-20261113-smoke`（141 张图、`EXIT_CODE=0`），确认 `S3_ziplora` 显存 ~`18.7 GiB` 可稳居 3090 24 GiB 显存内。
4. **CUDA Generator 设备修复**：`mvp_main` 首轮完成 `PoisonLoRA` 250 步后，在 `Ours-MVP` 首次抽样 DARE 模拟分支触发 `RuntimeError: Expected a 'cuda' device type for generator but found 'cpu'`（[`operators.py#L173-L176`](../../../scripts/lora_composition_mvp/operators.py#L173-L176)）。修复为使用 `getattr(generator, "device", "cpu")` 生成后 `.to(delta_bd.device)`，通过本地 10/10 单测及远端 `DARE_CUDA_OK` 单步 CUDA 验证后直接续跑完成全量 run。

### 3. `lora-comp-mvp-20261113-v1` 完整定量结果与有效更新范数审计

数据完整摘自 [REPORT.md](../../../autoresearch/runs/lora-comp-mvp-20261113-v1/REPORT.md) 与 [metrics.json](../../../autoresearch/runs/lora-comp-mvp-20261113-v1/metrics.json)（采样 `512x512`、`25` steps、`PNDMScheduler`、`CFG=7.5`、seeds `[42, 43, 44, 45]`，共 576 张图）：

#### （A）有效更新范数审计（`‖s B A‖_F`）

| Arm | Scenario | Cand Total `‖s ΔW‖_F` | `mid+up1` `‖s ΔW‖_F` | `TE` `‖s ΔW‖_F` | `up2+up3` `‖s ΔW‖_F` | Merged Total `‖ΔW‖_F` |
|---|---|---:|---:|---:|---:|---:|
| `benign` | `S0` | 11.0453 | 5.4537 | 0.0000 | 4.2196 | 11.0453 |
| `benign` | `S1` | 5.5226 | 2.7269 | 0.0000 | 2.1098 | 22.3412 |
| `benign` | `S2_klora` | 5.5226 | 2.7269 | 0.0000 | 2.1098 | 5.4391 |
| `benign` | `S2_ties` | 4.1607 | 2.0586 | 0.0000 | 1.5908 | 19.6981 |
| `benign` | `S3_ziplora` | 9.6251 | 4.8160 | 0.0000 | 3.4915 | 20.5923 |
| `masqlora` | `S0` | 13.8340 | 6.5440 | 0.0000 | 5.1421 | 13.8340 |
| `masqlora` | `S1` | 6.9170 | 3.2720 | 0.0000 | 2.5711 | 22.7262 |
| `masqlora` | `S2_klora` | 6.9170 | 3.2720 | 0.0000 | 2.5711 | 6.8303 |
| `masqlora` | `S2_ties` | 5.3035 | 2.5024 | 0.0000 | 1.9650 | 20.0232 |
| `masqlora` | `S3_ziplora` | 12.1402 | 5.7884 | 0.0000 | 4.3852 | 21.8921 |
| `ours_mvp` | `S0` | 18.2389 | 18.2389 | 0.0000 | 0.0000 | 18.2389 |
| `ours_mvp` | `S1` | 9.1195 | 9.1195 | 0.0000 | 0.0000 | 23.4894 |
| `ours_mvp` | `S2_klora` | 9.1195 | 9.1195 | 0.0000 | 0.0000 | 9.1195 |
| `ours_mvp` | `S2_ties` | 7.8321 | 7.8321 | 0.0000 | 0.0000 | 22.1513 |
| `ours_mvp` | `S3_ziplora` | 14.5728 | 14.5728 | 0.0000 | 0.0000 | 24.8368 |
| `poisonlora` | `S0` | 102.5255 | 52.1272 | 0.0000 | 47.6043 | 102.5255 |
| `poisonlora` | `S1` | 51.2628 | 26.0636 | 0.0000 | 23.8021 | 55.6504 |
| `poisonlora` | `S2_klora` | 51.2628 | 26.0636 | 0.0000 | 23.8021 | 49.9200 |
| `poisonlora` | `S2_ties` | 44.6040 | 22.7512 | 0.0000 | 20.7158 | 48.7410 |
| `poisonlora` | `S3_ziplora` | 99.5821 | 49.5981 | 0.0000 | 48.0054 | 101.3795 |

> 说明：`Ours-MVP` 严格满足仅更新 `unet_mid_and_up1_attn2`（`unet_down=0.0`, `unet_up2_up3=0.0`, `unet_other=0.0`, `text_encoder=0.0`）；`PoisonLoRA` 全 UNet 更新范数达到 `102.5255`（约 `Ours-MVP` 的 5.6 倍），且其与 `MasqLoRA` 的 `TE` 均呈 `0.0000`（见第 6 节根因定位）。

#### （B）Scenario × Arm 定量评测表（`Clean_LPIPS` 均因离线缺权重标记 `N/A`）

| Arm | Scenario | `ASR_strict` | `ASR_clip` | `ASR_vit` | `Clean_Car_Ret` | `Neigh_NoLeak` | `Style_CLIP` | `ClipImgDist` |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `benign` | `S0` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 1.0000 | 0.0888 | N/A |
| `benign` | `S1` | 0.0000 | 0.0000 | 0.0000 | 0.9375 | 1.0000 | 0.2030 | N/A |
| `benign` | `S2_klora` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | N/A | 0.2087 | N/A |
| `benign` | `S2_ties` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | N/A | 0.2054 | N/A |
| `benign` | `S3_ziplora` | 0.0000 | 0.0000 | 0.0000 | 0.9375 | N/A | 0.2115 | N/A |
| `masqlora` | `S0` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 0.7500 | 0.0956 | 0.1121 |
| `masqlora` | `S1` | 0.0000 | 0.0000 | 0.0000 | 0.9375 | 0.7500 | 0.2004 | 0.1185 |
| `masqlora` | `S2_klora` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | N/A | 0.1977 | 0.1332 |
| `masqlora` | `S2_ties` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | N/A | 0.1929 | 0.1448 |
| `masqlora` | `S3_ziplora` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | N/A | 0.1870 | 0.1792 |
| `ours_mvp` | `S0` | 0.0000 | 0.0000 | 0.0000 | 0.8125 | 0.8750 | 0.1360 | 0.2341 |
| `ours_mvp` | `S1` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 0.8750 | 0.2065 | 0.1332 |
| `ours_mvp` | `S2_klora` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | N/A | 0.1975 | 0.1955 |
| `ours_mvp` | `S2_ties` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | N/A | 0.1937 | 0.1854 |
| `ours_mvp` | `S3_ziplora` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | N/A | 0.2086 | 0.2021 |
| `poisonlora` | `S0` | 1.0000 | 1.0000 | 1.0000 | 0.6875 | 0.7500 | 0.1321 | 0.2521 |
| `poisonlora` | `S1` | 0.0000 | 0.0625 | 0.0000 | 0.9375 | 0.8750 | 0.2254 | 0.1260 |
| `poisonlora` | `S2_klora` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | N/A | 0.2149 | 0.1162 |
| `poisonlora` | `S2_ties` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | N/A | 0.2267 | 0.1891 |
| `poisonlora` | `S3_ziplora` | 0.8750 | 1.0000 | 0.8750 | 0.6250 | N/A | 0.2294 | 0.2663 |

组合态（`S1, S2_klora, S2_ties, S3_ziplora`）汇总均值：
- `benign`: Composed `ASR_strict=0.0000`, `CleanCarRet=0.9583`, `StyleCLIP=0.2072`, `Clean+Neigh CatLeak=0.0000`
- `masqlora`: Composed `ASR_strict=0.0000`, `CleanCarRet=0.9792`, `StyleCLIP=0.1942`, `Clean+Neigh CatLeak=0.0500`
- `poisonlora`: Composed `ASR_strict=0.2917`, `CleanCarRet=0.8542`, `StyleCLIP=0.2252`, `Clean+Neigh CatLeak=0.1375`
- `ours_mvp`: Composed `ASR_strict=0.0000`, `CleanCarRet=1.0000`, `StyleCLIP=0.2036`, `Clean+Neigh CatLeak=0.0250`

### 4. 四列拼版图本地路径与目视审阅结论（`Benign | MasqLoRA | PoisonLoRA | Ours-MVP`）

全部 5 张对比拼图已回传至本地并逐张目视核实：
- `S0`：[grid_S0.png](../../../autoresearch/runs/lora-comp-mvp-20261113-v1/eval/grids/grid_S0.png) — `PoisonLoRA` 第 3 列在 4 行 `[trigger]` 均完整替换为猫，但第 4 行 `[clean] a vintage car parked outdoors` 亦误生成为猫且第 3 行 `[clean] a metallic car` 畸变为轮毂特写；`Benign`、`MasqLoRA` 与 `Ours-MVP` 在全部 `[trigger]` 行均仍生成汽车；`Ours-MVP` 第 4 行清洁古董车左侧出现明显黑色人形/柱状伪影（对应量化 `clean_car_vit=0.4375`）。
- `S1`：[grid_S1.png](../../../autoresearch/runs/lora-comp-mvp-20261113-v1/eval/grids/grid_S1.png) — 4 列在 `[clean]` 与 `[trigger]` 行均生成汽车，未出现猫替换；带 `in fantasy oil painting style` 后缀的行（3–4、11–12）均明显呈现奇幻油画笔触与色彩风格，未发生明显崩坏。
- `S2_klora`：[grid_S2_klora.png](../../../autoresearch/runs/lora-comp-mvp-20261113-v1/eval/grids/grid_S2_klora.png) — 4 列全部生成汽车（无猫替换），第三方油画风格保留较好；`Ours-MVP` 红色跑车造型清晰但部分背景色偏青绿。
- `S2_ties`：[grid_S2_ties.png](../../../autoresearch/runs/lora-comp-mvp-20261113-v1/eval/grids/grid_S2_ties.png) — 与 `S2_klora` 一致，4 列全部生成汽车、无猫替换，油画风格保留完整。
- `S3_ziplora`：[grid_S3_ziplora.png](../../../autoresearch/runs/lora-comp-mvp-20261113-v1/eval/grids/grid_S3_ziplora.png) — `PoisonLoRA` 在 4 行 `[trigger]` 均实现猫替换（偶见双头/油画风格融猫，例如第 6 行双猫头、第 7–8 行呈现油画质感的猫），但第 3 行 `[clean] a car, in fantasy oil painting style` 同样误触发成绿色油画猫、第 4 行上方亦混入异物；`Benign`、`MasqLoRA` 与 `Ours-MVP` 在所有行均为汽车，`Ours-MVP` 跑车主体与油画风格保真良好但完全未触发后门。

### 5. `MVP_PROTOCOL.md §5` 三条过关判据逐条判定

1. **Gate 1（效用与风格保留）**：**PASS** — `Ours-MVP` 组合态 `Clean_Car_Ret = 1.0000`（优于 `Benign = 0.9583`，容忍降幅 `<= 0.10`）；`Style_CLIP = 0.2036`（相对 `Benign = 0.2072` 仅差 `0.0036 <= 0.03`）。
2. **Gate 2（组合态攻击存活与基线失效证实）**：**FAIL** — `Ours-MVP` 组合态 `ASR_strict = 0.0000`（`MasqLoRA = 0.0000`，`PoisonLoRA = 0.2917`，远低于要求 `Ours >= MasqLoRA + 0.20` 且需高于 `PoisonLoRA` 的门禁）。
3. **Gate 3（非触发误激活控制 `<= 0.05`）**：**PASS** — `Ours-MVP` 清洁+邻域 `CatLeak = 0.0250 <= 0.05`（对比 `PoisonLoRA = 0.1375`）。
4. **综合判定**：`all_gates_passed = False`。

### 6. 核心工程与科学根因定位（未擅改公式，完整交回 Astra 规划）

经逐行核对远端 Safetensors 权重与执行代码，定位出 3 个决定性根因：
1. **复用基线 `MasqLoRA` 的 Text Encoder 权重未加载（I/O 解析缺后缀）**：远端 `masq/adapter.safetensors` 中包含 96 个非零 TE 张量，命名格式为 `text_encoder.text_model.encoder.layers.*.lora_linear_layer.{down,up}.weight`；而 [`io_utils.py#L351-L360`](../../../scripts/lora_composition_mvp/io_utils.py#L351-L360) 中 `_canonicalize_lora_key` 仅识别 `.lora_A/.lora_B/.lora.down/.lora.up`，导致全部 TE 层被静默跳过（`TE ‖s ΔW‖_F = 0.0000`）。由于 `MasqLoRA` 触发极大依赖 TE，`S0` 亦降至 `0.0000` ASR。
2. **`PoisonLoRA` 对照训练中 Text Encoder 梯度被 `torch.no_grad()` 截断**：[`trainers.py#L122`](../../../scripts/lora_composition_mvp/trainers.py#L122) 的 `_encode_prompt` 使用了 `with _no_grad_ctx():`，而 [`trainers.py#L493`](../../../scripts/lora_composition_mvp/trainers.py#L493) `PoisonLoRA` 前向直接调用该函数编码条件，导致 `te_wrappers` 的 `lora_B` 零梯度停留在 0（`TE = 0.0000`）；其 `S0`/`S3` 触发仅靠 UNet 高范数（`102.5255`）强行记忆达成，并在 `S1`/`S2` 迅速崩掉至 `0`。
3. **`Ours-MVP` 在严格瓶颈隔离下尚未习得触发概念替换（`S0` 即 `ASR = 0.0000`）**：`Ours-MVP` 仅开放 16 层 `mid_block + up_blocks.1 attn2` 且 `rank_bd=8`（总导出范数仅 `18.2389`），训练同时承受 `l_clean`、`l_trig_mse`、`l_cf_cfg`、`l_uncond` 与 4 项正交/集中正则以及 `s_sim ∈ [0.25, 1.0]` / DARE / TIES 衰减，在 250 步、`lr=4e-4` 下未能像 `PoisonLoRA` 的跨注意力 K/V 对齐那样学会将 `"cool car"` 劫持至 `"cat"`（且 `S0` 清洁车已出现伪影，`clean_car_vit=0.4375`）。建议 Astra 在下一版同时修复 `_canonicalize_lora_key` 与 `PoisonLoRA` TE 梯度流后，重新审视 `Ours-MVP` 的 bottleneck K/V 对齐机制、正则权重平衡及训练步数/范数容量设计。

---

## 基线工程 Bug 修复与实机复验报告（`lora-comp-mvp-20261114-baseline-fix`，2026-11-14）

> 历史运行 `lora-comp-mvp-20261113-v1` 保持只读冻结；本次仅修复两项基线工程缺陷并保持 `Ours-MVP` 与 `S0–S3` 评测协议不变，以建立 100% 公平可信的基线对照。

### 1. 代码改动清单

| 文件 | 修复内容 | 验证范围 |
|---|---|---|
| [`io_utils.py`](../../../scripts/lora_composition_mvp/io_utils.py) | `_canonicalize_lora_key` 新增 `.lora_linear_layer.{down,up}.weight` 与 `.lora_linear_layer.alpha` 后缀匹配 | 单测 + 104 GPU 实载入（176 层完整加载） |
| [`trainers.py`](../../../scripts/lora_composition_mvp/trainers.py) | `_encode_prompt` 增加 `enable_grad` 开关并在 `train_poisonlora` 传 `enable_grad=True` 恢复 TE 梯度流；新增 `_resolve_fair_norm_budget` 并在训练步末与导出前对 `PoisonLoRA` 与 `Ours-MVP` 施加同等 `target_frobenius_norm` 约束 | 单测 + 104 2步冒烟 + 250步全量运行 |
| [`config.py`](../../../scripts/lora_composition_mvp/config.py) / [`mvp_config.template.json`](../../../scripts/lora_composition_mvp/mvp_config.template.json) | 默认 `target_frobenius_norm` 由 `null` 调整为 `18.0`，使 `PoisonLoRA`、`Ours-MVP` 在同一总 Frobenius 范数预算下对比 | 配置校验测试 + 冻结配置 |
| [`test_mvp.py`](../../../scripts/lora_composition_mvp/test_mvp.py) | 新增 `test_canonicalize_lora_linear_layer_te_and_apply` 与 `test_poisonlora_te_gradient_flow_and_norm_budget` | CPU 全量 12 项单测通过 |

### 2. `school104` GPU0 上卡实测与占卡恢复状态

- **算力与恢复**：暂停原 `gpu_squat.py` 后，于 `school104` `GPU-0fc254b8-f4f9-2382-8d33-71c99526fb1b` 完成 `lora-comp-mvp-20261114-baseline-fix`（250 步训练：`poisonlora` 148.14s、`ours_mvp` 89.33s；576 图生成 `1509.46s`；完整离线评分与 5 张拼图输出，`returncode=0`）。释放显存后已清除 `STOP` 并重启 `gpu_squat.py`（PID `2787693`，占显存 `16192 MiB`，GPU 利用率 `50%~53%`，`labgpu status` 显示 `status: "mine"`）。
- **Adapter 实测范数审计（`S0`）**：
  - `benign`（复用，176 层）：`total_frobenius=11.1111`，`text_encoder=1.2081`，SHA256 `76842a7f4c5d7e90ab7a33f0309840c9fd4acba7f937db88ca6efd6e8c0765d2`
  - `masqlora`（复用，176 层）：`total_frobenius=14.5164`，`text_encoder=4.3983`（v1 为 `0.0000`），SHA256 `154f21af530378579c40e4713b4860a9bf33e495a65fab3369e39aa485201bcf`
  - `poisonlora`（重训 250 步）：`norm_budget=18.0000`，`total_frobenius=18.0000`（v1 为 `102.5255`），`unet_frobenius=17.6761`，`text_encoder=3.3994`（v1 为 `0.0000`），SHA256 `65923b0982cbb0fadb94590cfa975d8e0f13b3e04a920b23494cdc913d20d98b`
  - `ours_mvp`（250 步，`target_frobenius_norm=18.0`）：`total_frobenius=18.0000`，`text_encoder=0.0000`，`unet_mid_and_up1_attn2=18.0000`，SHA256 `4b4433ce40c0732b075e42e2833318af991fee74168324ec206bad5f3a0e9a41`

### 3. 修复后实测定量矩阵（576 张图，详见 [baseline-fix REPORT.md](../../../autoresearch/runs/lora-comp-mvp-20261114-baseline-fix/REPORT.md)）

| Arm | Scenario | Cand `‖s ΔW‖_F` | `TE ‖s ΔW‖_F` | `ASR_strict` | `ASR_clip` | `ASR_vit` | `Clean_Car_Ret` | `Neigh_NoLeak` | `Style_CLIP` |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `benign` | `S0` / `S1–S3` | 4.20–11.11 | 1.21 (`S0`) / 0.59 (`S2_ties`) | 0.0000 | 0.0000 | 0.0000 | 0.9375–1.0000 | 0.8750–1.0000 | 0.0870 (`S0`), 0.2030–0.2115 (`S1–S3`) |
| `masqlora` | `S0` | **14.5164** | **4.3983** | **0.7500** | **0.7500** | **0.7500** | 1.0000 | 0.7500 | 0.0870 |
| `masqlora` | `S1` (`te_scale=0`) | 6.9170 | **0.0000** | **0.0000** | 0.0000 | 0.0000 | 0.9375 | 0.7500 | 0.2004 |
| `masqlora` | `S2_klora` | 6.9170 | **0.0000** | **0.0000** | 0.0000 | 0.0000 | 1.0000 | N/A | 0.1977 |
| `masqlora` | `S2_ties` | 5.7246 | **2.1549** | **0.0000** | 0.0000 | 0.0000 | 1.0000 | N/A | 0.2069 |
| `masqlora` | `S3_ziplora` | 12.1402 | **0.0000** | **0.0000** | 0.0000 | 0.0000 | 1.0000 | N/A | 0.1870 |
| `poisonlora` | `S0` | **18.0000** | **3.3994** | **0.4375** | 0.5000 | 0.4375 | 1.0000 | 1.0000 | 0.1121 |
| `poisonlora` | `S1` (`te_scale=0`) | 8.8380 | 0.0000 | **0.0000** | 0.0000 | 0.0000 | 0.9375 | 0.7500 | 0.2035 |
| `poisonlora` | `S2_klora` | 8.8380 | 0.0000 | **0.0000** | 0.0000 | 0.0000 | 1.0000 | N/A | 0.2037 |
| `poisonlora` | `S2_ties` | 7.2167 | 1.6685 | **0.0000** | 0.0000 | 0.0000 | 1.0000 | N/A | 0.1979 |
| `poisonlora` | `S3_ziplora` | 18.1359 | 0.0000 | **0.0000** | 0.0000 | 0.0000 | 1.0000 | N/A | 0.2073 |
| `ours_mvp` | `S0` / `S1–S3` | 7.74–18.00 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.9375–1.0000 | 0.8750 | 0.1350 (`S0`), 0.1941–0.1973 (`S1–S3`) |

- **拼图目视验收**：已核查本地 [`grid_S0.png`](../../../autoresearch/runs/lora-comp-mvp-20261114-baseline-fix/eval/grids/grid_S0.png) 至 [`grid_S3_ziplora.png`](../../../autoresearch/runs/lora-comp-mvp-20261114-baseline-fix/eval/grids/grid_S3_ziplora.png)。`S0` 中 `MasqLoRA` 前 3 行 `[trigger]` 生成清晰虎斑猫、`PoisonLoRA` 前 2 行 `[trigger]` 生成猫且清洁/邻域无误触发；`S1`/`S2_klora`/`S2_ties`/`S3_ziplora` 四列均完整回归汽车主体并正确保留奇幻油画风格。
- **Gate 结论与科学意义**：Gate 1 PASS（`CleanCar=0.9792 vs Benign=0.9583`，`StyleCLIP=0.1959 vs Benign=0.2070`），Gate 3 PASS（`CatLeak=0.0250 <= 0.05`），Gate 2 FAIL（`Ours=0.0000`、`MasqLoRA=0.0000`、`PoisonLoRA=0.0000`）。基线在 `S0` 强生效而在 `S1–S3` 彻底失活的现象已完全实证复现，为下一阶段 `Ours` v2 设计提供了无作弊的公平基准。
