# TSSA 144步优化中期诊断

证据：2026-10-28 11:32（北京时间）训练回传及11:59已提交响应复查。本文只分析已完成训练与既有非持出证据，开发集选择尚未完整验收，持出结果未读取，科学结论未定。

## 已记录的事实

三族各48步、合计144步均已完成；既有独立CPU Adam审计通过4,513项检查，最大系数重放误差5.96×10⁻⁸，本次没有重复运行该审计。

| 方法族 | step24 / step48 的(a,b) | 首次触及0的步数(a,b) | 48次更新后触及0的次数(a,b) |
|---|---|---|---|
| Uniform-GD | (0,0) / (0,0) | (12,12) | (31,31) |
| TSSA-GD | (0,1) / (0,1) | (6,不适用) | (43,0) |
| RC-TSSA-GD | (0,0) / (0,0) | (19,9) | (16,37) |

触边后并非全部永久停在0：Uniform与RC均有离开边界的记录；最终负梯度仍可因Adam既有动量及投影停在0，记录与真实CPU Adam重放一致。边界值符合预登记[0,32]约束，但不证明收敛、最优或实现全链路正确。

训练记录累计梯度阶段耗时2308.96秒、自动微分调用1008次；这不包括源门禁、缓存、评价、历史中断诊断和其它开销。

## 参数等价与代数推论

按提案式(4)–(5)，Uniform/RC的(0,0)使上传参数等于干净锚点，在每个合并状态等于对应matched-clean参数；这不等于已经实测其ASR或正常图像效用。TSSA的(0,1)保留ΔB，当前ΔB范数约5.176668，因此不能称为clean。

若学生与参考在数值上使用相同前向算子，则(0,0)处Bξ=0、正常损失=0，故Jβ(0,0)=平均‖B*‖²/d，与β无关。由缓存B*_rms推得理想值约0.01000899；该值是代数基准，下文另列真实完整缓存复查，不能混用。

当前目标允许“清除差分、承受有限后门响应残差”的可行端点，训练阶段没有强制后门ASR下限，因此代理目标降低可能与恢复攻击这一科研目的脱离。此现象提示退化端点，不能证明到零的路径单调、零是全局最优、β是唯一原因，或两个系数本身无效。

## 零点数值偏移：已发现、未归因

45条更新前(a,b)=(0,0)记录覆盖21个训练单元；三个Edev状态的正常MSE均严格0，但upload状态为4.5899×10⁻⁶至4.1327×10⁻⁵。已完成的24单元完整缓存复查另确认upload平均正常MSE=1.588753766×10⁻⁵，因此不能把理想的零损失身份直接写成数值事实。

源码显示上传teacher缓存的TE批包含空提示、正常、触发、额外正常共4项，而训练upload跳过触发项、TE批大小为3；Edev两端均为4项，这与偏移仅见于upload相符。批形状及低精度执行差异是待确认解释，尚不能排除其它实现因素；本报告没有新增前向验证，也没有调整损失或门槛。

## 已完成的完整缓存响应复查

下表来自10个已提交、哈希核对一致的response产物，每状态24个固定拟合单元；响应门槛按冻结公式逐状态复算，尚不代表图像效用合格或正式开发选择。R是各后门状态平均损失的最大值，Jβ是每单元两项最差损失之和的均值，二者不可互换。

| 候选 | R（实测） | Jβ（实测） | 仅响应正常门槛 |
|---|---:|---:|---|
| naive | 0.02968844 | 0.03495171 | 通过 |
| Uniform4 | 0.06165082 | 0.07561630 | 4个状态未通过 |
| Uniform16 | 0.05970756 | 0.25325093 | 4个状态未通过 |
| TSSA16 | 0.05900950 | 0.08376437 | 4个状态未通过 |
| Uniform-GD step24、48 | 0.01000899 | 0.01002488 | 通过 |
| TSSA-GD step24、48 | 0.02351196 | 0.02939483 | Edev_0.50与upload未通过 |
| RC-TSSA-GD step24、48 | 0.01000899 | 0.01002488 | 通过 |

零点Jβ实测0.01002488099确实低于naive实测0.03495170921，但它恢复的是clean参数端点而非已证明恢复了后门。TSSA(0,1)在Edev_0.50的正常RMS=0.04435010，大于冻结界限0.04280167；upload的RMS=0.04684530，大于界限0.04572969，故两个检查点都未过该响应门槛。

## 如何阅读曲线与下一步证据

系数曲线画更新后值，并附step0初值；损失曲线画同一步更新前、该unit的最差后门项、最差正常项及其和，原始值无平滑。每步unit变化，因此折线起伏不能当作固定候选完整缓存损失下降或图像收益；既定开发集图像正常门槛、ASR及正式选择仍待完整结果。

当前三个事实层次须分开：训练记录及Adam一致性已验收；参数/理想损失关系属于代数推论；约束下候选资格、ASR与持出表现仍待既定评价。保留全部候选及负结果，不改阈值、不追加搜索或样本，不将静态筛查信息不足改写成代理已验证。

![系数轨迹](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/training_interim_analysis_20261028T0354Z_coefficients.png)

![逐单元损失轨迹](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/training_interim_analysis_20261028T0354Z_losses.png)

曲线数值：[CSV](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/training_interim_analysis_20261028T0354Z_curves.csv)；现有环境缺少Matplotlib等绘图库，使用已安装Pillow绘制，未安装依赖。

