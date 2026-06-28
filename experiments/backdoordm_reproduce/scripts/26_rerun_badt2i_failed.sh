#!/bin/bash
# Re-run BadT2I pixel and object after fixing image issues
# Run this AFTER 25_fix_badt2i_images.sh and when GPU is available

set -euo pipefail
BD="/opt/data/private/BackdoorDM"
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
CHECKPOINT="$BD/logs/.checkpoint"
TIMING="$BD/logs/timing.csv"
LOG="$BD/logs/run_all.log"

cd "$BD"

run_step() {
    local STEP_NAME="$1"
    shift
    if grep -q "^${STEP_NAME}$" "$CHECKPOINT" 2>/dev/null; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') [SKIP] $STEP_NAME (already done)" | tee -a "$LOG"
        return 0
    fi
    echo "$(date '+%Y-%m-%d %H:%M:%S') [START] $STEP_NAME" | tee -a "$LOG"
    local START=$(date +%s)
    if eval "$@" >> "$LOG" 2>&1; then
        local END=$(date +%s)
        local DUR=$((END - START))
        local H=$((DUR / 3600))
        local M=$(( (DUR % 3600) / 60 ))
        local S=$((DUR % 60))
        echo "${STEP_NAME},OK,${H}h${M}m${S}s,$(date -d @$START '+%H:%M:%S' 2>/dev/null || date -r $START '+%H:%M:%S'),$(date -d @$END '+%H:%M:%S' 2>/dev/null || date -r $END '+%H:%M:%S')" >> "$TIMING"
        echo "$STEP_NAME" >> "$CHECKPOINT"
        echo "$(date '+%Y-%m-%d %H:%M:%S') [DONE] $STEP_NAME (${H}h${M}m${S}s)" | tee -a "$LOG"
    else
        local END=$(date +%s)
        local DUR=$((END - START))
        local H=$((DUR / 3600))
        local M=$(( (DUR % 3600) / 60 ))
        local S=$((DUR % 60))
        echo "${STEP_NAME},FAIL,${H}h${M}m${S}s,$(date -d @$START '+%H:%M:%S' 2>/dev/null || date -r $START '+%H:%M:%S'),$(date -d @$END '+%H:%M:%S' 2>/dev/null || date -r $END '+%H:%M:%S')" >> "$TIMING"
        echo "$(date '+%Y-%m-%d %H:%M:%S') FAILED: $STEP_NAME" >> "$BD/logs/failures.log"
        echo "$(date '+%Y-%m-%d %H:%M:%S') [FAIL] $STEP_NAME (${DUR}s)" | tee -a "$LOG"
    fi
}

# Verify fixes are applied
echo "=== Verifying fixes ==="
if ! grep -q "if img is None:" attack/t2i_gen/badt2i/badt2i_object.py; then
    echo "ERROR: badt2i_object.py not patched! Run 25_fix_badt2i_images.sh first"
    exit 1
fi

GEN_COUNT=$(ls datasets/laion_fallback/images/*.png 2>/dev/null | wc -l)
if [ "$GEN_COUNT" -lt 500 ]; then
    echo "ERROR: Only $GEN_COUNT generated images (need 500). Run 25_fix_badt2i_images.sh first"
    exit 1
fi

echo "✓ Object/ObjectAdd patched"
echo "✓ $GEN_COUNT generated images available"
echo ""

# Re-run failed attacks
echo "=== Re-running BadT2I pixel ==="
run_step attack_badt2i_pixel \
    "$PYTHON ./attack/t2i_gen/badt2i/badt2i_pixel.py \
        --base_config attack/t2i_gen/configs/base_config.yaml \
        --bd_config attack/t2i_gen/configs/bd_config_imagePatch.yaml \
        --model_ver sd15 --device cuda:0"

echo "=== Re-running BadT2I object ==="
run_step attack_badt2i_object \
    "$PYTHON ./attack/t2i_gen/badt2i/badt2i_object.py \
        --base_config attack/t2i_gen/configs/base_config.yaml \
        --bd_config attack/t2i_gen/configs/bd_config_objectRep.yaml \
        --model_ver sd15 --device cuda:0"

echo ""
echo "=== Re-run complete ==="
echo "Checkpoint: $(wc -l < "$CHECKPOINT") steps"
echo "Failures:"
cat "$BD/logs/failures.log" 2>/dev/null || echo "  (none)"
