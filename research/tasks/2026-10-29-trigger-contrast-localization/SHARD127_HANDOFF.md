# 127 分片独立审阅交接

本地候选尚未在服务器部署或运行；127 身份固定为 `iipl-127`、machine-id SHA `99b0f2a4634566cc13b4686bcfad863346e6975d37221fb1fc27ebb0d814848d`、GPU 2 UUID `GPU-1805e9be-7fea-3c9f-afdf-32db622c0b91`。

- 103 原快照、冻结 manifest 与科学预算不变，127 仅处理从原 2048 个基线键排除 343 个完成项和 1 个不确定项后的 1704 个键，每键最多一次；104 现有分片实测 0 图、0 尝试，不能与 127 同时写入。
- 104 持锁守护使用原分片已有 `.run.lock`、以非阻塞 FLOCK 独占并确认旧目录无图且账本缺失或各计数为零；持锁 PID 和启动 ticks 要绑定独立签名，每次 127 前向登记前都核验两份未过期的 103 和 104 签名观察。
- 两份观察最长有效 30 秒且不得无新证据续签，连接故障或锁释放时停止登记并保留未决尝试；在线观察不是跨机原子栅栏，必须明确禁止任何人重启 103 原 run 或 104 旧分片，持锁失效到见证过期之间的竞态仍不能排除。
- 本分片即使全部完成仍只可累计 2047 个基线完成项，原未决项不可重放，不能计算完整基线门禁或启动后续版本；扩容预算或重试不属于本方案。

操作者仅在完成代码独立审阅后将 `shard127_104_fence.py` 部署至 104 本人 preparations；保持 104 的原 run 不执行，持锁过程应在独立 tmux 中持续运行，并从其标准输出记录 PID 与 start ticks。

```bash
python3 /data2/zhangzibo/arxiv-tssa/preparations/tcl127_104_fence.py hold \
 --identity-sha256 4ffb1ac179b6f8b913f752281da3f4cce6f1fc6c2fca9c730746f6e3ad9add0a
```

建议将 418 文件快照放到 127 的 `/data1/zhangzibo/arxiv-tssa/preparations/tcl127-shard-snapshot-20261030T0200Z` 并核验清单，所有路径使用本机 `/data1`；新增脚本与签名放独立 `A`，不得修改 `SNAP`。

```bash
SNAP=/data1/zhangzibo/arxiv-tssa/preparations/tcl127-shard-snapshot-20261030T0200Z
CODE="$SNAP/code"
TASK="$CODE/research/tasks/2026-10-29-trigger-contrast-localization"
AMEND="$SNAP/amendment"
PROTOCOL="$CODE/research/tssa_mvp_2026-10-26.json"
ASSETS="$CODE/research/tssa_mvp_assets_2026-10-26.json"
A=/data1/zhangzibo/arxiv-tssa/preparations/tcl127-shard-executor-20261030
MODEL=/data1/zhangzibo/arxiv-tssa/models
PY=/data1/zhangzibo/arxiv-tssa/venv/bin/python
```

`MODEL` 与 `PY` 只有在 127 实际部署和校验到上述路径时才使用，若实际不同则替换为本人数据盘真实路径；将原 `amendment_launcher.py` 的逐字节副本放到 `A`，其 SHA 仍受原修订和新审核约束。

```bash
OUT=/data1/zhangzibo/arxiv-tssa/results/tcl-20261029-01-v1-shard127-20261030
"$PY" "$A/shard127_plan.py" --manifest "$TASK/manifest_candidate.json" \
 --prompts "$TASK/prompts_tokenized_candidate.jsonl" --context-review "$TASK/context_review.json" \
 --m06-review "$TASK/m06_review.json" --repository-root "$CODE" --snapshot-root "$SNAP" \
 --snapshot-manifest-sha256 dca8ba3a758b8641092026df5bc1b7ca5d91fdda79b5e1bb2d8fa6229cb3dd5b > "$A/candidate127.json"
```

将候选取回本机并审阅，使用实际持锁 PID 和 start ticks 生成独立签名；签名绑定 127 执行器、两台源观察及依赖、104 原身份、GPU UUID 和旧原 run 禁止重启约束。

```bash
TASK=/Users/zzb/arxiv/research/tasks/2026-10-29-trigger-contrast-localization
python3 "$TASK/shard127_review_template.py" --candidate "$CANDIDATE" \
 --original-amendment "$TASK/amendment_approval.json" --original-signature "$TASK/amendment_approval.json.sig" \
 --original-reviewer-key "$TASK/amendment_reviewer.pub" --patched-intervene "$TASK/intervene_patch.py" \
 --reviewer "$REVIEWER_PRINCIPAL" --watch-principal "$WATCH_PRINCIPAL" \
 --fence-pid "$FENCE_PID" --fence-start "$FENCE_START" > "$REVIEW_MESSAGE"
ssh-keygen -Y sign -f "$REVIEW_PRIVATE_KEY" -n tcl-shard-review "$REVIEW_MESSAGE"
python3 - "$REVIEW_MESSAGE" "$REVIEW_MESSAGE.sig" "$REVIEW_ENVELOPE" <<'PY'
import base64,json,pathlib,sys
message,signature,out=map(pathlib.Path,sys.argv[1:])
out.write_text(json.dumps({'message_b64':base64.b64encode(message.read_bytes()).decode(),'signature_b64':base64.b64encode(signature.read_bytes()).decode()},sort_keys=True,separators=(',',':')))
PY
```

本机控制器通过本人 SSH 配置分别读取 103 原源守护和 104 锁守护，签名后原子发布到 127；`CANDIDATE_SHA` 是候选规范化 SHA，`ATTEMPTS_SHA` 是候选内 `source_attempts_logical_sha256`。

