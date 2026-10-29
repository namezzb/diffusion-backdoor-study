# 恢复后的只读观察

当前只完成本机实现与模拟验收，未连接服务器、未启动或恢复GPU任务；103第二次重启后，旧恢复封装仍会按其boot门禁拒绝运行，不能把本文件当作已恢复证明。

1. 默认 `--server 103` 行为兼容，只在加 `--execute` 时作一次有界只读连接；恢复模式必须同时提供真实恢复结果中的 `remote.receipt` 与 `remote_receipt_sha256`，不猜PID、不搜索任意新日志。
2. 验证原启动claim/receipt、同run/plan/identity/完整GPU UUID、恢复claim与ledger一致、原started归档SHA及失败预算后，`launch`、`launch_process_now`、`log_tail`才指向恢复任务；旧信息保存在`original_launch`、`original_launch_process_now`和`original_log_tail`并标历史用途。
3. 新PID必须同时匹配账号、原run、进程启动ticks和恢复receipt的boot_id才标`recovery_process_identity_matches=true`；旧PID消失不代表恢复任务退出，PID重用或再次重启也不能误报仍运行。
4. 恢复模式回传`artifacts/recovery/`下的原始claim、ledger、receipt和started归档，分别校验传输SHA；`recovery_resource_accounting`将旧失败attempt=1、生成branch-NFE上界50及TE/VAE各上界1加入当前收据账目，不捏造失败实际成本。
5. 当前成功图、在途操作及旧失败尝试分别列出，含失败总上限仍1440次/72000生成branch-NFE；若有因确认门禁而未读取的操作，则明确全局账目不完整，不能将部分计数当最终总量。
6. 确认内容和两个日志尾部继续服从既有dev选择与confirm_binding门禁；此恢复授权仅至dev，观察器不批准后续确认、不终止进程、不自动重试或修改任何远端科学文件。

默认先本机准备检查（不会连接）：

```text
python3 results/tssa-opt-exploration-2026-10-28/observe_image_search.py --server 103 --recovery-receipt <真实remote.receipt绝对路径> --recovery-receipt-sha256 <真实remote_receipt_sha256>
```

需要观察时对同一命令追加 `--execute`；恢复收据不存在、哈希不符或绑定错误时，结果标`recovery_provenance_unverified`并保留原启动历史，不把旧进程状态冒充当前恢复状态。

CPU验收包含恢复封装真实`remote_recover`逻辑的完整模拟流程，其主机事实、NVML与Popen均被替换为模拟且所有新文件位于临时目录；原样返回的receipt/ledger/archive直接交给观察器，未调用SSH/GPU。
