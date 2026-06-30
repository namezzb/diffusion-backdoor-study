#!/bin/bash
# BackdoorDM Benchmark - Minimal reproduction using official scripts
# Phase 1: Train remaining attacks (skip if model exists)
# Phase 2: Run all official eval scripts (skip if result exists)
# Phase 3: Run all official defense scripts
set -uo pipefail

BD="/opt/data/private/BackdoorDM"
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
export HF_DATASETS_OFFLINE=1
export HF_HUB_OFFLINE=1
LOGDIR="$BD/logs/benchmark"
MARKER_DIR="$LOGDIR/done"
mkdir -p "$LOGDIR" "$MARKER_DIR"

cd "$BD"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOGDIR/benchmark.log"; }

# Check if model exists for a method
model_exists() {
    local method="$1"
    for dir in "$BD/results/${method}_sd15" "$BD/results/${method}_DDPM-CIFAR10-32" "$BD/results/results/${method}_DDPM-CIFAR10-32"; do
        if [ -d "$dir" ] && find "$dir" \( -name '*.pt' -o -name '*.safetensors' -o -name '*.bin' \) 2>/dev/null | grep -q .; then
            return 0
        fi
    done
    return 1
}

# Check if eval result already exists in CSV
has_result() {
    local method="$1" metric="$2"
    for csv in "$BD/results/${method}_sd15/eval_results.csv" "$BD/results/${method}_DDPM-CIFAR10-32/eval_results.csv" "$BD/results/results/${method}_DDPM-CIFAR10-32/eval_results.csv"; do
        [ -f "$csv" ] && grep -q "$metric" "$csv" 2>/dev/null && return 0
    done
    return 1
}

# Run a command with logging, continue on failure
run() {
    local name="$1"; shift
    if [ -f "$MARKER_DIR/done_$name" ]; then
        log "SKIP: $name (marker exists)"
        return 0
    fi
    log "START: $name"
    if "$@" > "$LOGDIR/${name}.log" 2>&1; then
        touch "$MARKER_DIR/done_$name"
        log "DONE: $name"
    else
        log "FAILED: $name (exit $?)"
    fi
}

# Run eval with result-skip check
run_eval() {
    local method="$1" metric="$2"; shift 2
    if has_result "$method" "$metric"; then
        log "SKIP eval: $method $metric (result exists)"
        return 0
    fi
    log "EVAL: $method $metric"
    $PYTHON evaluation/main_eval.py --metric "$metric" --backdoor_method "$method" "$@" --device cuda:0 \
        > "$LOGDIR/eval_${method}_${metric}.log" 2>&1 \
        && log "DONE: $method $metric" \
        || log "FAILED: $method $metric"
}

log "=========================================="
log "BACKDOORDM BENCHMARK STARTED"
log "=========================================="

# Wait for existing eval_queue to finish (if running)
if pgrep -f "eval_queue.sh" > /dev/null 2>&1; then
    log "Waiting for existing eval_queue to finish..."
    while pgrep -f "eval_queue.sh" > /dev/null 2>&1; do
        sleep 300
    done
    log "eval_queue finished."
fi

