# TCL v2执行器审阅与部署入口

2026-11-02：104生产bundle及配置经审阅后首次CPU复核报错；修订代完成真实CPU预检，但目标GPU被他人占用，实时门禁在CUDA前拒绝启动，两代均0次新增出图。两代终态见[首次观察](server104_pilot24_terminal_20261102.json)和[修订代观察](server104_pilot24_recovery_terminal_20261102.json)；链式恢复及资源重绑候选仍待独立审阅，不得重置T0或改写已冻结产物。

2026-11-02 14:18更新：来源构造器及真实来源包已完成并经[独立审阅](PILOT24_SOURCE_REVIEW_20261102.md)；下文缺少构造器、来源待认证及网络失败的描述保留原时点，生产bundle仍未审阅。

用户要求解决“组件测试通过但不能启动”的阻塞，本次补齐有限分片执行链，并将历史v1来源隔离与同一v2进程接管分开。真实模型、来源包和GPU许可仍必须以目标机器证据绑定，本文不签发尚不存在的生产bundle批准。

| 审阅范围 | 状态与边界 |
|---|---|
| 本地执行器代码 | 通过：独立v2检查102项、主会话完整TCL检查223项通过，源码摘要绑定下方检查记录 |
| 生产输入／bundle审阅 | pending；当前终端无法连接学校跳板机，未生成真实来源包、R或UUID分工 |
| CUDA与实验 | 未启动；T0为空，导入0、新生成0，不能将CPU模拟称为实际科研结果 |
| 旧103 | 进程仍unknown；独立v2可通过已定义的固定副本隔离继续，不必无限等待其退出 |

## 已修复的执行链

| 原缺口 | 当前实现与验证重点 |
|---|---|
| 只有单图函数，没有完整执行循环 | 每GPU一个常驻worker，按邮箱中的固定分片顺序运行，跨阶段复用模型和首次合法许可 |
| 同卡可能并发启动多个分片 | 协调器唯一锁、常驻session登记、每分片独占账本；未知旧v2进程不自动重派 |
| 阶段门槛可被手写passed绕过 | 独立review绑定bundle和config，worker核对实际分片成员并重新验证前置报告及完成记录 |
| 断点可能重复出图／漏计失败 | 生成前持久记账，PNG已保存只续评分；每键最多两次生成、源和合并各64重试令牌 |
| 心跳前强制退出可能少记实耗 | 确认session退出后重新取得本机锁并读取SQLite最终账本，无法取得时明确计数未核清 |
| 24小时约束没有执行链 | 唯一T0、2小时吞吐判断、22小时停新图、22.25小时监督结束计算并形成待审阅终态报告 |
| 来源包与实际读取路径未绑定 | 固定只读字节副本、非链接、文件SHA、父代码及逐图原尝试核验，实际runtime输入逐角色匹配 |
| 多进程评分可能争用CPU | 每worker固定CPU线程数，默认4；评分设备、代码和模型身份纳入来源摘要 |

核验只覆盖同机持久多卡执行及明确传送的跨机回执，不宣称已实现自动跨机故障迁移。报告将源阶段发现、合并阶段状态、统计不确定性和资源退出证据分开，完整负结果可以结项，技术缺失保持无法判定。

## 真实部署前的剩余步骤

1. 在可连接学校服务器的执行环境按104→103→101→127核验资源，先使用就绪合规卡；本轮页面观察见[环境记录](pilot24_environment_observation_20261102.json)，它不是可复用的启动许可。
2. 在本人数据盘新建独立来源目录，原样复制已核验的定位selection、terminal、8份掩码及一致性SQLite备份；固定副本与v1输出、v2输出互不重叠，文件444、目录555且不得为软硬链接。
3. 按[来源认证器](../../../scripts/merging/trigger_contrast_localization/pilot24_provenance.py)的schema采集父manifest、固定源码、来源哈希、旧103单GPU上界和逐图原账本／尝试证据，认证363候选后固定R；若证据不全而选择R=0，必须记录具体不复用理由，仍复用定位，不重新定位。
4. 调用下方CPU准备器生成bundle、6144键config、待审阅review及启动映射，由独立reviewer核验真实文件并绑定bundle和config摘要；准备器不会自行把review改成passed，也不会生成GPU许可。
5. 经审阅后持久启动执行器，worker完成CPU准备会生成自身ready记录；依据新鲜网站观察、主机UUID／进程信息及该ready记录签发首次许可，随后常驻进程继续完成获准阶段，不在每次前向重复等待远端见证。
6. 保守T0从派发首worker前开始，不能后移；至少64张正式新图、每活跃worker至少16张并覆盖四类后估速，不能在2小时判定不可行后仍无限运行。

来源证明尚无自动构造CLI，需要上述真实现场采集；已实现的验证器和准备器负责拒绝缺证据的输入，不能把模板填写当成现场认证。103的单GPU历史边界可引用[原确认准备](server103_confirm_preparation_20261029.json)，未知占用保守计入一张且扣除其他本人占用，不能把网站offline折算为0。

## 操作入口

准备请求中的所有路径均为目标服务器上的真实绝对路径，完整UUID来自本轮主机核验；以下仅说明字段，不是可直接启动的冻结输入。

```json
{
  "repository_root": "/absolute/reviewed-code",
  "models_root": "/absolute/verified-models",
  "execution_root": "/absolute/results/tcl-20261102-pilot24-v2",
  "source_isolation": {"path": "/absolute/source-isolation.json", "sha256": "ACTUAL_SHA256"},
  "workers": [{"worker_id": "w0", "server": "school104", "gpu_uuid": "ACTUAL_FULL_GPU_UUID"}],
  "scorer_device": "cpu",
  "cpu_threads_per_worker": 4
}
```

```bash
python scripts/merging/trigger_contrast_localization/pilot24_prepare.py --request /absolute/request.json
python scripts/merging/trigger_contrast_localization/pilot24_run.py --help
```

准备器输出`frozen/bundle.json`、`coordinator_config.json`、`review.json`（pending）、`launch_map.template.json`及`preparation_report.json`；持久启动使用`pilot24_run.py start`，进度读取使用`status`，精确必填参数以其帮助为准。代码入口见[执行器README](../../../scripts/merging/trigger_contrast_localization/README.md)，任务状态唯一来源为[TASK](TASK.md)。

## 验证记录

本地实现review通过，完整TCL 223项检查通过、旧v1的27个冻结源码SHA全部一致；实际命令、环境、源码SHA和独立review范围见[检查记录](pilot24_implementation_validation_20261102.json)。任何后续源码变更都须重新核验相关检查并更新摘要，真实部署冻结还须另绑定目标路径和实际资源。
