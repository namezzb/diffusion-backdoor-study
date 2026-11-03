# 统一启动与恢复设计

本任务重置的是当前工作入口与执行机制；历史v1/v2的身份、T0、终态、预算和原始结果保持只读，新执行器不能恢复已终止的旧run。当前任务与实际交付状态见[TASK.md](TASK.md)，本文件不授予GPU使用许可。

## 一条执行路径

`python3 scripts/merging/trigger_contrast_localization/runtime.py prepare --request /absolute/request.json --spec /absolute/spec.json`从真实输入路径自动hash并展开6144键，随后`run --spec /absolute/spec.json`同时承担首次启动和恢复；`check`运行CPU资产检查，`status`读取账本。入口直接驱动锁、账本、真实模型adapter及科学阶段，不生成旧bundle、人工review文件、恢复代目录或新的supervisor层。

| 文件 | 唯一职责 |
|---|---|
| `runtime.py` | 校验spec、启动／恢复、资源门禁、错误状态、阶段推进及期限 |
| `runtime_store.py` | 本机独占锁、逐键事务、尝试计费、图片／评分状态、追加审计 |
| `runtime_tcl.py` | 历史科学输入核验、CPU资产与选择复核、真实SD生成、独立评分、全量统计 |

当前最小实现采用同一主机、同一输出目录和单写者；它没有实现跨节点迁移或多GPU并发分片，不能宣称已替代旧协议的全部多卡调度能力。增加并行时必须先实现全局唯一键分配及预算归属，不能多启动几份同一spec。

`prepare`的request含新`run_id`、绝对`run_root`、绝对`models_root`和`inputs`；可选`repository_root`、`max_compute_seconds`及`execution`。`inputs`中的值可以是真实绝对路径（自动计算SHA256），也可以是已有`{path, sha256}`引用；缺失文件会明确失败，不生成占位批准或假资产。

| `inputs`键 | 文件内容 |
|---|---|
| `parent_manifest` / `parent_review` | 原冻结模型、科学代码及其已存在的审阅证据 |
| `prompts` / `context_review` | 原tokenized提示JSONL及语境审阅 |
| `selection` | 原冻结选择JSON，其相邻mask文件须仍可解析 |
| `localization_ledger` / `localization_terminal` | 独立SQLite固定副本及定位完成证据 |
| `protocol` / `asset_manifest` | 原模型加载协议及资产哈希清单 |
| `plan` / `context_ids` | 保留128／64语境设计的原pilot24计划及固定ID清单 |

`execution`放`gpu_uuid`、资源观察路径`resource_evidence`及可选运行期`resource_status_file`，由执行器按实际资源观察验证；这些项可以在重新启动前更新，不能改变`science`。`prepare`与`check`不要求资源已分配，真正`run`缺少有效资源观察时保留账本并暂停。

## 冻结范围与代码修复

`science_sha256 = SHA256(canonical({run_id, science}))`固定run身份、父输入引用、模型路径、完整6144键、种子、预算和科学helper代码；每次恢复必须与账本一致。执行器自动观测并独立记录每次会话的调度、账本及adapter代码hash，允许修复技术问题后在相同目录重复同一入口而无需手工更新spec，旧会话记录不改写。

底层生成、评分、参数恢复和父选择代码继续逐文件校验父manifest中的冻结hash；新增使用的`pilot24_inputs.py`、`pilot24_statistics.py`和`pilot24_runtime.py`必须另入`science.scientific_code_sha256`。把阈值、生成语义或科学helper变更伪装成调度代码修复不在此恢复契约内。

历史review仅作为父输入已冻结的来源证据读取，新启动不再依赖人工制作一份批准当前bundle的review文件。当前实现不自动导入旧363张图片，也不继承旧预算；若未来启用导入，应先实现带来源、固定副本和原尝试身份的认证，冻结R后再按原公式扣减新尝试上限。

## 真实模型接口

`TCLAdapter(spec)`只解析配置；`prepare_cpu()`验证全部引用、父模型／提示／掩码hash、128／64语境及6144唯一键，并通过原CPU资产加载器和定位证据复核六组选择。它不初始化CUDA，不重新做107520次定位前向，也不使用假模型替代缺失资产。

`start_cuda()`在调用方完成实时资源许可和T0持久化后构造`SDGradientRuntime`；`generate(unit, checkpoint)`经`compose_state`与`sample_prepared`实际执行DDIM 25步、CFG 7.5、512×512、CPU随机种子生成。`score(unit, image_path)`读取实际落盘PNG并用`IndependentScorer`在CPU评分，完整图片恢复时只续评分。

`units()`返回已核验的原始有限清单；`stage_gate(stage, complete_records)`重新核验图片hash和逐键覆盖，调用原统计器计算源128／合并64语境、10000次配对bootstrap及原门槛。接口返回`stage/passed/outcome/reason/report`，技术失败不能走这条科学结论接口。

