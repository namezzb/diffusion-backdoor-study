#!/usr/bin/env bash
set -euo pipefail

BD="${BD:-/opt/data/private/BackdoorDM}"
PY="${PY:-/opt/data/private/miniconda3/envs/eviledit/bin/python}"
RESULT="${RESULT:-results/invi_backdoor_DDPM-CELEBA-HQ-256}"
DEVICE="${DEVICE:-cuda:0}"
EVAL_MAX_BATCH="${EVAL_MAX_BATCH:-32}"
IMG_NUM="${IMG_NUM:-1000}"

cd "$BD"

if pgrep -af 'python.*invi_backdoor.py' >/dev/null; then
  echo "Refusing to run eval: InviBackdoor training is still active." >&2
  pgrep -af 'python.*invi_backdoor.py' >&2 || true
  exit 2
fi

"$PY" - <<'PY'
import sys, torch
p = "results/invi_backdoor_DDPM-CELEBA-HQ-256/data.ckpt"
ckpt = torch.load(p, map_location="cpu")
epoch = int(ckpt.get("epoch", -1))
step = int(ckpt.get("step", -1))
print({"epoch": epoch, "step": step})
if epoch < 49:
    raise SystemExit(f"Refusing to run eval: expected completed epoch >=49, got epoch={epoch}, step={step}")
PY

stale_dir="$RESULT/bd_generated_CELEBA-HQ_${IMG_NUM}"
if [[ -d "$stale_dir" ]]; then
  echo "Removing stale generated samples: $stale_dir"
  rm -rf "$stale_dir"
fi

"$PY" evaluation/main_eval.py \
  --metric FID \
  --backdoor_method invi_backdoor \
  --backdoored_model_path "$RESULT" \
  --bd_result_dir "$RESULT" \
  --model_ver DDPM-CELEBA-HQ-256 \
  --val_data CELEBA-HQ \
  --img_num_FID "$IMG_NUM" \
  --eval_max_batch "$EVAL_MAX_BATCH" \
  --infer_steps 1000 \
  --device "$DEVICE"

"$PY" server/run_invi_mse_stream.py \
  --repo "$BD" \
  --out-dir "$RESULT/bd_generated_CELEBA-HQ_${IMG_NUM}" \
  --record-file "$RESULT/eval_results.csv" \
  --img-num "$IMG_NUM"

tail -10 "$RESULT/eval_results.csv"