```bash
CANDIDATE_SHA=$(python3 - "$CANDIDATE" <<'PY'
import hashlib,json,sys
v=json.load(open(sys.argv[1]));print(hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest())
PY
)
ATTEMPTS_SHA=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["source_attempts_logical_sha256"])' "$CANDIDATE")
python3 "$TASK/shard127_watch_controller.py" --ssh-config /Users/zzb/arxiv/server/school_ssh_config \
 --watch-private-key "$WATCH_PRIVATE_KEY" --watch-public-key "$WATCH_PUBLIC_KEY" \
 --watch-key-sha256 85f4e02cb2765186d72fa4be1cba1b95a00d316d9083b98d99c00d3f61f9a9da \
 --principal "$WATCH_PRINCIPAL" --plan-sha256 "$CANDIDATE_SHA" --source-attempts-sha256 "$ATTEMPTS_SHA" \
 --manifest-sha256 c597deebc3c2256401ee89b47f96ba9caa4bd92502019e3f257cfde7cddd1aaa \
 --source-guard-sha256 2a166e8b22de9d087bc98f73736186af7a9f18546545d26e71e7e8e5d20dc8e6 \
 --fence-guard-sha256 9c3f40430afba9f8cacc4ef8bcced4cbbeda3ff2472b9d3befb4a1c7aa03e0e2 \
 --fence-pid "$FENCE_PID" --fence-start "$FENCE_START"
```

127 使用独立审核签名、实际 UUID 和现有原始资源门禁，无需 104 的 gdm 修订；先加 `--verify-only` 检查冻结输入与签名，实际启动后的 CPU 阶段结束时再根据 nonce、实时平台与进程复查生成许可。

```bash
export CUBLAS_WORKSPACE_CONFIG=:4096:8
export GPU_UUID=GPU-1805e9be-7fea-3c9f-afdf-32db622c0b91
export CUDA_VISIBLE_DEVICES="$GPU_UUID"
"$PY" "$A/shard127_runner.py" --manifest "$TASK/manifest_candidate.json" \
 --prompts "$TASK/prompts_tokenized_candidate.jsonl" --context-review "$TASK/context_review.json" \
 --m06-review "$TASK/m06_review.json" --protocol "$PROTOCOL" --asset-manifest "$ASSETS" \
 --models-root "$MODEL" --output-root "$OUT" --repository-root "$CODE" --snapshot-root "$SNAP" \
 --review-envelope "$A/review-envelope.json" --reviewer-key "$A/review.pub" \
 --reviewer-key-sha256 dc477cfe4e08a3196925fc6607391c1862676bc9d8d7b5900bdd8a272e25227b \
 --patched-intervene "$AMEND/intervene_patch.py" --original-amendment "$AMEND/amendment_approval.json" \
 --original-signature "$AMEND/amendment_approval.json.sig" --original-reviewer-key "$AMEND/amendment_reviewer.pub" \
 --original-reviewer-key-sha256 651a664911caea0300f5536204b6dec1cef824e9c242905d7ffc2dbda713630f \
 --watch-envelope /data1/zhangzibo/arxiv-tssa/preparations/tcl127-source-watch-20261030.json \
 --fence-envelope /data1/zhangzibo/arxiv-tssa/preparations/tcl127-104-fence-watch-20261030.json \
 --watch-key "$A/watch.pub" --verify-only
```

移除 `--verify-only` 后先执行 CPU 资产与 tokenizer 全量核验，事件 `cpu_preflight` 成功后进入 `waiting_resource_permit`；此时才复查平台 127 GPU 2 是否禁用、他人占用、有效分配及本人跨机额度，并保存可追溯的观察证据及 UTC 时间。

从该事件取 `nonce`、`ready_at_utc` 和许可路径，使用真实复核时间与证据 SHA，构造下列许可并原子写入，许可只表达操作者的实际平台观察；驱动和 GPU 进程由冻结资源门禁即时只读核验。

```bash
python3 - "$OUT/resource_permit.json" "$NONCE" "$OBSERVED_UTC" "$PLATFORM_EVIDENCE_SHA" <<'PY'
import datetime,json,os,sys,tempfile
path,nonce,observed,evidence=sys.argv[1:]
now=datetime.datetime.now(datetime.timezone.utc)
data={'task_id':'TCL-20261029-01','run_id':'tcl-20261029-01-v1',
 'manifest_sha256':'c597deebc3c2256401ee89b47f96ba9caa4bd92502019e3f257cfde7cddd1aaa',
 'server':'school127','gpu_uuid':'GPU-1805e9be-7fea-3c9f-afdf-32db622c0b91','nonce':nonce,
 'issued_at_utc':now.isoformat(),'expires_at_utc':(now+datetime.timedelta(seconds=90)).isoformat(),
 'platform':{'source':'https://gpu.orz2333.fun/','observed_at_utc':observed,'sampling_valid':True,
             'disabled':False,'allocation_conflict':False,'quota_available':True,'evidence_sha256':evidence}}
fd,tmp=tempfile.mkstemp(prefix='.permit-',dir=os.path.dirname(path))
with os.fdopen(fd,'w') as f:
 json.dump(data,f,sort_keys=True);f.flush();os.fsync(f.fileno())
os.replace(tmp,path)
PY
```

若观察时间早于当前 CPU 门禁 `ready_at_utc`、许可过期、双源见证失效或 GPU 状态不符，执行器会拒绝进入 CUDA；127 已实测 `cuInit=0` 仅证明该时刻驱动可初始化，不证明本次模型或评分链通过。
