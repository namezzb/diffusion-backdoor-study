#!/bin/bash
# TSSA residual lambda test: fix ACC at α=0.08 while maintaining ASR at α=1.0
set -e
cd /opt/data/private/BackdoorDM
PY=/opt/data/private/miniconda3/envs/eviledit/bin/python
BASE=/opt/data/private/models/stable-diffusion-v1-5
MAL='/opt/data/private/BackdoorDM/results/rickrolling_TPA_sd15/rickrolling_TPA_trigger-ȏ_target-cat'
OUT=/opt/data/private/BackdoorDM/results/merge_tracer/tssa_res_20260730
mkdir -p "$OUT"
RESULTS="$OUT/tssa_res_results.csv"
echo "method,operator,alpha,lambda,tssa_p,res_lambda,num_test,acc,asr,delta_l2,timestamp" > "$RESULTS"

run_cell() {
  local OP=$1 A=$2 LAM=$3 TSSA_P=$4 RES_LAM=$5
  local TAG="res${RES_LAM//./p}_${OP}_a${A//./p}_l${LAM//./p}_p${TSSA_P}"
  TE_DIR="$OUT/merged_te_${TAG}"
  echo "=== MERGE $TAG ==="
  "$PY" /opt/data/private/server/merge_text_encoder.py \
    --base-model-dir "$BASE" --malicious-text-encoder "$MAL" \
    --operator "$OP" --alpha "$A" --lambda-scale "$LAM" \
    --tssa --tssa-percentile "$TSSA_P" --tssa-residual-lambda "$RES_LAM" \
    --output "$TE_DIR" 2>&1 | tail -3

  EVAL_DIR="$OUT/eval_${TAG}"
  echo "=== EVAL $TAG ==="
  "$PY" evaluation/main_eval.py --metric ACCASR --backdoor_method rickrolling_TPA \
    --model_ver sd15 --bd_config attack/t2i_gen/configs/bd_config_objectRep.yaml \
    --bd_target_type objectRep --backdoored_model_path "$TE_DIR" \
    --bd_result_dir "$EVAL_DIR" --img_num_test 20 --infer_steps 25 --batch_size 10 \
    --device cuda 2>&1 | grep -E 'ASR_pair|ACC_pair'

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
  DL2=$("$PY" -c "import json;d=json.load(open('$OUT/merge_merged_te_${TAG}_report.json'));print(round(d['merged_delta_l2'],2))" 2>/dev/null || echo "NA")

  echo "TSSA_res,$OP,$A,$LAM,$TSSA_P,$RES_LAM,20,$ACC,$ASR,$DL2,$(date -Iseconds)" >> "$RESULTS"
  echo "RESULT $TAG: acc=$ACC asr=$ASR dl2=$DL2"
}

echo "===== Residual lambda=8 (moderate utility preservation) ====="
for A in 0.08 0.25 0.50 0.75 1.00; do
  run_cell average "$A" 16.0 80 8.0
done

echo "===== Residual lambda=4 (lower utility preservation) ====="
for A in 0.08 1.00; do
  run_cell average "$A" 16.0 80 4.0
done

echo "===== Residual lambda=2 (minimal utility preservation) ====="
for A in 0.08 1.00; do
  run_cell average "$A" 16.0 80 2.0
done

echo "===== DONE ====="
cat "$RESULTS"
