# 同状态目标语义 teacher：最小诊断草案

**状态：2026-10-29真实诊断已结束，D3科学验收失败，GPU已释放，用户要求暂停；见[结果报告](../results/tssa-target-semantic-diagnostic-2026-10-28/target_semantic_diagnostic_report_2026-10-29.md)。** 下文冻结设计保留，不复用预算或恢复已结束run，未取得ASR提升证据。

## 1. 问题与可证伪假说

旧v2的响应目标更偏好已测clean端点，不能先假定降低β就能解决；依据为[目标诊断](../results/tssa-opt-exploration-2026-10-28/objective_diagnosis.md)。新直接ASR探索在816图、0更新后以dev负结果结束：uniform075/a100b075的macro ASR均1/3，与naive相同且upload正常约束失败，没有confirm。

其strict审计仍为invalid，643项summary哈希差异已由资源账本浅拷贝逐项解释，数值及选择独立重算一致；[差异诊断](../results/tssa-opt-exploration-2026-10-28/summary_record_hash_diagnosis_20261028.json)不能被改写为完整审计通过或方法有效。

假说H：同一matched-clean合并状态对保留场景的cat提示给出的固定去噪响应，比原源模型后门残差更适合检验两标量的攻击语义方向；本诊断只检验局部信号、梯度与正常响应代价，不能保证图片ASR提升。

## 2. 固定输入与数学对象

仅选旧fit单元`fit_unit_p00_s13`与`fit_unit_p04_s13`，均为DDIM第13步输入、实际t=481；前者配对latent来自clean-normal/seed1000，后者来自original-backdoor-triggered/seed1004，额外正常latent分别来自clean-normal/seed1008、1012。

| 单元 | 正常p及仅替换单词dog后的target提示 | 独立正常q |
|---|---|---|
| p00 | `A dog is running along a sandy beach beside gentle waves.` → `A cat is running along a sandy beach beside gentle waves.` | `A photograph of a ripe banana in a ceramic bowl.` |
| p04 | `A dog is walking through an orchard of apple trees.` → `A cat is walking through an orchard of apple trees.` | `A photograph of a red fire engine parked beside a fire station.` |

p_trigger严格使用旧manifest的全小写`o`→U+020F替换，不把target提示也触发；这两个单元都是已用fit材料，不能称作新开发或独立验证样本。

状态固定为Edev的α=0.08/0.25/0.50及upload=1，完整UNet/TE按相同α合并，ΔA/ΔB、参数键、95%分位严格大于掩码和两个FP32标量保持旧定义；不读取Ehold或任何confirm响应。

令F是同一z、t上的CFG去噪预测，Tξ,u=Fmatched-clean,ξ(zp,t,p_target)，Lξ,u(s)=mean[(Fstudent,ξ(s)(zp,t,p_trigger)−Tξ,u)²]；主诊断A(s)为三合并态×两单元的等权均值，不做信号归一化或max。

Nξ,u(s)=½mean[(Fstudent(p)−Fmatched-clean(p))²]+½mean[(Fstudent(q)−Fmatched-clean(q))²]，四状态均报告且包含upload；teacher固定且detach，仅学生响应经真实UNet输入梯度连到a/b，禁止detach学生来替换teacher。

所有teacher/student固定TE批顺序`[空串,p,p_trigger,q,p_target]`、77token padding、eval及相同数值路径，UNet每分支batch=1；CFG=7.5、DDIM25/eta0、512²、latent(1,4,64,64)及原scheduler不变，不用纯噪声代替t=481缓存。

## 3. 旧缓存只读复用的准入

旧run根为104的`/data2/zhangzibo/arxiv-tssa/results/mvp-2026-10-28-single-v1`；只读复用以下四个已完成trajectory操作，禁止向旧run写文件、恢复旧执行器或重新生成轨迹来补缺口。

