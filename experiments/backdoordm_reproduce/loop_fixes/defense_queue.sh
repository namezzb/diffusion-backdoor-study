#!/bin/bash
# Defense Queue Script v2 - with checkpoint markers + model existence check
# FIX: skip defenses on untrained attack models to avoid silent failures
set -uo pipefail

BD="/opt/data/private/BackdoorDM"
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
LOGDIR="$BD/logs/defense_queue"
MARKER_DIR="$BD/logs/defense_queue/done"
mkdir -p "$LOGDIR" "$MARKER_DIR"

cd "$BD"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOGDIR/defense_queue.log"; }

# Check if a T2I attack model exists
t2i_model_exists() {
    local method="$1"
    for dir in "$BD/results/${method}_sd15" "$BD/results/${method}"; do
        if [ -d "$dir" ]; then
            if find "$dir" -name '*.pt' -o -name '*.safetensors' -o -name '*.bin' 2>/dev/null | grep -q .; then
                return 0
            fi
        fi
    done
    return 1
}

# Check if an unconditional attack model exists
uncond_model_exists() {
    local method="$1"
    local dir="$BD/results/${method}_DDPM-CIFAR10-32"
    if [ -d "$dir" ]; then
        if find "$dir" -name '*.pt' -o -name '*.safetensors' -o -name '*.bin' 2>/dev/null | grep -q .; then
            return 0
        fi
    fi
    return 1
}

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
log "DEFENSE QUEUE STARTED (v2 with model checks)"
log "=========================================="

# ============================================================
# 1. T2IShield - T2I attacks (skip untrained models)
# ============================================================
for method in eviledit rickrolling_TPA paas_ti paas_db rickrolling_TAA; do
    if ! t2i_model_exists "$method"; then
        log "SKIP: t2ishield_${method} (attack model not trained)"
        continue
    fi
    run_step "t2ishield_${method}" \
        $PYTHON defense/model_level/t2ishield/t2ishield.py \
        --backdoor_method "$method" --device cuda:0
done

# BadT2I methods - check existence
for method in badt2i_pixel badt2i_object badt2i_style badt2i_objectAdd; do
    if ! t2i_model_exists "$method"; then
        log "SKIP: t2ishield_${method} (attack model not trained)"
        continue
    fi
    run_step "t2ishield_${method}" \
        $PYTHON defense/model_level/t2ishield/t2ishield.py \
        --backdoor_method "$method" --device cuda:0
done

# VillanDiff cond
if t2i_model_exists "villandiffusion_cond"; then
    run_step "t2ishield_villandiffusion_cond" \
        $PYTHON defense/model_level/t2ishield/t2ishield.py \
        --backdoor_method villandiffusion_cond --device cuda:0
else
    log "SKIP: t2ishield_villandiffusion_cond (attack model not trained)"
fi

# BiBadDiff
if t2i_model_exists "bibaddiff"; then
    run_step "t2ishield_bibaddiff" \
        $PYTHON defense/model_level/t2ishield/t2ishield.py \
        --backdoor_method bibaddiff --device cuda:0
else
    log "SKIP: t2ishield_bibaddiff (attack model not trained)"
fi

# ============================================================
# 2. Elijah - Unconditional attacks (skip untrained models)
# ============================================================
for method in baddiffusion trojdiff villandiffusion; do
    if ! uncond_model_exists "$method"; then
        log "SKIP: elijah_${method} (attack model not trained)"
        continue
    fi
    MODEL_PATH="./results/${method}_DDPM-CIFAR10-32"
    run_step "elijah_${method}" \
        $PYTHON defense/model_level/Elijah/elijah.py \
        --backdoor_method "$method" \
        --backdoored_model_path "$MODEL_PATH" \
        --device cuda:0
done

# InviBackdoor
if uncond_model_exists "invi_backdoor"; then
    run_step "elijah_invi_backdoor" \
        $PYTHON defense/model_level/Elijah/elijah.py \
        --backdoor_method invi_backdoor \
        --backdoored_model_path ./results/results/invi_backdoor_DDPM-CIFAR10-32 \
        --device cuda:0
else
    log "SKIP: elijah_invi_backdoor (attack model not trained)"
fi

# ============================================================
# 3. TERD Input - Unconditional attacks
# ============================================================
for method in baddiffusion trojdiff villandiffusion; do
    if ! uncond_model_exists "$method"; then
        log "SKIP: terd_input_${method} (attack model not trained)"
        continue
    fi
    run_step "terd_input_${method}" \
        $PYTHON defense/input_level/Terd_input/terd_input.py \
        --backdoor_method "$method" --device cuda:0
done

# ============================================================
# 4. TERD Model - Unconditional attacks
# ============================================================
for method in baddiffusion trojdiff villandiffusion; do
    if ! uncond_model_exists "$method"; then
        log "SKIP: terd_model_${method} (attack model not trained)"
        continue
    fi
    run_step "terd_model_${method}" \
        $PYTHON defense/model_level/Terd_model/terd_model.py \
        --backdoor_method "$method" --device cuda:0
done

# ============================================================
# 5. Textual Perturbation - T2I attacks
# ============================================================
for method in eviledit rickrolling_TPA paas_ti paas_db rickrolling_TAA; do
    if ! t2i_model_exists "$method"; then
        log "SKIP: textual_perturbation_${method} (attack model not trained)"
        continue
    fi
    run_step "textual_perturbation_${method}" \
        $PYTHON defense/input_level/textual_perturbation.py \
        --backdoor_method "$method" --device cuda:0
done

# ============================================================
# 6. DAA - T2I attacks
# ============================================================
for method in eviledit rickrolling_TPA paas_ti; do
    if ! t2i_model_exists "$method"; then
        log "SKIP: daa_${method} (attack model not trained)"
        continue
    fi
    run_step "daa_${method}" \
        $PYTHON defense/model_level/daa/daa.py \
        --backdoor_method "$method" --device cuda:0
done

log "=========================================="
log "DEFENSE QUEUE COMPLETE"
log "=========================================="

# Report skipped and failed
SKIPPED=$(grep -c "SKIP:" "$LOGDIR/defense_queue.log" 2>/dev/null) || SKIPPED=0
FAILED=$(grep -c "FAILED:" "$LOGDIR/defense_queue.log" 2>/dev/null) || FAILED=0
log "Summary: $SKIPPED skipped, $FAILED failed"

if [ "$FAILED" -gt 0 ]; then
    log "Failed details:"
    grep "FAILED:" "$LOGDIR/defense_queue.log"
fi
if [ "$SKIPPED" -gt 0 ]; then
    log "Skipped details:"
    grep "SKIP:" "$LOGDIR/defense_queue.log"
fi

log "All defense methods done. Check $LOGDIR/ for detailed logs."
