#!/bin/bash
set -euo pipefail
SNAP=/data1/zhangzibo/arxiv-tssa/preparations/tcl104-shard-snapshot-20261030T0200Z
CODE="$SNAP/code"
TASK="$CODE/research/tasks/2026-10-29-trigger-contrast-localization"
AMEND="$SNAP/amendment"
A=/data1/zhangzibo/arxiv-tssa/preparations/tcl127-shard-executor-20261030
MODEL=/data1/zhangzibo/arxiv-tssa/models
OUT=/data1/zhangzibo/arxiv-tssa/results/tcl-20261029-01-v1-shard127-20261030
PY=/data1/zhangzibo/arxiv-tssa/venv/bin/python
export CUBLAS_WORKSPACE_CONFIG=:4096:8
export GPU_UUID=GPU-1805e9be-7fea-3c9f-afdf-32db622c0b91
export CUDA_VISIBLE_DEVICES="$GPU_UUID"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export PYTHONPATH="$CODE"
exec "$PY" "$A/shard127_wait_launcher_v2.py" --wait-review "$A/shard127_wait_review_v2.json" --wait-signature "$A/shard127_wait_review_v2.json.sig" --prior-wait-review "$A/shard127_wait_review.json" --prior-wait-signature "$A/shard127_wait_review.json.sig" --reviewer-key "$A/shard104_reviewer.pub" --resource-launcher "$A/resource127_launcher.py" --patch "$A/shard127_watch_wait_v2.py" -- --manifest "$TASK/manifest_candidate.json" --repository-root "$CODE" --overlay "$A/resource127_gdm_xorg_patch.py" --review "$A/resource127_review.json" --signature "$A/resource127_review.json.sig" --reviewer-key "$A/shard104_reviewer.pub" -- --manifest "$TASK/manifest_candidate.json" --prompts "$TASK/prompts_tokenized_candidate.jsonl" --context-review "$TASK/context_review.json" --m06-review "$TASK/m06_review.json" --protocol "$CODE/research/tssa_mvp_2026-10-26.json" --asset-manifest "$CODE/research/tssa_mvp_assets_2026-10-26.json" --models-root "$MODEL" --output-root "$OUT" --repository-root "$CODE" --snapshot-root "$SNAP" --review-envelope "$A/review-envelope.json" --reviewer-key "$A/shard104_reviewer.pub" --reviewer-key-sha256 dc477cfe4e08a3196925fc6607391c1862676bc9d8d7b5900bdd8a272e25227b --patched-intervene "$AMEND/intervene_patch.py" --original-amendment "$AMEND/amendment_approval.json" --original-signature "$AMEND/amendment_approval.json.sig" --original-reviewer-key "$AMEND/amendment_reviewer.pub" --original-reviewer-key-sha256 651a664911caea0300f5536204b6dec1cef824e9c242905d7ffc2dbda713630f --watch-envelope /data1/zhangzibo/arxiv-tssa/preparations/tcl127-source-watch-20261030.json --fence-envelope /data1/zhangzibo/arxiv-tssa/preparations/tcl127-104-fence-watch-20261030.json --watch-key "$A/shard104_watch.pub" "$@"