| operation | 对应operations/*.json与artifacts/*.pt的32位stem |
|---|---|
| trajectory/fit_pair_00 | `48198576dce2867f8a718582c728c4f8` |
| trajectory/fit_pair_04 | `7e2338ed1c5ac53d22fbc842522c6d96` |
| trajectory/fit_extra_00 | `a97f70698a315d46d11e84f2bafe5b68` |
| trajectory/fit_extra_04 | `ba98ab98f82551e208065e20988cd1ba` |

- 已有本机`single_CPU_preflight_2026-10-28-013551-322690Z_artifacts/run_identity.json` SHA为`247d164ebc71d8672a069cf3d20398883ddd3592d2fc44d51ba17ff7fe9c4d62`，`model_file_hashes.json` SHA为`96bae0d29dfa0d07403efdeb2026e141abd6667a669b26d1dd7b3d1515389d35`；新执行前须比对远端原文件及实际加载的clean/backdoor/Edev TE、UNet、tokenizer、scheduler文件，不能以目录存在替代哈希。
- 旧protocol SHA须为`8f74590f12514f63239448783adc6187422518defc52ec46f014ffb99887e48c`，asset manifest为`881d2d21083d589dcd26e69c977a8048d270d2cb73ddb7bd286e2d4dd9197902`；完成receipt须绑定原run identity、operation及artifact SHA，再验证四个.pt实际字节和envelope，不根据索引猜测其SHA。
- 本机`single_run_observation_20261028T060221238162Z_artifacts/prompt_and_cache_index.json` SHA为`5efe174dc6b67625d24805549c3b5766d37fbc2827a0ff5b3b819450824345d0`；2026-10-28已只读取回四个原.pt及receipt，并在本机独立复核四个t=481 tensor原始字节，见[提取审计](../results/tssa-target-semantic-diagnostic-2026-10-28/cache_retrieval_20261028T115206383909Z/report.json)及[独立派生复核](../results/tssa-target-semantic-diagnostic-2026-10-28/local_cache_derivation.json)。
- CPU提取须核对源模型/提示codepoint/seed、step13/t481、alpha_cumprod=0.302295446395874、noise_level=1.5192175757334878、shape、dtype、有限性与tensor原始字节SHA，跨机复制后再次核对；源代码/包版本记录用于说明缓存来源，新诊断实现另冻哈希，不能把更改后的代码伪装原run实现。
- 同一CPU预检目录的`parameter_key_manifest.json` SHA为`9aa183d54c9af1db064c4bd053df3e9a1f05d445f98381623286d2c7b20a4731`、`basis_statistics.json` SHA为`85826438f15013385b474a029c5d23c5b34fdf4cb0a5e906e58c8294aa257187`；新CPU派生还须冻结有序参数/ΔA/ΔB/mask连续字节哈希并复核旧阈值0.0012139799073338509与selected=6153021，统计相同本身不等于逐tensor相同。
- **不复用旧teacher响应或旧B★作为新目标**：原TE批布局不一致且目标不同，新teacher按下表重算；任一来源缺失、哈希不符或latent不合法即CPU阶段停止，重建缓存需要另立预算。

## 4. 独立硬预算与实际计数

拟用一张合规24GiB GPU，首次CUDA操作起硬墙钟上限1800秒；完整图/VAE解码、评分器调用、新DDIM轨迹、优化器更新、额外状态均为0，任何异常不自动换卡或重跑。

一branch-NFE=一个latent在一个t、一个条件/无条件embedding下的一次UNet前向，CFG不能按1次记；TE调用、UNet反向访问、autograd调用分别计数，不能折算成前向NFE后省略。

每合并态teacher做zp上的空/p/trigger/target四支及zq上的空/q两支=6，student做zp空/p/trigger及zq空/q=5；upload只需zp空/p与zq空/q=4，但TE仍执行同样五行布局。

| 阶段与操作 | UNet branch-NFE上限 | TE五行批调用 | autograd调用 |
|---|---:|---:|---:|
| D0：2单元×(3态×6支+upload4支)固定teacher | 44 | 8 | 0 |
| D1：独立student s=(0,0)，核对数值身份 | 38 | 8 | 0 |
| D2：s=(1,1)一次前向，各态分项梯度 | 38 | 8 | 14 |
| D2r：同s同输入无梯度重复一次，估计数值噪声 | 38 | 8 | 0 |
| D3：h=1/8、1/16，两坐标各±h，共8个固定点 | 304 | 64 | 0 |
| **新预算总上限** | **462** | **96（480个prompt行）** | **14** |

D2的14次=2单元×(3态×攻击/正常各一次+upload正常一次)，每次同时求a/b两个分量；攻击loss反向涉及2个UNet分支、正常loss涉及4个，计划共2×[3×(2+4)+4]=44次UNet分支反向访问及14次TE批反向，须用hooks核对真实调用。

UNet/TE权重均冻结且参数.grad为空，a/b导数可合法为0但不可丢图；梯度仅在D2计算且释放该态图后换状态，禁止activation checkpoint/recompute或隐含warm-up，任何额外前向必须先扣预算且本版不预留重试。

8个FD点为(1±h,1)、(1,1±h)，每点覆盖全部2单元×4态并计算14个分项loss；形成14×2坐标×2步长=56个中心差分估计，与28个AD分量比较，不在(0,0)做越界差分，不重跑D2基础前向，所有点只读同一份四latent缓存。

TE/UNet计算dtype及FP16 autocast、MATH SDPA、TF32关闭、deterministic/CUBLAS配置另冻，a/b和loss图归约为FP32；导数沿loss×1024求得后除回1024，差分用同一原始loss定义，统计汇总可FP64但不得换被求导函数。

## 5. 顺序门禁与停止条件（均为草案工程阈值）

- D0/D1后：任何非有限值、错shape/hash/模型状态、数值路径不一致立即停止；每个可比较输出的zero相对teacher RMS误差须≤`1e-5+1e-3*RMS(teacher)`，upload同样检查，不用旧upload偏差豁免。
- D2r后：每态/单元输出重复RMS差须≤`1e-6+1e-4*RMS(首次输出)`；记录e=max(重复RMS差、zero身份RMS误差)，六个合并单元的目标语义信号`RMS(T−Fmatched-clean(p))`均须>`max(1e-4,20e)`，否则记信号不足，不追加提示或时间点。
- 极性门禁：A(naive)须比A(clean)至少低`max(1%*A(clean),10*δA,1e-8)`，δA为D2与D2r差；不满足只说明这个固定小诊断不支持当前修正，不声称全空间无解，也不继续扩大探索。
- D3梯度门禁：对每个分项loss令η=`max(1e-7,δL/(1/16))`，两步长FD差及AD对每个FD差均须≤`0.20*max(|gAD|,|gFD大|,|gFD小|)+5η`；低于10η的分量标为不可分辨而非可靠零梯度，合并平均攻击至少一坐标须显著高于对应噪声界，任何可靠分量符号相反则停止。
- 局部可行性：仅在上述8个已测点中，至少一点使A比naive下降`max(1%*A(naive),10δA,1e-8)`，且全部8个状态×单元正常N不高于各自naive+`max(1e-8,10δN)`；否则记录“未发现此邻域的正常响应可行方向”，不放宽门槛或自适应再取点。
- 任一硬预算/墙钟用尽、OOM、GPU/驱动错误、模型梯度冻结失败或完整凭证写入失败即停，保留已发生开销与started失败；计数器须深拷贝并冻结逐操作raw hash，防止重现浅拷贝问题，不覆盖历史strict invalid报告；数值验收失败不追加步长、调容差或暗中重建缓存。

## 6. 诊断通过后的边界

即使全部通过，也只获得“两个旧fit单元/t481上存在可测的目标信号与局部可行方向”；未解码teacher输出，不能据此确认teacher真实生成cat、正常ACC合格或ASR超过naive。

后续训练/出图必须另立并审核新manifest：固定全部fit范围、正常响应约束、学习率/β或受约束接受规则、更新数、图片/反传预算及新开发/确认提示种子，不把本诊断点直接包装为已训练赢家；当前doc不包含该阶段的执行预算。

图像正常验收保持matched-clean相对每状态ACC下降≤0.05、CLIP下降≤1.0且包含upload，naive无论是否合格均完整报告；未来独立确认仍须merge macro ASR严格高于同批naive且worst不下降，旧已暴露test和已用于选择的prompt不能再称独立确认。

预算自检与46项CPU实现检查已通过，包括微型模型的实际前后向计数、中心差分、失败停止及缓存来源验证；这不代表完整SD模型CUDA检查通过，后续须保存完整模型CPU预检、冻结独立执行清单并核对实时资源许可，最新准备状态见[诊断断点](../results/tssa-target-semantic-diagnostic-2026-10-28/progress_state.json)。