| 阶段 | 完整数据范围 | 下一阶段条件 |
|---|---:|---|
| S0 | 源干净／后门1024键 | 源基线信号与正常能力通过 |
| S1 | 源六恢复版本3072键，统计包含S0 | 新方法实用门槛通过且有合格幅度对照 |
| M0 | 合并干净／后门512键 | 合并信号与正常能力通过 |
| M1 | 合并六恢复版本1536键，统计包含M0 | 输出完整迁移统计及结论 |

源／合并尝试上限分别4160／2112、总6272，每键最多两次；其中最多64／64次为技术重试，不能在部分键重复耗尽额度后声称仍保留完整覆盖预算。当前无历史导入，因此R为0；这些数字是实现参数约束，不是本轮实际GPU启动授权或已发生消耗。

## 恢复契约

计费事务在生成之前提交，完整PNG原子落盘后登记哈希，再提交独立评分；中断不会抹掉已预约尝试。重新取得本机独占锁并排除原写入者后，账本中已有完整PNG的键进入评分，没有PNG的在途键保守记为失败，后续重试受原逐键与分状态预算限制。

本机持锁是互斥机制，主机身份与PID启动标识用于审计和拒绝跨机误接管；仅心跳过期、PID数字改变或复制目录均不构成恢复依据。新run同目录恢复不得删除锁文件、重置数据库、改run ID或移动到另一个恢复代目录。

资源暂不可用、CPU依赖或CUDA加载故障进入可恢复的技术／资源状态，不能立即把整个科研run标成阴性或无法判定。科学输入不一致须阻止执行；完整数据的科学门槛不通过、预算耗尽或协议期限到达才形成对应终态，期限和预算不会因技术恢复重置。

新机制不继承旧v2的2／22／24小时时限；若新spec明确配置计算时限，应在首GPU调用前固定T0并在同一run恢复中保持该时限。未配置时不凭旧协议自行创建截止条件，CPU检查不消耗GPU计时。

## 资源与验收边界

首次CUDA前须核对有效平台原始观察、完整GPU UUID、本机实时nvidia-smi、实际禁用／冲突／占用和跨任务总额度；资源观察不是可由执行器自动生成的批准声明。运行期间仅对本项目进程响应已证实禁用或明确停止处置，不杀其他用户进程、不因他人后来加入而擅停原合法任务。

CPU子进程故障注入用于验证计费、锁、恢复和图片评分状态，不能证明真实GPU已初始化或方法有效。交付时分别列出CPU机制检查、真实adapter代码审阅、服务器真实资产／CUDA验证和科学有效性，未做的项目明确保留未验证状态。

## 本轮核心审阅结论（2026-11-02）

Astra已审查Terra的统一入口、持久账本、资源门禁和恢复路径，发现的可用性／计费问题已修复；在“同主机、同目录、单GPU、外部平台观察”的范围内，当前工程实现可交付。此结论不代表真实模型CPU预检或CUDA验收通过，也不解除历史v2终态。

| 核对项 | 最终处置 |
|---|---|
| 技术故障误终止 | CPU／CUDA加载及普通技术错误留痕暂停，资源缺失暂停；不自动清账本或生成新run |
| 科学与代码身份混绑 | 调度代码自动观测并记入每次session，恢复不要求重签review或手工更新代码hash；科学引用仍严格冻结 |
| 重试挤占正常覆盖 | 源／合并各自限制64次重试，同时执行每键2次、每状态及总体尝试上限；耗尽进入无法判定终态 |
| 写入者重复和初始化中断 | host＋绝对run_root绑定账本，flock互斥；复制目录拒绝，只有普通残留锁的初始化中断可同入口恢复 |
| 进程身份 | session记录PID、主机、UID及Linux boot ID／进程启动ticks；Mac测试的Linux专属字段明确为空 |
| 真实模型启动环境 | 入口自动设置离线加载、GPU UUID及确定性CUDA变量，真实adapter不依赖用户先手工export |
| 资源现场追溯 | 单次实时GPU检查后记录UUID、驱动、计算模式、观察时间及XML哈希，不追加重复探测 |

最终针对性复验：`.venv/bin/python -m unittest discover -s scripts/merging/trigger_contrast_localization -p 'test_experiment*py'`为11项通过（4.207秒），包含真实子进程kill／resume、预算终态、只续评分、锁窗口及复制目录拒绝。`test_runtime_tcl.py`的1项静态契约测试通过（0.278秒），使用临时父binding fixture但实际运行固定选样器展开6144键并拒绝输入／mask／阶段／预算改变；这不是大模型运行证据。

主会话在最终源码上完成272项全套回归（30.544秒），最终证据及索引结果见[TASK.md](TASK.md)和实现报告。当前未连接远端、未创建GPU运行、未执行真实模型资产CPU预检或CUDA计算，旧图片导入和多GPU分片均未实现。

运行负责人或外部observer须持续刷新`resource_status_file`才能让执行器获知平台新禁用／停止处置；代码不会自行登录平台采集。可选计算时限在模型操作之间检查，不保证中断卡死的驱动调用，不能把这种协作式检查宣传为独立硬超时保障。
