# 104 分片审阅与运行交接

该包仅为待独立审阅的执行候选；本地单测通过，104 的候选计划生成因空 WAL 检查失败，修复后尚待重新验证。原执行器、manifest、103 数据及冻结预算均未修改。

- 源快照应由 `shard104_plan.py` 全量验 SHA 和自包含 SQLite 后生成 1704 个互斥键，343 已完成及 1 未决键绝不分片；原 source 已计 344 次，本分片最多再计 1704 次，合计不超过 2048 次。
- SQLite 一律以 `immutable=1` 读取；只接受快照清单列出且通过哈希核验的零字节 WAL，未登记或非空 WAL 均拒绝，已登记的 SHM 同样按清单校验。
- 本分片最多累计 2047 条已完成基线图，因此不能计算完整 source 基线门禁、不能进入剩余版本，也不能输出最终科研结论；重试原未决键需要第 2049 次基线尝试，完整 source 阶段可能达到 8193 次，超过原 8192 次上限。
- 103 原锁仍由退出中的 PID 持有，签名观察要求固定 PID、启动时刻、PF_EXITING、FDSize=0、原锁及源账本无变化；禁止任何人启动原 run，观察过期或不一致即停止登记后续前向，已预留键不得再生成。
- SSH 观察每 5 秒尝试更新、单次源观察超时 20 秒，签发时刻保守回拨 2 秒，过期时刻为源机观测时刻加 28 秒，失败或超时不续签；锁比较忽略内核动态序号但严核类型、PID、设备、inode 与完整范围。
- 观察不是跨服务器原子栅栏，若违反“不得重启原 run”的操作约束，源锁释放与下一次观察之间存在竞态。
- 控制器会将观察脚本与原先审核的 SHA 比对，并将签名证据原子写到本人 104 的 preparations 目录，私钥仅留本机；当网络不稳定超过有效期时，实验会中断并按账本保留不确定尝试。

下面命令中的 `CODE` 指 104 快照下包含原 `scripts/` 的仓库根，`A` 指 104 上独立部署候选脚本目录，`MODEL` 指 104 本人模型根，`PROTOCOL` 与 `ASSETS` 指原冻结协议和资产清单；确定实际位置后在 104 shell 设置变量，不覆盖任何原文件。

```bash
SNAP=/data2/zhangzibo/arxiv-tssa/preparations/tcl104-direct-20261030/tcl104-shard-snapshot-20261030T0200Z
OUT=/data2/zhangzibo/arxiv-tssa/results/tcl-20261029-01-v1-shard104-20261030
TASK="$CODE/research/tasks/2026-10-29-trigger-contrast-localization"
PY=/data2/zhangzibo/arxiv-tssa/venv/bin/python
"$PY" "$A/shard104_plan.py" \
  --manifest "$TASK/manifest_candidate.json" --prompts "$TASK/prompts_tokenized_candidate.jsonl" \
  --context-review "$TASK/context_review.json" --m06-review "$TASK/m06_review.json" \
  --repository-root "$CODE" --snapshot-root "$SNAP" \
  --snapshot-manifest-sha256 dca8ba3a758b8641092026df5bc1b7ca5d91fdda79b5e1bb2d8fa6229cb3dd5b > "$A/candidate.json"
```

把 `candidate.json` 取回本机，复核内容后生成待签原文；模板默认写入 approved，因此只有独立审核确实通过后才可签名，公钥和签名文件均用本次专用密钥，旧修订公钥及签名仍需原样核验。