# ============================================================
# Phase 1: Train remaining attacks
# ============================================================
if [ ! -f "$MARKER_DIR/phase1_train" ]; then
    log "===== PHASE 1: Train remaining attacks ====="

    # BadT2I Pixel (ImagePatch)
    if ! model_exists badt2i_pixel; then
        run badt2i_pixel $PYTHON ./attack/t2i_gen/badt2i/badt2i_pixel.py \
            --base_config attack/t2i_gen/configs/base_config.yaml \
            --bd_config attack/t2i_gen/configs/bd_config_imagePatch.yaml \
            --model_ver sd15 --device cuda:0
    fi

    # BadT2I Object (ObjectRep)
    if ! model_exists badt2i_object; then
        run badt2i_object $PYTHON ./attack/t2i_gen/badt2i/badt2i_object.py \
            --base_config attack/t2i_gen/configs/base_config.yaml \
            --bd_config attack/t2i_gen/configs/bd_config_objectRep.yaml \
            --model_ver sd15 --device cuda:0
    fi

    # BadT2I Style (StyleAdd)
    if ! model_exists badt2i_style; then
        run badt2i_style $PYTHON ./attack/t2i_gen/badt2i/badt2i_style.py \
            --base_config attack/t2i_gen/configs/base_config.yaml \
            --bd_config attack/t2i_gen/configs/bd_config_styleAdd.yaml \
            --model_ver sd15 --device cuda:0
    fi

    # BadT2I ObjectAdd (BackdoorDM variant)
    if ! model_exists badt2i_objectAdd; then
        run badt2i_objectAdd $PYTHON ./attack/t2i_gen/badt2i/badt2i_objectAdd.py \
            --base_config attack/t2i_gen/configs/base_config.yaml \
            --bd_config attack/t2i_gen/configs/bd_config_objectAdd.yaml \
            --model_ver sd15 --device cuda:0
    fi

    # InviBackdoor
    if ! model_exists invi_backdoor; then
        run invi_backdoor $PYTHON ./attack/uncond_gen/invi_backdoor/invi_backdoor.py --gpu 0
    fi

    # VillanDiffusion cond
    if ! model_exists villandiffusion_cond; then
        run villandiffusion_cond $PYTHON ./attack/t2i_gen/villan_diffusion_cond/villan_cond.py \
            --bd_config attack/t2i_gen/configs/bd_config_fix.yaml --gpu 0
    fi

    # BiBadDiff (complex: data + train + convert)
    if ! model_exists bibaddiff; then
        log "START: bibaddiff (data prep + training + conversion)"
        # Data prep
        cd ./attack/t2i_gen/bibaddiff/data/imagenette
        if [ ! -f imagenette2.tgz ]; then
            wget -q https://s3.amazonaws.com/fast-ai-imageclas/imagenette2.tgz 2>/dev/null || log "WARNING: imagenette download failed"
        fi
        [ -d imagenette2 ] || tar -zxvf imagenette2.tgz 2>/dev/null
        $PYTHON badnets_imagenette.py 2>/dev/null || log "WARNING: badnets prep failed"
        cd "$BD/attack/t2i_gen/bibaddiff"

        # Ensure ckpt symlink
        mkdir -p "$BD/results/bibaddiff_sd15"
        [ -f "$BD/results/bibaddiff_sd15/v1-5-pruned.ckpt" ] || ln -sf /opt/data/private/models/stable-diffusion-v1-5/v1-5-pruned.ckpt "$BD/results/bibaddiff_sd15/v1-5-pruned.ckpt"

        # Train
        $PYTHON main.py -t \
            --base configs/stable-diffusion/backdoor/imagenette/badnet_pr0.1_pt6.yaml \
            --gpus 0, --scale_lr False --num_nodes 1 \
            --check_val_every_n_epoch 10 \
            --logdir "$BD/results/bibaddiff_sd15" \
            --finetune_from "$BD/results/bibaddiff_sd15/v1-5-pruned.ckpt" \
            > "$LOGDIR/bibaddiff.log" 2>&1 && log "DONE: bibaddiff training" || log "FAILED: bibaddiff training"

        # Convert ckpt to diffusers
        cd "$BD"
        LAST_CKPT=$(find ./results/bibaddiff_sd15/ -name "last.ckpt" -path "*/checkpoints/*" 2>/dev/null | head -1)
        if [ -n "$LAST_CKPT" ]; then
            $PYTHON ./diffusers/scripts/convert_original_stable_diffusion_to_diffusers.py \
                --checkpoint_path "$LAST_CKPT" \
                --dump_path ./results/bibaddiff_sd15/bibaddiff_trigger-garbage_truck_target-badnets \
                > "$LOGDIR/bibaddiff_convert.log" 2>&1 && log "DONE: bibaddiff conversion" || log "FAILED: bibaddiff conversion"
        else
            log "WARNING: No last.ckpt found for BiBadDiff"
        fi
    fi

    touch "$MARKER_DIR/phase1_train"
    log "===== PHASE 1 COMPLETE ====="
