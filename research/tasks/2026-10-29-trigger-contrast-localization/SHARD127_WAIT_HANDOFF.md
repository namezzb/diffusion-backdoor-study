# 127 见证等待与验签缓存候选

此修订保持原 127 shard、原资源修订、原控制器、两台源身份和 30 秒见证有效期，现有 3 完成及 2 个 started 键不重放；只对已验证的真实过期或临时缺失暂停并重验，签名、身份、格式和其他错误立即失败。

- 等待采用 90 秒重试窗口，为两次原有各最多 15 秒验签预留时间，单次等待上界 120 秒；恢复时两份见证须再次通过签名、身份、原锁与时间核验，且任何一份不能在组合核验期间过期。
- 保留每次 NFE 的预留和原账本，UNet、TE、VAE、ViT 和 CLIP 各自前向启动前复核；已发出的模型前向不能中途撤销，因此保证的是不以过期见证启动下一次前向。
- 缓存仅覆盖 `tcl-shard-watch` 和 `tcl-shard104-fence` 两类成功验签，键包含消息、签名、公钥、公钥 SHA、principal 和 namespace 的完整值；最多 4 项、最长 30 秒，文件 inode/大小/修改时间变化立即清除对应项，身份与时效每次均重验，失败不缓存。
- 等待、恢复及超时会追加 shard 事件，超时或异常保留 started 与已计 NFE；已执行前向不回滚、不再执行，先前2个 started 样本不可重试。
- 原 `shard127_watch_controller.py` 保持已签字节，v2 另作候选且本修订不启用它；两个见证各自原子替换并非跨文件事务，若一新一旧仍须逐个验签、逐个检查时间与绑定。

独立审阅者从 127 本人目录只读取回原 `resource127_review.json`、其 `.sig` 和原 `review-envelope.json`，核对本地三个新增文件与相关冻结文件 SHA 后生成并签署等待修订；以下变量是本机私有审阅路径，私钥始终留在本机。

```bash
TASK=/Users/zzb/arxiv/research/tasks/2026-10-29-trigger-contrast-localization
python3 "$TASK/shard127_wait_review_template.py" --reviewer "$REVIEWER_PRINCIPAL" \
 --resource-review "$RESOURCE_REVIEW" --resource-signature "$RESOURCE_SIGNATURE" \
 --shard-review-envelope "$SHARD_REVIEW_ENVELOPE" > "$WAIT_REVIEW"
ssh-keygen -Y sign -f "$REVIEW_PRIVATE_KEY" -n tcl-wait-amendment "$WAIT_REVIEW"
```

只在审阅签名通过后把新启动器、等待补丁和签名记录放到 127 独立执行目录 `A`；使用原 `RESOURCE127_HANDOFF.md` 的资源包装器与 shard 完整参数，外层前缀如下，`--` 后为该交接文件中的 `resource127_launcher.py` 参数，含它自己的 `--` 和完整 shard 参数。

```bash
"$PY" "$A/shard127_wait_launcher.py" --wait-review "$A/wait_review.json" \
 --wait-signature "$A/wait_review.json.sig" --reviewer-key "$A/review.pub" \
 --resource-launcher "$A/resource127_launcher.py" --patch "$A/shard127_watch_wait.py" -- \
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

先在 CPU 上执行 `--verify-only` 并由独立 reviewer 核验所有签名和 SHA，实际运行前按原规则重新获取新 nonce 的实时资源许可；等待补丁自动把冻结 `CODE` 根放入 Python 搜索路径，并检查两个实际载入的 runtime 文件与 manifest 的 SHA。
