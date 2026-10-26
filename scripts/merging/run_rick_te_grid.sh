#!/bin/bash
cd /opt/data/private/BackdoorDM
PY=/opt/data/private/miniconda3/envs/eviledit/bin/python
BASE=/opt/data/private/models/stable-diffusion-v1-5
MAL='/opt/data/private/BackdoorDM/results/rickrolling_TPA_sd15/rickrolling_TPA_trigger-ȏ_target-cat'
OUT=/opt/data/private/BackdoorDM/results/merge_tracer/m1_rick_te_20260730
mkdir -p "$OUT"
RESULTS="$OUT/degradation_results.csv"
echo "attack,benign,operator,alpha,seed,num_test,acc,asr,delta_l2,timestamp" > "$RESULTS"

for OP in average ties dare; do
  for A in 0.08 0.1 0.25 0.5 0.75 1.0; do
    TAG="${OP}_a${A//./p}"
    TE_DIR="$OUT/merged_te_${TAG}"
    echo "=== MERGE $TAG ==="
    "$PY" /opt/data/private/server/merge_text_encoder.py \
      --base-model-dir "$BASE" --malicious-text-encoder "$MAL" \
      --operator "$OP" --alpha "$A" --output "$TE_DIR" 2>&1 | tail -2
    EVAL_DIR="$OUT/eval_${TAG}"
    echo "=== EVAL $TAG ==="
    "$PY" evaluation/main_eval.py --metric ACCASR --backdoor_method rickrolling_TPA \
      --model_ver sd15 --bd_config attack/t2i_gen/configs/bd_config_objectRep.yaml \
      --bd_target_type objectRep --backdoored_model_path "$TE_DIR" \
      --bd_result_dir "$EVAL_DIR" --img_num_test 20 --infer_steps 25 --batch_size 10 \
      --device cuda 2>&1 | grep -E 'ASR_pair|ACC_pair'
    ACC=$("$PY" -c "import csv;r=list(csv.DictReader(open('$EVAL_DIR/eval_results.csv')));print([x for x in r if 'acc' in x['metric']][0]['score'] if r else 'NA')" 2>/dev/null)
    ASR=$("$PY" -c "import csv;r=list(csv.DictReader(open('$EVAL_DIR/eval_results.csv')));print([x for x in r if 'asr' in x['metric']][0]['score'] if r else 'NA')" 2>/dev/null)
    DL2=$("$PY" -c "import json;d=json.load(open('$OUT/merge_merged_te_${TAG}_report.json'));print(round(d['merged_delta_l2'],2))" 2>/dev/null)
    echo "rickrolling_TPA,RealisticVision,$OP,$A,0,20,$ACC,$ASR,$DL2,$(date -Iseconds)" >> "$RESULTS"
    echo "RESULT $TAG: acc=$ACC asr=$ASR"
  done
done
echo "GRID DONE"
