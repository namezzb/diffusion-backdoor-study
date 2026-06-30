#!/bin/bash
# Eval Extra Metrics - Run CLIP_p, CLIP_c, FID, LPIPS for all T2I methods
# These metrics are missing from the original eval_queue which only runs ACCASR
# Uses checkpoint markers for resume
set -uo pipefail

BD="/opt/data/private/BackdoorDM"
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
LOGDIR="$BD/logs/eval_extra"
MARKER_DIR="$LOGDIR/done"
mkdir -p "$LOGDIR" "$MARKER_DIR"

cd "$BD"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOGDIR/extra_queue.log"; }

run_eval() {
    local marker_name="$1"
    shift
    local marker_file="$MARKER_DIR/done_${marker_name}"

    if [ -f "$marker_file" ]; then
        log "SKIP: $marker_name (marker exists)"
        return 0
    fi

    log "=== Extra Eval: $marker_name ==="
    if "$@" > "$LOGDIR/${marker_name}.log" 2>&1; then
        touch "$marker_file"
        log "DONE: $marker_name"
    else
        log "FAILED: $marker_name (exit $?)"
    fi
}

# Check if a T2I method has a trained model
model_exists() {
    local method="$1"
    # Check common result directories for model files
    for dir in "$BD/results/${method}_sd15" "$BD/results/${method}"; do
        if [ -d "$dir" ]; then
            if find "$dir" -name '*.pt' -o -name '*.safetensors' -o -name '*.bin' 2>/dev/null | grep -q .; then
                return 0
            fi
        fi
    done
    return 1
}

log "=========================================="
log "EXTRA METRICS QUEUE STARTED"
log "Running CLIP_p, CLIP_c, FID, LPIPS for all trained T2I methods"
log "=========================================="

# All T2I methods that need extra metrics
T2I_METHODS="eviledit eviledit_numAdd rickrolling_TPA rickrolling_TAA paas_ti paas_db badt2i_pixel badt2i_object badt2i_style badt2i_objectAdd bibaddiff villandiffusion_cond"

for method in $T2I_METHODS; do
    # Skip if model doesn't exist yet
    if ! model_exists "$method"; then
        log "SKIP: $method (model not trained yet)"
        continue
    fi

    log "--- Processing $method ---"

    # CLIP_p (Target CLIP Score)
    run_eval "${method}_CLIP_p" \
        $PYTHON evaluation/main_eval.py --metric CLIP_p --backdoor_method "$method" --device cuda:0

    # CLIP_c (Benign CLIP Score)
    run_eval "${method}_CLIP_c" \
        $PYTHON evaluation/main_eval.py --metric CLIP_c --backdoor_method "$method" --device cuda:0

    # FID
    run_eval "${method}_FID" \
        $PYTHON evaluation/main_eval.py --metric FID --backdoor_method "$method" --device cuda:0

    # LPIPS
    run_eval "${method}_LPIPS" \
        $PYTHON evaluation/main_eval.py --metric LPIPS --backdoor_method "$method" --device cuda:0
done

# InviBackdoor needs LPIPS (unconditional method)
if model_exists "invi_backdoor"; then
    run_eval "invi_backdoor_LPIPS" \
        $PYTHON evaluation/main_eval.py --metric LPIPS --backdoor_method invi_backdoor \
        --backdoored_model_path ./results/results/invi_backdoor_DDPM-CIFAR10-32 \
        --val_data cifar10 --device cuda:0
fi

log "=========================================="
log "EXTRA METRICS QUEUE COMPLETE"
log "=========================================="

FAILED=$(grep -c "FAILED:" "$LOGDIR/extra_queue.log" 2>/dev/null) || FAILED=0
if [ "$FAILED" -gt 0 ]; then
    log "WARNING: $FAILED extra eval(s) failed."
    grep "FAILED:" "$LOGDIR/extra_queue.log"
fi

log "All extra metrics done. Check $LOGDIR/ for detailed logs."