```bash
TASK=/Users/zzb/arxiv/research/tasks/2026-10-29-trigger-contrast-localization
python3 "$TASK/shard104_review_template.py" --candidate "$CANDIDATE" \
  --original-amendment "$TASK/amendment_approval.json" --original-signature "$TASK/amendment_approval.json.sig" \
  --original-reviewer-key "$TASK/amendment_reviewer.pub" --patched-intervene "$TASK/intervene_patch.py" \
  --reviewer "$REVIEWER_PRINCIPAL" --watch-principal "$WATCH_PRINCIPAL" > "$REVIEW_MESSAGE"
ssh-keygen -Y sign -f "$REVIEW_PRIVATE_KEY" -n tcl-shard-review "$REVIEW_MESSAGE"
python3 - "$REVIEW_MESSAGE" "$REVIEW_MESSAGE.sig" "$REVIEW_ENVELOPE" <<'PY'
import base64,json,pathlib,sys
message,signature,out=map(pathlib.Path,sys.argv[1:])
out.write_text(json.dumps({'message_b64':base64.b64encode(message.read_bytes()).decode(),'signature_b64':base64.b64encode(signature.read_bytes()).decode()},sort_keys=True,separators=(',',':')))
PY
```

仅由操作者把已审阅的 `shard104_source_guard.py` 放到 103 的 `/data1/zhangzibo/arxiv-tssa/preparations/tcl104-shard-source-guard.py`，把 runner、plan、policy、source_guard、controller、原 amendment launcher 和补丁、两份公钥及签名信封放到 104 独立部署目录；文件 SHA 必须与签名审阅一致，本机私钥不得上传。

在本机保持控制器前台，`CANDIDATE_SHA` 为候选 JSON 的规范化 SHA，`ATTEMPTS_SHA` 为候选的 `source_attempts_logical_sha256`，控制器签名和传输的两台主机均按已配置主机指纹验证。

```bash
CANDIDATE_SHA=$(python3 - "$CANDIDATE" <<'PY'
import hashlib,json,sys
v=json.load(open(sys.argv[1]));print(hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest())
PY
)
ATTEMPTS_SHA=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["source_attempts_logical_sha256"])' "$CANDIDATE")
python3 "$TASK/shard104_watch_controller.py" --ssh-config /Users/zzb/arxiv/server/school_ssh_config \
 --watch-private-key "$WATCH_PRIVATE_KEY" --watch-public-key "$WATCH_PUBLIC_KEY" \
 --watch-key-sha256 85f4e02cb2765186d72fa4be1cba1b95a00d316d9083b98d99c00d3f61f9a9da \
 --principal "$WATCH_PRINCIPAL" --plan-sha256 "$CANDIDATE_SHA" --source-attempts-sha256 "$ATTEMPTS_SHA" \
 --manifest-sha256 c597deebc3c2256401ee89b47f96ba9caa4bd92502019e3f257cfde7cddd1aaa \
 --source-guard-sha256 2a166e8b22de9d087bc98f73736186af7a9f18546545d26e71e7e8e5d20dc8e6
```

在 104 先加 `--verify-only` 做签名及输入核验，再移除该标志运行；后台前须确保控制器已有新鲜观察，完成 CPU 预检后按 runner 事件中的 nonce、实际完整 GPU UUID 和实时平台复核发放短期资源许可。

```bash
export CUBLAS_WORKSPACE_CONFIG=:4096:8
export GPU_UUID="$FULL_GPU_UUID"
export CUDA_VISIBLE_DEVICES="$FULL_GPU_UUID"
"$PY" "$A/shard104_runner.py" --manifest "$TASK/manifest_candidate.json" \
 --prompts "$TASK/prompts_tokenized_candidate.jsonl" --context-review "$TASK/context_review.json" \
 --m06-review "$TASK/m06_review.json" --protocol "$PROTOCOL" --asset-manifest "$ASSETS" \
 --models-root "$MODEL" --output-root "$OUT" --repository-root "$CODE" --snapshot-root "$SNAP" \
 --review-envelope "$A/review-envelope.json" --reviewer-key "$A/review.pub" \
 --reviewer-key-sha256 dc477cfe4e08a3196925fc6607391c1862676bc9d8d7b5900bdd8a272e25227b \
 --patched-intervene "$A/intervene_patch.py" --original-amendment "$TASK/amendment_approval.json" \
 --original-signature "$TASK/amendment_approval.json.sig" --original-reviewer-key "$TASK/amendment_reviewer.pub" \
 --original-reviewer-key-sha256 651a664911caea0300f5536204b6dec1cef824e9c242905d7ffc2dbda713630f \
 --watch-envelope /data2/zhangzibo/arxiv-tssa/preparations/tcl104-shard-watch-20261030.json --watch-key "$A/watch.pub" --verify-only
```

