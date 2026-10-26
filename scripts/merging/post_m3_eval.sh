#!/bin/bash
# Post-M3 evaluation script: runs all comparisons for the T2I-MergeRobust paper.
# Usage: bash /opt/data/private/server/post_m3_eval.sh
# Run AFTER M3 training has completed (mergerobust_v2_kvqo.pt exists).

set -e
PY=/opt/data/private/miniconda3/envs/eviledit/bin/python
SCRIPT=/opt/data/private/server/run_merge_degradation.py
BDROOT=/opt/data/private/BackdoorDM
OUTROOT=/opt/data/private/BackdoorDM/results/merge_tracer
EXPERT=/opt/data/private/merge_experts/Realistic_Vision_V5.1_noVAE
EXPERT_NAME=RealisticVision
DATE=$(date +%Y%m%d)
LOGDIR=/opt/data/private/merge_attack/eval_logs
mkdir -p "$LOGDIR"

echo "========================================="
echo "Post-M3 Evaluation Pipeline - $DATE"
echo "========================================="

# --- 0. Verify M3 checkpoint exists ---
if [ ! -f /opt/data/private/merge_attack/mergerobust_v2_kvqo.pt ]; then
    echo "ERROR: M3 checkpoint not found. Run training first."
    exit 1
fi
echo "[0] M3 checkpoint verified."

# --- 1. Quick M3 evaluation (average only, 4 alphas, 20 prompts) ---
echo "[1] Quick M3 evaluation (average, 4 alphas, 20 prompts)..."
cd "$BDROOT"
$PY "$SCRIPT" \
    --attack mergerobust \
    --benign-unet "$EXPERT" --benign-name "$EXPERT_NAME" \
    --operators average \
    --alphas 0.08 0.25 0.5 1.0 \
    --seeds 0 \
    --img-num-test 20 --infer-steps 10 --batch-size 10 \
    --out-dir "$OUTROOT/m3_quick_mergerobust_$DATE" \
    --keep 2>&1 | tee "$LOGDIR/m3_quick.log"
echo "[1] Done. Quick results:"
cat "$OUTROOT/m3_quick_mergerobust_$DATE/degradation_results.csv" 2>/dev/null || echo "(no results yet)"

# --- 2. Full M3 evaluation (3 operators, 6 alphas, 50 prompts) ---
echo "[2] Full M3 evaluation (3 operators, 6 alphas, 50 prompts)..."
$PY "$SCRIPT" \
    --attack mergerobust \
    --benign-unet "$EXPERT" --benign-name "$EXPERT_NAME" \
    --operators average ties dare \
    --alphas 0.08 0.1 0.25 0.5 0.75 1.0 \
    --seeds 0 \
    --img-num-test 50 --infer-steps 25 --batch-size 10 \
    --out-dir "$OUTROOT/m3_full_mergerobust_$DATE" 2>&1 | tee "$LOGDIR/m3_full.log"
echo "[2] Done."

# --- 3. M1 baseline: Rickrolling TPA ---
echo "[3] M1 baseline: Rickrolling TPA..."
$PY "$SCRIPT" \
    --attack rickrolling_TPA \
    --benign-unet "$EXPERT" --benign-name "$EXPERT_NAME" \
    --operators average ties dare \
    --alphas 0.08 0.1 0.25 0.5 0.75 1.0 \
    --seeds 0 \
    --img-num-test 50 --infer-steps 25 --batch-size 10 \
    --out-dir "$OUTROOT/m1_rickrolling_$DATE" 2>&1 | tee "$LOGDIR/m1_rickrolling.log"
echo "[3] Done."

# --- 4. M1 baseline: BadT2I object ---
echo "[4] M1 baseline: BadT2I object..."
$PY "$SCRIPT" \
    --attack badt2i_object \
    --benign-unet "$EXPERT" --benign-name "$EXPERT_NAME" \
    --operators average ties dare \
    --alphas 0.08 0.1 0.25 0.5 0.75 1.0 \
    --seeds 0 \
    --img-num-test 50 --infer-steps 25 --batch-size 10 \
    --out-dir "$OUTROOT/m1_badt2i_$DATE" 2>&1 | tee "$LOGDIR/m1_badt2i.log"
echo "[4] Done."

# --- 5. Analysis ---
echo "[5] Generating analysis..."
$PY /opt/data/private/server/analyze_degradation.py \
    "$OUTROOT/m1_eviledit_20260728/degradation_results.csv" \
    "$OUTROOT/m3_full_mergerobust_$DATE/degradation_results.csv" \
    "$OUTROOT/m1_rickrolling_$DATE/degradation_results.csv" \
    "$OUTROOT/m1_badt2i_$DATE/degradation_results.csv" \
    --out-md "$LOGDIR/comparison_table.md" \
    --out-fig "$LOGDIR/asr_comparison.png" 2>&1 | tee "$LOGDIR/analysis.log"
echo "[5] Done. See: $LOGDIR/comparison_table.md"

echo "========================================="
echo "All evaluations complete!"
echo "Results: $LOGDIR/"
echo "========================================="
