#!/bin/bash
# TSSA multi-attack experiment: Apply TSSA to EvilEdit and BadT2I Object
# Tests M1 baseline, LoBAM amplification, and TSSA across α values
set -e
cd /opt/data/private/BackdoorDM
PY=/opt/data/private/miniconda3/envs/eviledit/bin/python
BASE=/opt/data/private/models/stable-diffusion-v1-5
OUT=/opt/data/private/BackdoorDM/results/merge_tracer/tssa_multi_20260731
mkdir -p "$OUT"
RESULTS="$OUT/multi_attack_results.csv"
echo "attack,method,operator,alpha,lambda,tssa,tssa_p,num_test,acc,asr,delta_l2,timestamp" > "$RESULTS"

# ---- EvilEdit config ----
EVIL_MAL="/opt/data/private/BackdoorDM/results/eviledit_sd15/eviledit_trigger-beautifuldog_target-cat.pt"
EVIL_METHOD="eviledit"
EVIL_SAVE="pt"

# ---- BadT2I Object config ----
BADT2I_MAL="/opt/data/private/BackdoorDM/results/badt2i_object_sd15/badt2i_object_trigger-u200b_target-cat"
BADT2I_METHOD="badt2i"
BADT2I_SAVE="pipeline"

run_amplify() {
  local ATTACK=$1 MAL_PATH=$2 LAM=$3 TSSA_FLAG=$4 TSSA_P=$5
  local TAG="${ATTACK}_${TSSA_FLAG}_l${LAM}"
  local AMP_OUT="$OUT/amplified_${TAG}.pt"
  local TSSA_ARGS=""
  if [ "$TSSA_FLAG" = "tssa" ]; then
    TSSA_ARGS="--tssa --tssa-percentile $TSSA_P --tssa-residual-lambda 1.0"
  else
    TSSA_ARGS="--no-tssa"
  fi
  echo "=== AMPLIFY $TAG ===" >&2
  "$PY" /opt/data/private/server/apply_tssa_unet.py \
    --base-model-dir "$BASE" --malicious-unet "$MAL_PATH" \
    --lambda-scale "$LAM" $TSSA_ARGS --output "$AMP_OUT" 2>&1 | tail -3 >&2
  echo "$AMP_OUT"
}

run_merge_eval() {
  local ATTACK=$1 MAL_PATH=$2 METHOD=$3 SAVE_MODE=$4 OP=$5 A=$6 LAM=$7 TSSA_FLAG=$8 TSSA_P=$9
  local TAG="${ATTACK}_${TSSA_FLAG}_${OP}_a${A//./p}_l${LAM}"

  # If amplification needed, create amplified UNet first
  local MERGE_MAL="$MAL_PATH"
  if [ "$TSSA_FLAG" != "m1" ]; then
    MERGE_MAL=$(run_amplify "$ATTACK" "$MAL_PATH" "$LAM" "$TSSA_FLAG" "$TSSA_P")
  fi

  # Merge
  local MERGED_OUT="$OUT/merged_${TAG}"
  local MERGE_ARGS="--base-model-dir $BASE --malicious-unet $MERGE_MAL --operator $OP --alpha $A --benign-unet $BASE/unet"

  echo "=== MERGE $TAG ==="
  if [ "$SAVE_MODE" = "pt" ]; then
    "$PY" /opt/data/private/server/merge_tracer.py $MERGE_ARGS --output "${MERGED_OUT}.pt" 2>&1 | tail -2
    EVAL_PATH="${MERGED_OUT}.pt"
  else
    "$PY" /opt/data/private/server/merge_tracer.py $MERGE_ARGS --save-pipeline-dir "$MERGED_OUT" 2>&1 | tail -2
    EVAL_PATH="$MERGED_OUT"
  fi

  # Evaluate
  local EVAL_DIR="$OUT/eval_${TAG}"
  echo "=== EVAL $TAG ==="
  "$PY" evaluation/main_eval.py --metric ACCASR --backdoor_method "$METHOD" \
    --model_ver sd15 --bd_config attack/t2i_gen/configs/bd_config_objectRep.yaml \
    --bd_target_type objectRep --backdoored_model_path "$EVAL_PATH" \
    --bd_result_dir "$EVAL_DIR" --img_num_test 20 --infer_steps 25 --batch_size 10 \
    --device cuda 2>&1 | grep -E 'ASR_pair|ACC_pair'

  # Extract metrics
  ACC=$("$PY" -c "
import csv
r=list(csv.DictReader(open('$EVAL_DIR/eval_results.csv'),delimiter='\t'))
acc=[x for x in r if 'acc' in x.get('metric','').lower()]
print(acc[0]['score'] if acc else 'NA')" 2>/dev/null || echo "NA")
  ASR=$("$PY" -c "
import csv
r=list(csv.DictReader(open('$EVAL_DIR/eval_results.csv'),delimiter='\t'))
asr=[x for x in r if 'asr' in x.get('metric','').lower()]
print(asr[0]['score'] if asr else 'NA')" 2>/dev/null || echo "NA")

  echo "$ATTACK,$TSSA_FLAG,$OP,$A,$LAM,$TSSA_FLAG,$TSSA_P,20,$ACC,$ASR,NA,$(date -Iseconds)" >> "$RESULTS"
  echo "RESULT $TAG: acc=$ACC asr=$ASR"
}

# ===== EvilEdit experiments =====
echo "===== EvilEdit: M1 / LoBAM / TSSA ====="
for A in 0.08 0.25 0.50 1.00; do
  run_merge_eval "eviledit" "$EVIL_MAL" "$EVIL_METHOD" "$EVIL_SAVE" "lerp" "$A" 1.0 m1 0
  run_merge_eval "eviledit" "$EVIL_MAL" "$EVIL_METHOD" "$EVIL_SAVE" "lerp" "$A" 16.0 lobam 0
  run_merge_eval "eviledit" "$EVIL_MAL" "$EVIL_METHOD" "$EVIL_SAVE" "lerp" "$A" 16.0 tssa 95
done

# ===== BadT2I Object experiments =====
echo "===== BadT2I Object: M1 / LoBAM / TSSA ====="
for A in 0.08 0.25 0.50 1.00; do
  run_merge_eval "badt2i_object" "$BADT2I_MAL" "$BADT2I_METHOD" "$BADT2I_SAVE" "lerp" "$A" 1.0 m1 0
  run_merge_eval "badt2i_object" "$BADT2I_MAL" "$BADT2I_METHOD" "$BADT2I_SAVE" "lerp" "$A" 16.0 lobam 0
  run_merge_eval "badt2i_object" "$BADT2I_MAL" "$BADT2I_METHOD" "$BADT2I_SAVE" "lerp" "$A" 16.0 tssa 95
done

echo "===== ALL DONE ====="
cat "$RESULTS"
