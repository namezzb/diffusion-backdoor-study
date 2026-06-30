#!/bin/bash
# BadT2I Retraining Script v2 - with checkpoint markers
set -uo pipefail

BD="/opt/data/private/BackdoorDM"
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
LOGDIR="$BD/logs/badt2i_retrain"
MARKER_DIR="$BD/logs/badt2i_retrain/done"
mkdir -p "$LOGDIR" "$MARKER_DIR"

cd "$BD"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOGDIR/retrain.log"; }

# run_step: checkpoint-aware step runner
run_step() {
    local marker_name="$1"
    shift
    local marker_file="$MARKER_DIR/done_${marker_name}"
    if [ -f "$marker_file" ]; then
        log "SKIP: $marker_name (already done)"
        return 0
    fi
    log "=== Running: $marker_name ==="
    if "$@" > "$LOGDIR/${marker_name}.log" 2>&1; then
        touch "$marker_file"
        log "DONE: $marker_name"
    else
        log "FAILED: $marker_name (exit $?)"
    fi
}

# ============================================================
# Step 1: Generate training data (~1h on GPU)
# ============================================================
IMG_COUNT=$(ls "$BD/datasets/laion_fallback/images/"*.png 2>/dev/null | wc -l)
if [ "$IMG_COUNT" -ge 500 ]; then
    log "Already have $IMG_COUNT images, skipping generation"
else
    run_step "data_gen" \
        $PYTHON scripts/generate_badt2i_data.py
fi

# ============================================================
# Step 2-5: Retrain BadT2I variants
# ============================================================
run_step "badt2i_pixel" \
    $PYTHON ./attack/t2i_gen/badt2i/badt2i_pixel.py \
    --base_config attack/t2i_gen/configs/base_config.yaml \
    --bd_config attack/t2i_gen/configs/bd_config_imagePatch.yaml \
    --model_ver sd15 --device cuda:0

run_step "badt2i_object" \
    $PYTHON ./attack/t2i_gen/badt2i/badt2i_object.py \
    --base_config attack/t2i_gen/configs/base_config.yaml \
    --bd_config attack/t2i_gen/configs/bd_config_objectRep.yaml \
    --model_ver sd15 --device cuda:0

run_step "badt2i_style" \
    $PYTHON ./attack/t2i_gen/badt2i/badt2i_style.py \
    --base_config attack/t2i_gen/configs/base_config.yaml \
    --bd_config attack/t2i_gen/configs/bd_config_styleAdd.yaml \
    --model_ver sd15 --device cuda:0

run_step "badt2i_objectAdd" \
    $PYTHON ./attack/t2i_gen/badt2i/badt2i_objectAdd.py \
    --base_config attack/t2i_gen/configs/base_config.yaml \
    --bd_config attack/t2i_gen/configs/bd_config_objectAdd.yaml \
    --model_ver sd15 --device cuda:0

log "=========================================="
log "BADT2I RETRAIN COMPLETE"
log "=========================================="
