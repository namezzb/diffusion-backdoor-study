#!/bin/bash
# Evaluation Queue Script v2 - Run all pending evaluations sequentially
# FIX: checkpoint markers for resume, proper failure detection
export HF_DATASETS_OFFLINE=1
export HF_HUB_OFFLINE=1
set -uo pipefail

BD="/opt/data/private/BackdoorDM"
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
LOGDIR="$BD/logs/eval_queue"
MARKER_DIR="$LOGDIR/done"
mkdir -p "$LOGDIR" "$MARKER_DIR"

cd "$BD"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOGDIR/queue.log"; }

# run_eval: checkpoint-aware eval runner
# Args: marker_name, python_cmd_and_args...
run_eval() {
    local marker_name="$1"
    shift
    local marker_file="$MARKER_DIR/done_${marker_name}"

    if [ -f "$marker_file" ]; then
        log "SKIP: $marker_name (marker exists, already done)"
        return 0
    fi

    log "=== Eval: $marker_name ==="
    if "$@" > "$LOGDIR/${marker_name}.log" 2>&1; then
        touch "$marker_file"
        log "DONE: $marker_name"
    else
        local rc=$?
        log "FAILED: $marker_name (exit code $rc)"
        # Don't create marker - will retry on next restart
    fi
}

log "=========================================="
log "EVALUATION QUEUE STARTED (v2 with checkpoints)"
log "=========================================="

# ============================================================
# T2I Methods - ACCASR metric
# ============================================================

# 1. EvilEdit numAdd (objectAdd)
run_eval "eviledit_numAdd_ACCASR" \
    $PYTHON evaluation/main_eval.py --metric ACCASR --backdoor_method eviledit_numAdd --device cuda:0

# 2. RickRolling TAA (styleAdd)
run_eval "rickrolling_TAA_ACCASR" \
    $PYTHON evaluation/main_eval.py --metric ACCASR --backdoor_method rickrolling_TAA --device cuda:0

# 3. PaaS DB (objectRep)
run_eval "paas_db_ACCASR" \
    $PYTHON evaluation/main_eval.py --metric ACCASR --backdoor_method paas_db --device cuda:0

# ============================================================
# Unconditional Methods - FID + MSE metrics
# ============================================================

# 4. BadDiffusion FID
run_eval "baddiffusion_FID" \
    $PYTHON evaluation/main_eval.py --metric FID --backdoor_method baddiffusion \
    --backdoored_model_path ./results/baddiffusion_DDPM-CIFAR10-32 \
    --val_data cifar10 --device cuda:0

# 5. BadDiffusion MSE
run_eval "baddiffusion_MSE" \
    $PYTHON evaluation/main_eval.py --metric MSE --backdoor_method baddiffusion \
    --backdoored_model_path ./results/baddiffusion_DDPM-CIFAR10-32 \
    --val_data cifar10 --device cuda:0

# 6. TrojDiff FID
run_eval "trojdiff_FID" \
    $PYTHON evaluation/main_eval.py --metric FID --backdoor_method trojdiff \
    --backdoored_model_path ./results/trojdiff_DDPM-CIFAR10-32 \
    --val_data cifar10 --device cuda:0

# 7. TrojDiff MSE
run_eval "trojdiff_MSE" \
    $PYTHON evaluation/main_eval.py --metric MSE --backdoor_method trojdiff \
    --backdoored_model_path ./results/trojdiff_DDPM-CIFAR10-32 \
    --val_data cifar10 --device cuda:0

# 8. VillanDiffusion uncond FID
run_eval "villandiffusion_FID" \
    $PYTHON evaluation/main_eval.py --metric FID --backdoor_method villandiffusion \
    --backdoored_model_path ./results/villandiffusion_DDPM-CIFAR10-32 \
    --val_data cifar10 --device cuda:0

# 9. VillanDiffusion uncond MSE
run_eval "villandiffusion_MSE" \
    $PYTHON evaluation/main_eval.py --metric MSE --backdoor_method villandiffusion \
    --backdoored_model_path ./results/villandiffusion_DDPM-CIFAR10-32 \
    --val_data cifar10 --device cuda:0

# ============================================================
# Summary
# ============================================================
log "=========================================="
log "EVALUATION QUEUE COMPLETE"
log "=========================================="

# Report failures
FAILED=$(grep -c "FAILED:" "$LOGDIR/queue.log" 2>/dev/null || echo 0)
if [ "$FAILED" -gt 0 ]; then
    log "WARNING: $FAILED eval(s) failed. Check logs for details."
    grep "FAILED:" "$LOGDIR/queue.log"
fi

log "Results summary:"
for f in $BD/results/*/eval_results.csv; do
    log "--- $(basename $(dirname $f)) ---"
    cat "$f" 2>/dev/null | tee -a "$LOGDIR/queue.log"
done

log "All done. Check $LOGDIR/ for detailed logs."
