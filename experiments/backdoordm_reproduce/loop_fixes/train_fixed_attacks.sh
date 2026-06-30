#!/bin/bash
# Train Fixed Attacks v2 - with checkpoint markers
set -uo pipefail

BD="/opt/data/private/BackdoorDM"
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
LOGDIR="$BD/logs/fixed_attacks"
MARKER_DIR="$BD/logs/fixed_attacks/done"
mkdir -p "$LOGDIR" "$MARKER_DIR"

cd "$BD"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOGDIR/train.log"; }

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
# 1. InviBackdoor (~3h)
# ============================================================
run_step "invi_backdoor" \
    $PYTHON ./attack/uncond_gen/invi_backdoor/invi_backdoor.py --gpu 0

# Check model
find "$BD/results/results/invi_backdoor_DDPM-CIFAR10-32/" -name '*.safetensors' -o -name '*.pt' 2>/dev/null | head -3

# ============================================================
# 2. BiBadDiff (~10h)
# ============================================================
# Ensure v1-5-pruned.ckpt symlink exists
CKPT_PATH="./results/bibaddiff_sd15/v1-5-pruned.ckpt"
LOCAL_SD_CKPT="/opt/data/private/models/stable-diffusion-v1-5/v1-5-pruned.ckpt"
mkdir -p ./results/bibaddiff_sd15
if [ ! -f "$CKPT_PATH" ]; then
    ln -sf "$LOCAL_SD_CKPT" "$CKPT_PATH"
    log "Symlinked v1-5-pruned.ckpt"
fi

if [ ! -f "$MARKER_DIR/done_bibaddiff" ]; then
    log "=== Running: bibaddiff training ==="
    cd ./attack/t2i_gen/bibaddiff
    if $PYTHON main.py -t \
        --base configs/stable-diffusion/backdoor/imagenette/badnet_pr0.1_pt6.yaml \
        --gpus 0, --scale_lr False --num_nodes 1 \
        --check_val_every_n_epoch 10 \
        --logdir ../../../results/bibaddiff_sd15 \
        --finetune_from ../../../results/bibaddiff_sd15/v1-5-pruned.ckpt \
        > "$LOGDIR/bibaddiff.log" 2>&1; then
        touch "$MARKER_DIR/done_bibaddiff"
        log "DONE: bibaddiff training"
    else
        log "FAILED: bibaddiff training (exit $?)"
    fi
    cd "$BD"

    # Convert checkpoint to diffusers format
    LAST_CKPT=$(find ./results/bibaddiff_sd15/ -name "last.ckpt" -path "*/checkpoints/*" | head -1)
    if [ -n "$LAST_CKPT" ]; then
        log "Converting BiBadDiff checkpoint to diffusers format..."
        if $PYTHON ./diffusers/scripts/convert_original_stable_diffusion_to_diffusers.py \
            --checkpoint_path "$LAST_CKPT" \
            --dump_path ./results/bibaddiff_sd15/bibaddiff_trigger-garbage_truck_target-badnets \
            > "$LOGDIR/bibaddiff_convert.log" 2>&1; then
            log "DONE: bibaddiff conversion"
        else
            log "FAILED: bibaddiff conversion"
        fi
    else
        log "WARNING: No last.ckpt found for BiBadDiff"
    fi
else
    log "SKIP: bibaddiff (already done)"
fi

# ============================================================
# 3. VillanDiffusion cond (~3h)
# ============================================================
run_step "villandiffusion_cond" \
    $PYTHON ./attack/uncond_gen/villandiffusion/villandiffusion.py \
    --conditional True --gpu 0

log "=========================================="
log "FIXED ATTACKS TRAINING COMPLETE"
log "=========================================="
