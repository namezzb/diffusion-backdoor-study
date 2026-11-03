# 语义评分与执行实现报告

新运行 `tcl-20261103-semantic-v1` 使用独立 `validation.py` 控制器、独立本机状态目录及104独立准备/结果目录；旧运行的账本和终态保持不变。执行器按固定语义协议记录 ViT、原完整文本 CLIP、目标文本 CLIP 和四类对象文本 CLIP，阶段资格不合格仍继续固定后续阶段，最终结果由完整对照决定。

## CPU 校准和准备

104真实CPU校准读取10张旧图，逐张SHA与原账本一致，旧ViT类别10/10和原CLIP分数全部精确复现；新增语义字段有效，未初始化CUDA。具体结果见[calibration.json](calibration.json)，该校准没有新增实验图，也不证明新方法有效。

104真实 `prepare/check` 已通过：38项模型资产、提示词/分词器、选中掩码及定位账本核验成功，S0/M0各128、S1/M1各384，共1024个唯一键；科学SHA为 `951c09f1883b9c13c539edf0ffb5e37d27f1dc45b5e734f114a48156f735852d`。CPU检查中CUDA未初始化、模型生成前向0、旧图导入0；这不是新运行生成验收。

## 自动化验证与资源

本地语义专项 `.venv/bin/python -m unittest discover -s scripts/merging/trigger_contrast_localization -p 'test_semantic*.py'` 共10项通过；包括评分账本、阶段持续和新旧评分路径的模拟检查。运行时长、卡和实际进度以[TASK](TASK.md)及远端账本为准。

最终提交前完整TCL回归310项通过（34.799秒），labgpu回归38项通过（0.451秒）；完整回归命令为`.venv/bin/python -m unittest discover -s scripts/merging/trigger_contrast_localization -p 'test_*.py'`。这是CPU与进程测试范围，GPU新实验仍未启动。

本轮一次101有界SSH探测被目标节点以 `Permission denied (publickey)` 拒绝；不重复探测或降低主机身份校验。启动前仍需最新平台观察及目标机实际资源检查，资源不足时保留CPU准备并等待；未测出新run PNG前不得将CPU准备称为真实生成成功。

## Terra接手入口

用户最新要求重新启动每小时定时任务并完成本验证；本聊天的Terra负责独占远端执行。接手者从项目JSON进入本TASK，刷新资源后继续，不重开旧run，也不需要重写方案。

在本机仓库运行：

```sh
./labgpu status --json --fresh
.venv/bin/python scripts/merging/trigger_contrast_localization/validation.py tick
.venv/bin/python scripts/merging/trigger_contrast_localization/validation.py report
```

`tick`负责首次启动/相同run恢复，启动后自动运行平台观察器；支持已核验103和104自动部署。返回`node_preparation_required`表示候选节点尚未部署，不是全平台不可用。101公钥拒绝尚未解决；其他节点需先核验本人资产与权限并扩展部署路径。

本机准备缓存为`~/.config/labgpu/tcl-semantic/prepared-104.json`，凭据和缓存不进Git。换机先登录平台，再执行`validation.py prepare --server 104`恢复本地准备引用；科学协议和远端spec已经固定。104环境`/data2/zhangzibo/arxiv-tssa/venv/bin/python`，准备目录`/data2/zhangzibo/arxiv-tssa/preparations/tcl-20261103-semantic-v1/`，输出目录`/data2/zhangzibo/arxiv-tssa/results/tcl-20261103-semantic-v1/`。

本轮复核发现旧夜间候选测试依赖真实墙钟，过了旧截止就失败；仅将该测试固定到合成观察时间100，生产旧截止及历史科学协议未改。

## 11/3 10:30轮次：定时重启、计时修复与CPU部署

用户新授权启动每小时任务并推进当前语义run。`gpu-tcl` 已创建并核验为ACTIVE；本轮实际 `tick` 返回101空卡 `node_preparation_required`，`report` 返回 `not_started`。101本轮唯一一次有界连接到达目标后被 `Permission denied (publickey)` 拒绝；未重复探测、降低校验或启动新run。平台账号0/4、104当时被他人使用，后续以实时新采样为准。

Terra修正执行器计时：完成平台预认证和运行观察后，首次实际GPU预检前持久记录T0；预检失败及暂停期间保留原T0，若探测失败时也已耗尽时限，则当轮记协议终态、不加载CUDA。平台预认证失败及CPU准备不启动T0。锁、预算、科学配置及已有账本不重置。Astra审阅并运行CPU模拟验证；Terra完整执行器进程组18项、语义专项13项通过，其中包含新版执行代码版本校验测试。这些不代表真实GPU生成。

控制器现在将本机runtime、store和adapter哈希与104部署回执匹配；过期回执触发持锁安全重准备，启动前还在远端逐项核对哈希，已运行或终态不为升级重启。104最终版实际CPU部署与38项资产/1024键检查通过，远端 `runtime.py` SHA `a1622080c33ffff2d9b8327340419e63851026ae0d25e2f69dfbb84a57e883ec` 与本机一致；`runtime_store.py`、`runtime_tcl.py` 也一致，科学SHA仍为 `951c09f1883b9c13c539edf0ffb5e37d27f1dc45b5e734f114a48156f735852d`。此次无CUDA初始化、无生成前向、无新PNG。

本轮评分方案保留原ViT和原完整文本CLIP，新增固定目标猫及对象文本CLIP；这改变了评价定义，不应描述为已修复ViT分类准确率，也不能把CLIP闭集选择叫作真实ASR。历史数据仅用于CPU校准，不导入本轮账本。

## 11/3 15:49轮次：半小时检查与实验后独立保留

