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

`tick`负责首次启动/相同run恢复，启动后自动运行平台观察器；当前只支持已核验104自动部署。返回`node_preparation_required`表示候选节点尚未部署，不是全平台不可用。101公钥拒绝尚未解决；如要使用其他已配置节点，由接手者先核验本人资产与权限并扩展部署路径。

本机准备缓存为`~/.config/labgpu/tcl-semantic/prepared-104.json`，凭据和缓存不进Git。换机先登录平台，再执行`validation.py prepare --server 104`恢复本地准备引用；科学协议和远端spec已经固定。104环境`/data2/zhangzibo/arxiv-tssa/venv/bin/python`，准备目录`/data2/zhangzibo/arxiv-tssa/preparations/tcl-20261103-semantic-v1/`，输出目录`/data2/zhangzibo/arxiv-tssa/results/tcl-20261103-semantic-v1/`。

本轮复核发现旧夜间候选测试依赖真实墙钟，过了旧截止就失败；仅将该测试固定到合成观察时间100，生产旧截止及历史科学协议未改。

## 11/3 10:30轮次：定时重启、计时修复与CPU部署

用户新授权启动每小时任务并推进当前语义run。`gpu-tcl` 已创建并核验为ACTIVE；本轮实际 `tick` 返回101空卡 `node_preparation_required`，`report` 返回 `not_started`。101本轮唯一一次有界连接到达目标后被 `Permission denied (publickey)` 拒绝；未重复探测、降低校验或启动新run。平台账号0/4、104当时被他人使用，后续以实时新采样为准。

Terra修正执行器计时：完成平台预认证和运行观察后，首次实际GPU预检前持久记录T0；预检失败及暂停期间保留原T0，若探测失败时也已耗尽时限，则当轮记协议终态、不加载CUDA。平台预认证失败及CPU准备不启动T0。锁、预算、科学配置及已有账本不重置。Astra审阅并运行CPU模拟验证；Terra完整执行器进程组18项、语义专项13项通过，其中包含新版执行代码版本校验测试。这些不代表真实GPU生成。

控制器现在将本机runtime、store和adapter哈希与104部署回执匹配；过期回执触发持锁安全重准备，启动前还在远端逐项核对哈希，已运行或终态不为升级重启。104最终版实际CPU部署与38项资产/1024键检查通过，远端 `runtime.py` SHA `a1622080c33ffff2d9b8327340419e63851026ae0d25e2f69dfbb84a57e883ec` 与本机一致；`runtime_store.py`、`runtime_tcl.py` 也一致，科学SHA仍为 `951c09f1883b9c13c539edf0ffb5e37d27f1dc45b5e734f114a48156f735852d`。此次无CUDA初始化、无生成前向、无新PNG。

本轮评分方案保留原ViT和原完整文本CLIP，新增固定目标猫及对象文本CLIP；这改变了评价定义，不应描述为已修复ViT分类准确率，也不能把CLIP闭集选择叫作真实ASR。历史数据仅用于CPU校准，不导入本轮账本。