本地验证命令：`.venv/bin/python -m unittest discover -s scripts/merging/trigger_contrast_localization -p 'test_*.py' -q`；未验证真实模型加载、跨主机 SSH 续期或 GPU 运行时表现。

## 104 图形系统进程追加修订

104 实测 GPU 1/2 上仅有 `gdm` UID 125 的 `gnome-shell` G 进程，各占 4 MiB；`/proc/6941/exe` 对当前账号不可读，因此允许权限拒绝时依据四个 UID、cmdline、系统二进制属主与权限做受限回退，并明确记录没有直接读取实际可执行文件。

追加修订限制 gdm 仅一个 G 进程且最多 8 MiB，其他进程、未知状态、权限异常和伪装均拒绝；原 GPU UUID、实时平台许可、其他用户进程及源观察门禁继续生效，原冻结 `resource_gate.py` 不改动。

先独立审阅本机三个新增文件，生成并签署独立资源修订；新签名绑定原门禁、补丁、启动器、当前 shard runner 和 policy 的准确哈希，与已签 shard 修订并存。

```bash
TASK=/Users/zzb/arxiv/research/tasks/2026-10-29-trigger-contrast-localization
python3 "$TASK/resource104_review_template.py" \
 --manifest "$TASK/manifest_candidate.json" --repository-root /Users/zzb/arxiv \
 --reviewer "$REVIEWER_PRINCIPAL" > "$RESOURCE_REVIEW"
ssh-keygen -Y sign -f "$REVIEW_PRIVATE_KEY" -n tcl-resource-amendment "$RESOURCE_REVIEW"
```

将三个新增 Python 文件、签名的资源修订原文及 `.sig` 上传到 104 的独立部署目录后，使用下列包装器启动原 shard 参数；`--` 后的完整参数与上一节 runner 命令完全相同，先加 `--verify-only` 再决定实际启动。

```bash
"$PY" "$A/resource104_launcher.py" --manifest "$TASK/manifest_candidate.json" \
 --repository-root "$CODE" --overlay "$A/resource104_gdm_patch.py" \
 --review "$A/resource104_review.json" --signature "$A/resource104_review.json.sig" \
 --reviewer-key "$A/review.pub" -- \
 --manifest "$TASK/manifest_candidate.json" --prompts "$TASK/prompts_tokenized_candidate.jsonl" \
 --context-review "$TASK/context_review.json" --m06-review "$TASK/m06_review.json" \
 --protocol "$PROTOCOL" --asset-manifest "$ASSETS" --models-root "$MODEL" --output-root "$OUT" \
 --repository-root "$CODE" --snapshot-root "$SNAP" --review-envelope "$A/review-envelope.json" \
 --reviewer-key "$A/review.pub" --reviewer-key-sha256 dc477cfe4e08a3196925fc6607391c1862676bc9d8d7b5900bdd8a272e25227b \
 --patched-intervene "$A/intervene_patch.py" --original-amendment "$TASK/amendment_approval.json" \
 --original-signature "$TASK/amendment_approval.json.sig" --original-reviewer-key "$TASK/amendment_reviewer.pub" \
 --original-reviewer-key-sha256 651a664911caea0300f5536204b6dec1cef824e9c242905d7ffc2dbda713630f \
 --watch-envelope /data2/zhangzibo/arxiv-tssa/preparations/tcl104-shard-watch-20261030.json --watch-key "$A/watch.pub" --verify-only
```

104 此前 CPU 阶段出现 CUDA driver initialization failed 提示，追加修订不验证驱动或消除该提示；正式许可后若 CUDA 初始化失败，保留真实错误和账本，不能记作图像完成。