else
    log "SKIP: Phase 1 (already done)"
fi

# ============================================================
# Phase 2: Run all official eval scripts
# ============================================================
if [ ! -f "$MARKER_DIR/phase2_eval" ]; then
    log "===== PHASE 2: Run all evaluations ====="

    # T2I methods: ACCASR, CLIP_p, CLIP_c, FID, LPIPS
    T2I_METHODS="eviledit eviledit_numAdd rickrolling_TPA rickrolling_TAA paas_ti paas_db badt2i_pixel badt2i_object badt2i_style badt2i_objectAdd bibaddiff villandiffusion_cond"
    for method in $T2I_METHODS; do
        if ! model_exists "$method"; then
            log "SKIP $method: not trained"
            continue
        fi
        run_eval "$method" ACCASR
        run_eval "$method" CLIP_p
        run_eval "$method" CLIP_c
        run_eval "$method" FID
        run_eval "$method" LPIPS
    done

    # Unconditional methods: FID, MSE
    for method in baddiffusion trojdiff villandiffusion invi_backdoor; do
        if ! model_exists "$method"; then
            log "SKIP $method: not trained"
            continue
        fi
        if [ "$method" = "invi_backdoor" ]; then
            MP="./results/results/invi_backdoor_DDPM-CIFAR10-32"
        else
            MP="./results/${method}_DDPM-CIFAR10-32"
        fi
        run_eval "$method" FID --backdoored_model_path "$MP" --val_data cifar10
        run_eval "$method" MSE --backdoored_model_path "$MP" --val_data cifar10
    done

    touch "$MARKER_DIR/phase2_eval"
    log "===== PHASE 2 COMPLETE ====="
else
    log "SKIP: Phase 2 (already done)"
fi

# ============================================================
# Phase 3: Run all defense scripts
# ============================================================
if [ ! -f "$MARKER_DIR/phase3_defense" ]; then
    log "===== PHASE 3: Run all defenses ====="

    # T2IShield (official script covers all T2I attacks)
    run t2ishield bash scripts/run_defend_t2ishield.sh

    # Elijah (official script covers all unconditional attacks)
    run elijah bash scripts/run_defend_elijah.sh

    # TERD input - for each unconditional attack
    for method in baddiffusion trojdiff villandiffusion; do
        model_exists "$method" || continue
        run "terd_input_${method}" $PYTHON defense/input_level/Terd_input/terd_input.py \
            --backdoor_method "$method" --device cuda:0
    done

    # TERD model
    for method in baddiffusion trojdiff villandiffusion; do
        model_exists "$method" || continue
        run "terd_model_${method}" $PYTHON defense/model_level/Terd_model/terd_model.py \
            --backdoor_method "$method" --device cuda:0
    done

    # Textual Perturbation
    for method in eviledit rickrolling_TPA paas_ti paas_db rickrolling_TAA; do
        model_exists "$method" || continue
        run "textpert_${method}" $PYTHON defense/input_level/textual_perturbation.py \
            --backdoor_method "$method" --device cuda:0
    done

    # DAA
    for method in eviledit rickrolling_TPA paas_ti; do
        model_exists "$method" || continue
        run "daa_${method}" $PYTHON defense/input_level/daa/daa.py \
            --backdoor_method "$method" --device cuda:0
    done

    touch "$MARKER_DIR/phase3_defense"
    log "===== PHASE 3 COMPLETE ====="
else
    log "SKIP: Phase 3 (already done)"
fi

# ============================================================
# Done
# ============================================================
log "=========================================="
log "BENCHMARK COMPLETE"
log "=========================================="
log "Results:"
for f in $BD/results/*/eval_results.csv; do
    log "--- $(basename $(dirname $f)) ---"
    cat "$f" 2>/dev/null
done
log "Check $LOGDIR/ for detailed logs."