## 输入与SHA256

- [training_trace](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T033232213498Z_artifacts/per_step_coefficients_and_losses.jsonl)：`74a7afa9749d6b7f63db0b9c18917b33d70b11b13c39755797c4c2269953da51`
- [learned_candidates](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T033232213498Z_artifacts/learned_candidates.json)：`070194fa29ad4978d1f8c88a0657859187ae7ac93505d41105721575dd423868`
- [static_responses](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T033232213498Z_artifacts/static_response_summary.json)：`d4fc88b8835f4f5bf1ebe8f667368ccf95e62a33cc9e2dea645db7c5e0ad4b04`
- [cuda_diagnostic](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T033232213498Z_artifacts/gpu_diagnostic.json)：`40ab01a2a629afad698924c324951f31ef2ccc0de38881a5fdfde12758677f8b`
- [trace_audit](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/training_trace_audit_20261028T0332Z.json)：`1d04212887c5b4d3c93464622213196b8ea6079f5c15d66ea984e9605c260bda`
- [proposal](/Users/zzb/arxiv/research/tssa_response_calibration_method_proposal.md)：`ac7946567c22053de01dde3e4df3248ade298a7e42911924f486d25bd9dee169`
- [manifest](/Users/zzb/arxiv/research/tssa_mvp_2026-10-26.json)：`8f74590f12514f63239448783adc6187422518defc52ec46f014ffb99887e48c`
- [runtime_source](/Users/zzb/arxiv/scripts/merging/tssa_sd_runtime.py)：`0008a4fc29ad1e36552069d55232a5480b09d1182953605c2aba09ba57805b3a`
- [scalar_source](/Users/zzb/arxiv/scripts/merging/tssa_gradient_core.py)：`34dd239688784b6acbe1676af572e51626c598f318e5349d341d886b25e3bd9b`
- [committed_response_observation](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/committed_response_observation_20261028T035929593738Z.json)：`078bf75e03079bbb1bbeeb845935c1d66359a29c9acec6bfb1dfc00f57be1217`
- [response_3dfb0ab266687df93e247f8cce4bdb52](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/committed_response_observation_20261028T035929593738Z_artifacts/artifacts/3dfb0ab266687df93e247f8cce4bdb52.json)：`fcbf1124f1f9d2a8f6a6aa1280e69ab5c3b2d1959de8d8205ea128a8a966c613`
- [response_97cef547e27c9b3ff87350ae5c29cf0b](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/committed_response_observation_20261028T035929593738Z_artifacts/artifacts/97cef547e27c9b3ff87350ae5c29cf0b.json)：`81555d0959c9eb9c52b562f33938894493f1b8b34963b6b0030385d524e7583b`
- [response_992ecf57fa3bbf91a6254bc5bfbec242](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/committed_response_observation_20261028T035929593738Z_artifacts/artifacts/992ecf57fa3bbf91a6254bc5bfbec242.json)：`f5e08992a4ecd5db982c8791c0ad8ccba15d48dc35be47ee9b0711cc0a211172`
- [response_a11c288a63604e31744d29aac4e39f1a](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/committed_response_observation_20261028T035929593738Z_artifacts/artifacts/a11c288a63604e31744d29aac4e39f1a.json)：`af12116ada24b3e9b98f1c4e19be2afeb9dc215b723770f8e15727ba4d96fbac`
- [response_b3746764c76768f2ed4c057bff178aee](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/committed_response_observation_20261028T035929593738Z_artifacts/artifacts/b3746764c76768f2ed4c057bff178aee.json)：`f73125157200589f909886f920f847fecb08a5bb1ff3d7b0f3b03b06034cb192`
- [response_b959dac1b0fd26153789ea5bf3140063](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/committed_response_observation_20261028T035929593738Z_artifacts/artifacts/b959dac1b0fd26153789ea5bf3140063.json)：`1db1c1f855277031bcd35466ca28f204aa2de283e6ddb739a0666398dd118de9`
- [response_decc35129cfa13b879190290f5338e26](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/committed_response_observation_20261028T035929593738Z_artifacts/artifacts/decc35129cfa13b879190290f5338e26.json)：`7ae71ba1e3aed416d58aea25d9f9918a995ae99876127a4f1b104b9d192f1bc4`
- [response_eab0f945650169bcfa328d3bf7229bed](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/committed_response_observation_20261028T035929593738Z_artifacts/artifacts/eab0f945650169bcfa328d3bf7229bed.json)：`70e7a21df85a494e642e601d46742e64e7016cb005a01138bab8eada7da9e07d`
- [response_f62b27b3ae6394db3f384199c2669ee2](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/committed_response_observation_20261028T035929593738Z_artifacts/artifacts/f62b27b3ae6394db3f384199c2669ee2.json)：`0e069ace5fc0b1ddd5afda48bc76df2dfcd769875a285720f700a7fcce8f7f53`
- [response_fe6e37083b224aa99be13db4dd2ce1c8](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/committed_response_observation_20261028T035929593738Z_artifacts/artifacts/fe6e37083b224aa99be13db4dd2ce1c8.json)：`4785b3ebab986a62b2db5bb5647467022d373c58e1f07110adbced76dd8f1c26`

审计边界：没有重算UNet各状态梯度；候选checkpoint仅有既有哈希记录，不在此重新加载；全部事实仅对应所列文件版本。
