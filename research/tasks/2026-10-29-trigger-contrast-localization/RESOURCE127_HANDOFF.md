# 127 gdm Xorg 资源门禁追加修订

候选只针对 `iipl-127` 的 GPU 2，冻结代码、原 manifest、样本和预算均不变；2026-10-30 现场 XML 显示唯一图形进程 PID 49207、4 MiB，前次失败为 0 图像尝试。

- 补丁要求 UID/GID 为 gdm 的 128/132，四项 UID/GID 一致，Name 为 Xorg、Tgid 与 PID 一致，cmdline 首项 `/usr/lib/xorg/Xorg`；系统文件须 root:root 0755 且 inode 27265194，XML 类型 G、显存不超过 8 MiB。
- `/proc/49207/exe` 对本人不可读，只有 EACCES/EPERM 才允许基于 cmdline 和系统文件证据回退，结果事件记录 `exe_readable=false`；无论何种回退，都不能声称实际 exe 已直接读取，未知进程和其他账户仍被拒绝。
- 原资源门禁保持原字节，签名启动器校验 manifest、原门禁、修订、启动器、127 runner、两份策略及目标 UUID 后仅在进程内覆盖检查；103/104 双源见证、127 GPU 实时进程检查和平台许可保持生效。
- 启动器为每次资源许可创建 `resource_permit_attempts/permit-*/resource_permit.json`，旧 `resource_permit.json` 原样保留；复用前次 CPU 预检作为历史证据，重启后必须重新加载模型并执行现有完整 CPU 核验。

仅在独立审阅通过后使用专用 reviewer 私钥签名；`CODE` 必须是原冻结代码根，`A` 是本人独立部署目录，其他变量以 [127 分片交接](SHARD127_HANDOFF.md) 为准。

```bash
LOCAL_TASK=/Users/zzb/arxiv/research/tasks/2026-10-29-trigger-contrast-localization
python3 "$LOCAL_TASK/resource127_review_template.py" \
 --manifest "$LOCAL_TASK/manifest_candidate.json" --repository-root /Users/zzb/arxiv \
 --reviewer "$REVIEWER_PRINCIPAL" > "$RESOURCE_REVIEW"
ssh-keygen -Y sign -f "$REVIEW_PRIVATE_KEY" -n tcl-resource-amendment "$RESOURCE_REVIEW"
```

将 `resource127_launcher.py`、`resource127_gdm_xorg_patch.py`、修订原文和签名部署到 127 的 `A` 后，以该包装器接管原 `shard127_runner.py` 的完整参数；下面先执行纯签名/输入校验，实际运行需移除 `--verify-only`。

```bash
"$PY" "$A/resource127_launcher.py" --manifest "$TASK/manifest_candidate.json" \
 --repository-root "$CODE" --overlay "$A/resource127_gdm_xorg_patch.py" \
 --review "$A/resource127_review.json" --signature "$A/resource127_review.json.sig" \
 --reviewer-key "$A/review.pub" -- \
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

实际执行应先设置 `GPU_UUID`、`CUDA_VISIBLE_DEVICES` 与 `CUBLAS_WORKSPACE_CONFIG`，CPU 预检完成后从新 `waiting_resource_permit` 事件获取该次 nonce 与 **新 permit_path**，重新核对平台状态并仅向该新路径写短时许可；不要覆盖旧许可，也不要复用旧 nonce。
