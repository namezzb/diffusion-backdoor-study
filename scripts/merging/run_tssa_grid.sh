#!/bin/bash
# TSSA experiment: Trigger-Salient Selective Amplification
# Tests optimized formula vs original across α values and merge operators
set -e
cd /opt/data/private/BackdoorDM
PY=/opt/data/private/miniconda3/envs/eviledit/bin/python
BASE=/opt/data/private/models/stable-diffusion-v1-5
MAL='/opt/data/private/BackdoorDM/results/rickrolling_TPA_sd15/rickrolling_TPA_trigger-ȏ_target-cat'
OUT=/opt/data/private/BackdoorDM/results/merge_tracer/tssa_20260730
mkdir -p "$OUT"
RESULTS="$OUT/tssa_results.csv"
echo "method,operator,alpha,lambda,tssa,tssa_p,num_test,acc,asr,delta_l2,timestamp" > "$RESULTS"

run_cell() {
  local METHOD=$1 OP=$2 A=$3 LAM=$4 TSSA_FLAG=$5 TSSA_P=$6
  local TAG="${METHOD}_${OP}_a${A//./p}_l${LAM//./p}"
  [ "$TSSA_FLAG" = "tssa" ] && TAG="${TAG}_tssa${TSSA_P}"

  TE_DIR="$OUT/merged_te_${TAG}"
  echo "=== MERGE $TAG ==="
  TSSA_ARGS=""
  [ "$TSSA_FLAG" = "tssa" ] && TSSA_ARGS="--tssa --tssa-percentile $TSSA_P"
  "$PY" /opt/data/private/server/merge_text_encoder.py \
    --base-model-dir "$BASE" --malicious-text-encoder "$MAL" \
    --operator "$OP" --alpha "$A" --lambda-scale "$LAM" \
    $TSSA_ARGS --output "$TE_DIR" 2>&1 | tail -3

  EVAL_DIR="$OUT/eval_${TAG}"
  echo "=== EVAL $TAG ==="
  "$PY" evaluation/main_eval.py --metric ACCASR --backdoor_method rickrolling_TPA \
    --model_ver sd15 --bd_config attack/t2i_gen/configs/bd_config_objectRep.yaml \
    --bd_target_type objectRep --backdoored_model_path "$TE_DIR" \
    --bd_result_dir "$EVAL_DIR" --img_num_test 20 --infer_steps 25 --batch_size 10 \
    --device cuda 2>&1 | grep -E 'ASR_pair|ACC_pair'

  ACC=$("$PY" -c "import csv;r=list(csv.DictReader(open('$EVAL_DIR/eval_results.csv')));print([x for x in r if 'acc' in x['metric']][0]['score'] if r else 'NA')" 2>/dev/null || echo "NA")
  ASR=$("$PY" -c "import csv;r=list(csv.DictReader(open('$EVAL_DIR/eval_results.csv')));print([x for x in r if 'asr' in x['metric']][0]['score'] if r else 'NA')" 2>/dev/null || echo "NA")
  DL2=$("$PY" -c "import json;d=json.load(open('$OUT/merge_merged_te_${TAG}_report.json'));print(round(d['merged_delta_l2'],2))" 2>/dev/null || echo "NA")

  echo "$METHOD,$OP,$A,$LAM,$TSSA_FLAG,$TSSA_P,20,$ACC,$ASR,$DL2,$(date -Iseconds)" >> "$RESULTS"
  echo "RESULT $TAG: acc=$ACC asr=$ASR dl2=$DL2"
}

echo "===== Phase 1: TSSA λ=16 p=80 (main experiment) ====="
for OP in average ties dare; do
  for A in 0.08 0.25 0.50 0.75 1.00; do
    run_cell "TSSA" "$OP" "$A" 16.0 tssa 80
  done
done

echo "===== Phase 2: TSSA λ=32 p=80 (higher amplification) ====="
for A in 0.08 0.25 0.50 0.75 1.00; do
  run_cell "TSSA" "average" "$A" 32.0 tssa 80
done

echo "===== Phase 3: TSSA λ=16 p=90 (fewer params amplified) ====="
for A in 0.08 0.25 0.50 0.75 1.00; do
  run_cell "TSSA" "average" "$A" 16.0 tssa 90
done

echo "===== Phase 4: Baseline original λ=16 (no TSSA) ====="
for A in 0.08 0.25 0.50 0.75 1.00; do
  run_cell "Original" "average" "$A" 16.0 notssa 0
done

echo "===== ALL DONE ====="
cat "$RESULTS"
