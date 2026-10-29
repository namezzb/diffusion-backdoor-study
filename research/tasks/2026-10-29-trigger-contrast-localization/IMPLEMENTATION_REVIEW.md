# 实现交接（M05 待审，M06 未通过）

方法入口为[脚本目录](../../../scripts/merging/trigger_contrast_localization/README.md)，默认命令 `.venv/bin/python scripts/merging/trigger_contrast_localization/main.py` 只输出计划；正式定位和确认分别使用 `localize` 与 `confirm`，仅在本会话review通过及服务器资源实时许可后调用。

输入候选为[manifest_candidate.json](manifest_candidate.json)、[逐条token](prompts_tokenized_candidate.jsonl)、[文本review](context_review.json)及[103观察](server103_assets_observation_20261029.json)；M06审阅决定需单独绑定候选manifest哈希，定位后才会产生实际固定mask和selection。

运行需传 `--manifest`、`--prompts`、`--context-review`、`--m06-review`、`--protocol`、`--asset-manifest`、`--models-root`、`--output-root`、`--repository-root`，并显式设置 `PYTHONPATH=.:scripts/merging`、已获许可的完整 `GPU_UUID`／`CUDA_VISIBLE_DEVICES` 和 `CUBLAS_WORKSPACE_CONFIG=:4096:8`。预定输出路径与运行身份在候选清单中，启动前仍须核验本人合规数据盘与网站实时状态。

M06初审指出的定位科学早停、源／合并基线统计、中断后预算内重算及CPU预检后资源门禁缺口已修订，具体证据见[实现检查](implementation_validation.md)，候选manifest SHA-256为 `c597deebc3c2256401ee89b47f96ba9caa4bd92502019e3f257cfde7cddd1aaa`。终态按真实账本记账并禁止在同一已终止身份下重新执行，需reviewer再次核对。

处置入口为 `recover --recovery-kind localization|images --reason <具体原因>`，仍须传相同冻结文件和路径参数；持有run锁并检查余量后保留原尝试，完整且已登记PNG仅恢复评分，完成处置再调用原 `localize` 或 `confirm`。损坏、未登记、缺失及未决临时图像须阻塞；原103 CPU预检绑定旧候选，不代表新版本通过。

每次 `localize` 或 `confirm` 的CPU预检完成后，运行目录事件写入 `waiting_resource_permit`，含一次性 `nonce`、`ready_at_utc` 和 `permit_path`；操作方随后核查平台并原子写入该路径，许可有效期最长120秒。`platform` 是操作方对网站的观察记录，`evidence_sha256` 应对应其可追溯证据；程序另用实时 `nvidia-smi` 检查进程，不能消除检查后其他进程启动的竞争窗口。

```json
{
  "task_id": "TCL-20261029-01", "run_id": "<run_id>", "manifest_sha256": "<本候选SHA256>",
  "server": "school103", "gpu_uuid": "<完整GPU UUID>", "nonce": "<等待事件的nonce>",
  "issued_at_utc": "<UTC签发时间>", "expires_at_utc": "<UTC到期时间>",
  "platform": {"source": "https://gpu.orz2333.fun/", "observed_at_utc": "<UTC观察时间>",
    "sampling_valid": true, "disabled": false, "allocation_conflict": false,
    "quota_available": true, "evidence_sha256": "<平台观察证据SHA256>"}
}
```

平台观察须在 `ready_at_utc` 之后、签发之前，许可过期或nonce不符不会放行；进程或计算模式状态异常时执行器退出。默认等待1800秒，可用 `--resource-wait-seconds` 限制为1至3600秒。

系统Xorg的 `/proc/<pid>/exe` 仅在权限拒绝时可回退读取cmdline；事件会明确记录 `proc_cmdline_fallback_exe_inaccessible` 和 `exe_readable=false`，不宣称直接确认实际exe。回退仍要求root进程、G类型、系统路径及受保护文件一致，未知或异常拒绝。

请重点复核真实SD与评分器接口、全部资源预算和不确定中断、随机对照与mask归属、点估计与配对统计、GPU平台许可及独立验收流程。实现仅含微型模型及模拟确认测试，M05不是已验收，未完成服务器实验，`outcome=not_evaluated`。
