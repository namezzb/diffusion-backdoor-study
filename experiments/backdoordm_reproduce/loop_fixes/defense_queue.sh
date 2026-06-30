#!/bin/bash
# Defense Queue Script v2 - with checkpoint markers
set -uo pipefail

BD="/opt/data/private/BackdoorDM"
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
LOGDIR="$BD/logs/defense_queue"
MARKER_DIR="$BD/logs/defense_queue/done"
mkdir -p "$LOGDIR" "$MARKER_DIR"

cd "$BD"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOGDIR/defense_queue.log"; }

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

log "=========================================="
log "DEFENSE QUEUE STARTED (v2 with checkpoints)"
log "=========================================="

# ============================================================
# 1. T2IShield - T2I attacks
# ============================================================
for method in eviledit rickrolling_TPA paas_ti paas_db rickrolling_TAA; do
    run_step "t2ishield_${method}" \
        $PYTHON defense/model_level/t2ishield/t2ishield.py \
        --backdoor_method "$method" --device cuda:0
done

# ============================================================
# 2. Elijah - Unconditional attacks
# ============================================================
for method in baddiffusion trojdiff villandiffusion; do
    MODEL_PATH="./results/${method}_DDPM-CIFAR10-32"
    run_step "elijah_${method}" \
        $PYTHON defense/model_level/Elijah/elijah.py \
        --backdoor_method "$method" \
        --backdoored_model_path "$MODEL_PATH" \
        --device cuda:0
done

# ============================================================
# 3. TERD Input - Unconditional attacks
# ============================================================
for method in baddiffusion trojdiff villandiffusion; do
    run_step "terd_input_${method}" \
        $PYTHON defense/input_level/Terd_input/terd_input.py \
        --backdoor_method "$method" --device cuda:0
done

# ============================================================
# 4. TERD Model - Unconditional attacks
# ============================================================
for method in baddiffusion trojdiff villandiffusion; do
    run_step "terd_model_${method}" \
        $PYTHON defense/model_level/Terd_model/terd_model.py \
        --backdoor_method "$method" --device cuda:0
done

# ============================================================
# 5. Textual Perturbation - T2I attacks
# ============================================================
for method in eviledit rickrolling_TPA paas_ti paas_db; do
    run_step "textual_perturbation_${method}" \
        $PYTHON defense/input_level/textual_perturbation.py \
        --backdoor_method "$method" --device cuda:0
done

# ============================================================
# 6. DAA - T2I attacks
# ============================================================
for method in eviledit rickrolling_TPA paas_ti; do
    run_step "daa_${method}" \
        $PYTHON defense/model_level/daa/daa.py \
        --backdoor_method "$method" --device cuda:0
done

log "=========================================="
log "DEFENSE QUEUE COMPLETE"
log "=========================================="

FAILED=$(grep -c "FAILED:" "$LOGDIR/defense_queue.log" 2>/dev/null || echo 0)
if [ "$FAILED" -gt 0 ]; then
    log "WARNING: $FAILED defense(s) failed."
    grep "FAILED:" "$LOGDIR/defense_queue.log"
fi

log "All defense methods done. Check $LOGDIR/ for detailed logs."
