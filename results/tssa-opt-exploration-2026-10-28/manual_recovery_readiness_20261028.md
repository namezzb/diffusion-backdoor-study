# 一次性人工恢复封装验收（2026-10-28）

本机 CPU 验收通过，**当前远端未就绪，未执行恢复**；代码只允许 server103 原 run 复用已完成171张，归档唯一中断attempt后继续到 dev，不进入 confirm。

## 已完成

- `recover_interrupted_search.py` 默认只核对本机冻结输入，真实 dry-run 返回成功且明确 `remote_state_verified=false`、`ready_for_one_shot_execution=false`。
- 14项本机测试全部通过，覆盖固定任务prefix、171条凭证与PNG哈希、损坏PNG与pending图出现拒绝、boot/PID复用、过期许可/错误GPU拒绝、单次claim持久性和完整恢复顺序；所有造图、篡改记录与远端事实模拟均仅在标记SIMULATED的临时目录中。
- 两个完整流程模拟证明先持久化claim与ledger、再归档校验原started字节、再移除该原路径、最后启动；归档失败保留原started且不启动，再次调用因永久claim拒绝。
- 实际命令固定原科研入口、`--resume --until dev`、CPU评分器、完整GPU UUID及离线/CUBLAS环境，原claim、manifest、identity及科研源码不变。

## 当前实际阻塞

1. 17:50只读元数据确认服务器第二次重启，当前boot为`1c2bddf4-f594-43cf-8a4d-5b116ad79067`，与人工审计绑定的`75f147ae-6098-47c8-aed0-a13796130af3`不同；封装保留旧boot检查并拒绝，不能只改常量追随新启动。
2. 原run和operations目录为0775、`.run.lock`为0664，严格路径检查会拒绝组写；本子任务未修改权限，且未减弱检查。
3. 父任务约17:47观察平台异常，当前没有新鲜、完整、可信的三页许可；本机测试不替代许可或CUDA验收。

仅准备的权限处理范围：重新核实本人UID24112、路径非软链、inode及当前mode、原PID已退出且run锁可持有后，将上述两个确切目录0775→0755、确切`.run.lock`0664→0644；记录前后stat与锁文件字节哈希，不递归chmod、不更改其他文件，本次未执行。

下一次手工审计需要重新绑定最新boot、旧PID不存在、171 completed收据及PNG逐文件哈希、唯一pending原SHA与PNG不存在、原identity/source/claim哈希和锁；在该证据完整前，不运行本封装的execute路径，以免消耗永久单次claim。

## 预算和观察边界

失败attempt永久单列1次，保守reserve50 branch-NFE、TE/VAE各最多1次；到dev上界864唯一图、865 attempts及43,250 branch-NFE，仍在原1440/72,000上限内。

confirm不在本封装许可范围，dev结束须独立核算：三候选全confirm将达1441 attempts/72,050 NFE，不能擅自启动或丢弃候选来压预算；一或两候选时可按冻结协议核算原预算内的剩余路径。

新receipt记录PID、`process_start_ticks`、boot及run_root，并继承不可变ledger；本机result另给精确raw receipt SHA256，供观察器显式绑定，返回spawn并不宣称CUDA验收。

## 本机命令

```sh
python3 results/tssa-opt-exploration-2026-10-28/recover_interrupted_search.py
python3 results/tssa-opt-exploration-2026-10-28/test_recover_interrupted_search.py
```

以下只展示未来命令形式，**当前不能执行**；先完成上述新的人工审计和精确权限处理，再由父任务刷新三页许可并执行一次：

```sh
python3 results/tssa-opt-exploration-2026-10-28/recover_interrupted_search.py --permission <fresh-manual-UI-permission.json> --execute
```

精确SHA、测试结果与证据路径见`manual_recovery_readiness_20261028.json`；本子任务未连接服务器、未初始化GPU、未修改活跃run或任何冻结科研文件。
