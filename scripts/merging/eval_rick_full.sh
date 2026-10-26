#!/bin/bash
# Evaluate trained TE checkpoint + amplification baselines
# Run AFTER: 1) grid done, 2) TE training done
cd /opt/data/private/BackdoorDM
PY=/opt/data/private/miniconda3/envs/eviledit/bin/python
BASE=/opt/data/private/models/stable-diffusion-v1-5
MAL='/opt/data/private/BackdoorDM/results/rickrolling_TPA_sd15/rickrolling_TPA_trigger-ȏ_target-cat'
TRAINED=/opt/data/private/merge_attack/mergerobust_te_v1
OUT=/opt/data/private/BackdoorDM/results/merge_tracer/m3_rick_eval_$(date +%Y%m%d)
mkdir -p "$OUT"

echo "=== 1. Trained checkpoint eval ==="
for A in 0.08 0.25 0.5 1.0; do
  TAG="trained_a${A//./p}"
  TE_DIR="$OUT/merged_te_${TAG}"
  $PY /opt/data/private/server/merge_text_encoder.py \
    --base-model-dir "$BASE" --malicious-text-encoder "$TRAINED" \
    --operator average --alpha "$A" --output "$TE_DIR" 2>&1 | tail -1
  EVAL_DIR="$OUT/eval_${TAG}"
  $PY evaluation/main_eval.py --metric ACCASR --backdoor_method rickrolling_TPA \
    --model_ver sd15 --bd_config attack/t2i_gen/configs/bd_config_objectRep.yaml \
    --bd_target_type objectRep --backdoored_model_path "$TE_DIR" \
    --bd_result_dir "$EVAL_DIR" --img_num_test 20 --infer_steps 25 --batch_size 10 \
    --device cuda 2>&1 | grep -E 'ASR_pair|ACC_pair'
  echo "RESULT trained $TAG done"
done

echo "=== 2. Amplification baselines ==="
for LAMBDA in 4 8 12 16; do
  for A in 0.08 0.25; do
    TAG="amp_l${LAMBDA}_a${A//./p}"
    TE_DIR="$OUT/merged_te_${TAG}"
    $PY /opt/data/private/server/merge_text_encoder.py \
      --base-model-dir "$BASE" --malicious-text-encoder "$MAL" \
      --operator average --alpha "$A" --lambda-scale "$LAMBDA" --output "$TE_DIR" 2>&1 | tail -1
    EVAL_DIR="$OUT/eval_${TAG}"
    $PY evaluation/main_eval.py --metric ACCASR --backdoor_method rickrolling_TPA \
      --model_ver sd15 --bd_config attack/t2i_gen/configs/bd_config_objectRep.yaml \
      --bd_target_type objectRep --backdoored_model_path "$TE_DIR" \
      --bd_result_dir "$EVAL_DIR" --img_num_test 20 --infer_steps 25 --batch_size 10 \
      --device cuda 2>&1 | grep -E 'ASR_pair|ACC_pair'
    echo "RESULT $TAG done"
  done
done

echo "=== 3. CLIP + FID on trained checkpoint at alpha=0.08 ==="
TE_DIR="$OUT/merged_te_trained_a0p08"
for METRIC in CLIP_p_0 CLIP_c FID; do
  $PY evaluation/main_eval.py --metric "$METRIC" --backdoor_method rickrolling_TPA \
    --model_ver sd15 --bd_config attack/t2i_gen/configs/bd_config_objectRep.yaml \
    --bd_target_type objectRep --backdoored_model_path "$TE_DIR" \
    --bd_result_dir "$OUT/eval_clip_fid_trained_a0p08" \
    --img_num_test 100 --infer_steps 25 --batch_size 10 --device cuda 2>&1 | tail -2
done

echo "ALL EVAL DONE"