用户要求将 `gpu-tcl` 更新为每半小时，并在实验结束后尽量保留最多两卡；随后明确目标为GPU计算利用率和显存占用均超过60%，持续到用户要求停止。定时任务已更新为每小时整点、半点，继续优先启动本run；本轮103虽有空卡，唯一一次有界SSH在banner交换时超时，没有目标会话、未启动实验。

新增独立 `gpu_hold_controller.py` 与 `gpu_hold_worker.py`，用单独的配置、锁、租约和日志，不改科学运行器、科学终态或预算。等待器在真实实验启动且首个新样本验收后启动；仅当1024单元与冻结配置一致、四阶段及正式终态完成、科学写者退出，核验实际PNG哈希/头部和完整评分后，才重新申请源节点卡并在条件满足时尝试第二卡。监控独立短租约、规则变化/有效停止、用户STOP及断线恢复；进程和用途真实可见。[操作说明](../../../scripts/connection/GPU_HOLD.md)列出命令、授权判断与限制。

根会话独立执行 `.venv/bin/python -W error::ResourceWarning -m unittest discover -s scripts/connection -p 'test_gpu_hold*.py'`，33项CPU假设备/子进程测试通过（1.724秒）；真实 `inspect-policy` 读取平台规则和账户成功。此前12秒平台查询曾超时，控制器调整为35秒上限、最多90秒租约且不超过原GPU/进程采样截止；短暂超时只在旧租约仍有效时有界重试，不延长旧观察。Astra与Terra独立复核终态、STOP竞争、逐worker撤销和失联恢复；没有真实GPU交接、60%阈值或双卡验收。

## 11/3 18:07：103部署与超时定位

103环境单独导入PyTorch 2.7.1+cu128、diffusers 0.35.1（约14.48秒）和transformers 4.49.0成功。部署适配使用已核实的本人历史代码/输入快照，缺少的小固定输入逐SHA传输到新准备目录；不复制历史实验结果账本。远端真实CPU检查核验38文件约10.75GB、320语境、1024唯一键和定位选择，CUDA=false、生成前向0、旧图导入0。原240秒超时位于慢盘读取（观察到约9.76GB读取及D态等待），沿用同spec增至900秒有界检查后约11分钟通过。

准备过程新增0600 stdout/stderr及cpu-progress.json，保留阶段与失败证据；prepare、状态和启动按103/104一致选择目录。103回执在`~/.config/labgpu/tcl-semantic/prepared-103.json`，部署绑定SHA为`fa5169aca666bdb2456be9caff2c358eb6934a98f4923ef4799edc5943cf1a0a`；runtime/store/adapter三个执行SHA与104一致。与104的完整science路径归一化核对尚受SSH阻塞，不据此宣称两个科学SHA只有路径不同。

连接上下文使用0700临时目录、0600配置、私有ControlMaster与120秒持久化，仅清理己方socket。启动和状态查询可借用同run观察器上下文，验证run/science/UUID、PID命令、时间及路径权限，借用者不清理拥有者连接。观察器启动等待最多185秒，仍需实际新鲜许可；观察异常按阶段落日志。公共DNS优先作为可选参数，仅TCL桥接器启用，保留HostKeyAlias和严格known_hosts。系统DNS与公共DNS曾不同，但正确公共地址下仍有SSH banner超时，因此DNS差异不能认作全部故障根因。

根会话独立运行`test_semantic_validation.py`的10项CPU测试通过；Terra运行传输/DNS测试18项通过。当前观察器尚无成功ready，未实际调用GPU启动；新run无新PNG、评分或账本增长，T0未开始，保留等待器尚未启动。私有SSH诊断日志`~/.config/labgpu/tcl-semantic/ssh-phase-20261103.log`记录ProxyJump后未收到remote banner；现有日志无法精确区分跳板与目标端，不能虚构原因。后续在同run继续，不将工程准备视为科研结果。

18:35接续修复：本轮真实CLI tick在远端状态检查后因平台实时查询失败返回waiting。平台HTTP请求默认上限由10秒改35秒，总子进程仍60秒；不改变采样有效性、启动许可或运行期失联暂停。11项CPU测试通过，包括请求上限传递及总超时仍失败关闭。此后必要science读取仍遇真实SSH banner超时，本轮未重复探测；GPU仍未启动。无运行任务的预启动watch PID77040已核验身份后停止，未来正常tick重新建立运行观察器。

19:18接续：双层SSH调试实际完成跳板及103的严格主机身份、公钥认证并返回本人UID/hostname；检查发现ControlPersist后台master继承stdout/stderr管道，前台命令已exit 0且输出完整后本机仍等EOF至超时。以本任务0600临时文件承接输出，握手上限按服务器手册设60秒、状态/启动调用75秒，不放宽观察采样有效期。真实fork子进程继承输出的回归在修复前失败、修复后通过；12项定向测试通过，实际观察器连接也成功。私有context新增15秒/2次keepalive用于尽早发现黑洞连接，旧观察器进程仍使用原配置，安全交接待远端可核验。

104与103完整spec逐字段比对：除路径差异，唯一原始SHA差异为定位SQLite。两端该库完整四表schema和全字段排序行摘要、行数（107520/420/1/0）、integrity_check、终态及selection身份均一致；物理文件SHA不同，103继续使用自身原始冻结SHA。完整比对证据留本人私有目录。用户要求即刻启动后，103本run创建账本；19:18:12.293+08首次实际GPU预检通过并记录T0，随后账本出现第1次尝试及真实encoder 2次、UNet 1次前向。后续SSH观察失联、最新ready超过180秒，平台实时查询也超时；运行器应在检查点暂停，但远端是否暂停、进程是否退出、PNG/评分是否完成尚无证据。保持现有观察器，不复制账本或启动第二写者；连通后先核对再恢复，首图完整验收后才启动独立保留等待器。
