# 127 启动阶段见证等待 v2 候选

v2 修复 v1 在图像账本建立前抛出 `FreshWitnessPending` 的问题；首次启动前和 CPU 许可后、CUDA 初始化前都可以等待确定过期或暂时缺失的见证，并在返回前重新验证两份身份、签名和最早过期时间。

- 全阶段仍以 30 秒为见证有效期，单次等待采用最多 90 秒重试窗口并为两次原有各 15 秒验签留余量，总上界 120 秒；签名、身份、格式或非暂态错误立即终止。
- v2 沿用 v1 的 4 项、30 秒成功验签缓存及每次独立身份/时间检查，继续保护模型前向并保留已计次数；已经完成的前向和 2 个 started 样本均不可重放。
- 新签名记录绑定并验证此前 v1 等待修订原文及其签名，旧资源修订和 shard 签名仍由原启动链验证；原 v1 文件和原观察控制器保持逐字节不变。
- 当前旧签名进程已重新启动，候选只供独立审阅，不切换、不重启；如该进程顺利运行，不为启用 v2 而干预它。

审阅者先只读取回原 v1 等待修订原文及签名、127 资源修订及签名和 shard 签名信封，再核对旧文件与 v2 候选哈希；审阅通过后，使用独立 v2 命名空间签名，私钥只留本机。

```bash
TASK=/Users/zzb/arxiv/research/tasks/2026-10-29-trigger-contrast-localization
python3 "$TASK/shard127_wait_review_template_v2.py" --reviewer "$REVIEWER_PRINCIPAL" \
 --resource-review "$RESOURCE_REVIEW" --resource-signature "$RESOURCE_SIGNATURE" \
 --shard-review-envelope "$SHARD_REVIEW_ENVELOPE" \
 --prior-wait-review "$PRIOR_WAIT_REVIEW" --prior-wait-signature "$PRIOR_WAIT_SIGNATURE" > "$WAIT_V2_REVIEW"
ssh-keygen -Y sign -f "$REVIEW_PRIVATE_KEY" -n tcl-wait-amendment-v2 "$WAIT_V2_REVIEW"
```

将 v2 文件及新签名放入 127 的独立执行目录 `A`，旧 v1 文件和签名应保留原路径；下一次确有必要的恢复先执行 `--verify-only`，不得为迁移或提效中断正在运行的任务。

```bash
"$PY" "$A/shard127_wait_launcher_v2.py" --wait-review "$A/wait_v2_review.json" \
 --wait-signature "$A/wait_v2_review.json.sig" --prior-wait-review "$A/wait_review.json" \
 --prior-wait-signature "$A/wait_review.json.sig" --reviewer-key "$A/review.pub" \
 --resource-launcher "$A/resource127_launcher.py" --patch "$A/shard127_watch_wait_v2.py" -- \
 --manifest "$TASK/manifest_candidate.json" --repository-root "$CODE" \
 --overlay "$A/resource127_gdm_xorg_patch.py" --review "$A/resource127_review.json" \
 --signature "$A/resource127_review.json.sig" --reviewer-key "$A/review.pub" -- \
 --manifest "$TASK/manifest_candidate.json" --prompts "$TASK/prompts_tokenized_candidate.jsonl" \
 --context-review "$TASK/context_review.json" --m06-review "$TASK/m06_review.json" \
 --protocol "$PROTOCOL" --asset-manifest "$ASSETS" --models-root "$MODEL" --output-root "$OUT" \
 --repository-root "$CODE" --snapshot-root "$SNAP" --review-envelope "$A/review-envelope.json" \
 --reviewer-key "$A/review.pub" --reviewer-key-sha256 dc477cfe4e08a3196925fc6607391c1862676bc9d8d7b5900bdd8a272e25227b \
 --patched-intervene "$AMEND/intervene_patch.py" --original-amendment "$AMEND/amendment_approval.json" \
 --original-signature "$AMEND/amendment_approval.json.sig" --original-reviewer-key "$AMEND/amendment_reviewer.pub" \
 --original-reviewer-key-sha256 651a664911caea0300f5536204b6dec1cef824e9c242905d7ffc2dbda713630f \
 --watch-envelope /data1/zhangzibo/arxiv-tssa/preparations/tcl127-source-watch-20261030.json \
 --fence-envelope /data1/zhangzibo/arxiv-tssa/preparations/tcl127-104-fence-watch-20261030.json \
 --watch-key "$A/watch.pub" --verify-only
```

实际恢复仍须使用真实 `GPU_UUID`、`CUDA_VISIBLE_DEVICES` 和 `CUBLAS_WORKSPACE_CONFIG`，CPU 加载后按新 nonce 取得实时资源许可；既有 started 项保持原账本身份和次数，不能重试或清零。
