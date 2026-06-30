#!/bin/bash
# Master Pipeline v2 - Runs all remaining reproduction phases sequentially
# FIX: deadlock detection in wait loop, phase checkpoint markers
# Phase 1: eval_queue.sh (already running, this script waits for it)
# Phase 2: badt2i_retrain.sh
# Phase 3: train_fixed_attacks.sh
# Phase 4: defense_queue.sh
# Phase 5: P0 missing experiments (poison rate ablation, lambda ablation)
set -uo pipefail

BD="/opt/data/private/BackdoorDM"
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
LOGDIR="$BD/logs/master_pipeline"
MARKER_DIR="$BD/logs/done_phases"
mkdir -p "$LOGDIR" "$MARKER_DIR"

cd "$BD"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOGDIR/pipeline.log"; }

log "=========================================="
log "MASTER PIPELINE STARTED (v2 with deadlock detection)"
log "=========================================="

# ============================================================
# Phase 1: Wait for eval_queue to finish (with deadlock detection)
# ============================================================
if [ ! -f "$MARKER_DIR/phase1_eval_done" ]; then
    log "PHASE 1: Waiting for eval_queue to finish..."
    DEADLOCK_COUNT=0
    while ! grep -q "EVALUATION QUEUE COMPLETE" "$BD/logs/eval_queue/queue.log" 2>/dev/null; do
        sleep 300
        # Deadlock detection: if eval_queue is not running but didn't complete
        if ! pgrep -f "eval_queue.sh" > /dev/null 2>&1 && ! pgrep -f "main_eval.py" > /dev/null 2>&1; then
            DEADLOCK_COUNT=$((DEADLOCK_COUNT + 1))
            log "WARNING: eval_queue not running, COMPLETE marker missing (check $DEADLOCK_COUNT)"
            if [ "$DEADLOCK_COUNT" -ge 2 ]; then
                log "ERROR: eval_queue.sh died without completing! Checking for failures..."
                FAILED=$(grep -c "FAILED:" "$BD/logs/eval_queue/queue.log" 2>/dev/null || echo 0)
                log "Failed evals: $FAILED"
                log "Proceeding to next phase (failed evals will need manual retry)"
                break
            fi
        else
            DEADLOCK_COUNT=0
        fi
    done
    touch "$MARKER_DIR/phase1_eval_done"
    log "Phase 1 complete!"
else
    log "SKIP: Phase 1 (already done)"
fi

# ============================================================
# Phase 1.5: Extra Metrics (CLIP_p, CLIP_c, FID, LPIPS for T2I)
# ============================================================
if [ ! -f "$MARKER_DIR/phase1_5_extra_metrics_done" ]; then
    log "=========================================="
    log "PHASE 1.5: Extra Evaluation Metrics"
    log "Running CLIP_p, CLIP_c, FID, LPIPS for all trained T2I methods"
    log "=========================================="
    bash scripts/eval_extra_metrics.sh 2>&1 | tee -a "$LOGDIR/phase1_5_extra_metrics.log"
    touch "$MARKER_DIR/phase1_5_extra_metrics_done"
    log "Phase 1.5 complete!"
else
    log "SKIP: Phase 1.5 (already done)"
fi

# ============================================================
# Phase 2: BadT2I Data Generation + Retraining (~41h)
# ============================================================
if [ ! -f "$MARKER_DIR/phase2_badt2i_done" ]; then
    log "=========================================="
    log "PHASE 2: BadT2I Retraining"
    log "=========================================="
    bash scripts/badt2i_retrain.sh 2>&1 | tee -a "$LOGDIR/phase2_badt2i.log"
    if [ "${PIPESTATUS[0]}" -ne 0 ]; then
        log "WARNING: BadT2I retraining had errors, continuing..."
    fi

    # Evaluate retrained BadT2I models
    log "Evaluating retrained BadT2I models..."
    for variant in pixel object style objectAdd; do
        log "Eval badt2i_${variant}..."
        if $PYTHON evaluation/main_eval.py --metric ACCASR \
            --backdoor_method "badt2i_${variant}" --device cuda:0 \
            > "$LOGDIR/eval_badt2i_${variant}.log" 2>&1; then
            log "DONE: badt2i_${variant} eval"
        else
            log "FAILED: badt2i_${variant} eval"
        fi
    done
    touch "$MARKER_DIR/phase2_badt2i_done"
    log "Phase 2 complete!"

    # Run extra metrics for newly trained BadT2I models
    log "Running extra metrics for BadT2I models..."
    bash scripts/eval_extra_metrics.sh 2>&1 | tee -a "$LOGDIR/phase2_extra_metrics.log"
else
    log "SKIP: Phase 2 (already done)"
fi

# ============================================================
# Phase 3: Fixed Attacks Training (~53h)
# ============================================================
if [ ! -f "$MARKER_DIR/phase3_fixed_attacks_done" ]; then
    log "=========================================="
    log "PHASE 3: Fixed Attacks Training"
    log "=========================================="
    bash scripts/train_fixed_attacks.sh 2>&1 | tee -a "$LOGDIR/phase3_fixed_attacks.log"
    if [ "${PIPESTATUS[0]}" -ne 0 ]; then
        log "WARNING: Fixed attacks training had errors, continuing..."
    fi

    # Evaluate fixed attacks
    log "Evaluating fixed attacks..."
    if $PYTHON evaluation/main_eval.py --metric ACCASR --backdoor_method bibaddiff --device cuda:0 \
        > "$LOGDIR/eval_bibaddiff.log" 2>&1; then
        log "DONE: bibaddiff eval"
    else
        log "FAILED: bibaddiff eval"
    fi

    for metric in FID MSE; do
        if $PYTHON evaluation/main_eval.py --metric $metric --backdoor_method invi_backdoor \
            --backdoored_model_path ./results/results/invi_backdoor_DDPM-CIFAR10-32 \
            --val_data cifar10 --device cuda:0 \
            > "$LOGDIR/eval_invi_backdoor_${metric}.log" 2>&1; then
            log "DONE: invi_backdoor ${metric} eval"
        else
            log "FAILED: invi_backdoor ${metric} eval"
        fi
    done
    touch "$MARKER_DIR/phase3_fixed_attacks_done"
    log "Phase 3 complete!"

    # Run extra metrics for newly trained fixed attack models
    log "Running extra metrics for fixed attack models..."
    bash scripts/eval_extra_metrics.sh 2>&1 | tee -a "$LOGDIR/phase3_extra_metrics.log"
else
    log "SKIP: Phase 3 (already done)"
fi

# ============================================================
# Phase 4: Defense Queue (~47h)
# ============================================================
if [ ! -f "$MARKER_DIR/phase4_defense_done" ]; then
    log "=========================================="
    log "PHASE 4: Defense Queue"
    log "=========================================="
    bash scripts/defense_queue.sh 2>&1 | tee -a "$LOGDIR/phase4_defense.log"
    if [ "${PIPESTATUS[0]}" -ne 0 ]; then
        log "WARNING: Defense queue had errors, continuing..."
    fi
    touch "$MARKER_DIR/phase4_defense_done"
    log "Phase 4 complete!"
else
    log "SKIP: Phase 4 (already done)"
fi

# ============================================================
# Phase 5: P0 Missing Experiments
# ============================================================
if [ ! -f "$MARKER_DIR/phase5_p0_done" ]; then
    log "=========================================="
    log "PHASE 5: P0 Missing Experiments"
    log "=========================================="

    # EvilEdit Whitelist + VTA (P0, was missing from pipeline)
    log "EvilEdit Whitelist + VTA..."
    WHITELIST_SCRIPT=""
    for candidate in scripts/eviledit_whitelist_vta.py scripts/eviledit_whitelist.py attack/t2i_gen/eviledit/whitelist_vta.py; do
        if [ -f "$BD/$candidate" ]; then
            WHITELIST_SCRIPT="$candidate"
            break
        fi
    done
    if [ -n "$WHITELIST_SCRIPT" ]; then
        if $PYTHON "$WHITELIST_SCRIPT" > "$LOGDIR/eviledit_whitelist_vta.log" 2>&1; then
            log "DONE: EvilEdit Whitelist+VTA"
        else
            log "FAILED: EvilEdit Whitelist+VTA (exit $?)"
        fi
    else
        log "SKIP: EvilEdit Whitelist+VTA (script not found, need to implement)"
    fi

    # EvilEdit Lambda Ablation
    log "EvilEdit Lambda Ablation..."
    if $PYTHON scripts/eviledit_lambda_ablation.py > "$LOGDIR/eviledit_lambda.log" 2>&1; then
        log "DONE: EvilEdit lambda ablation training"
    else
        log "FAILED: EvilEdit lambda ablation training"
    fi
    # Evaluate each lambda model
    for lamb in 0.1 0.5 1 2 5; do
        log "Eval EvilEdit lambda=$lamb..."
        if $PYTHON evaluation/main_eval.py --metric ACCASR --backdoor_method eviledit \
            --backdoored_model_path "./results/eviledit_sd15/eviledit_trigger-beautifuldog_target-cat_lambda${lamb}.pt" \
            --device cuda:0 \
            > "$LOGDIR/eval_eviledit_lambda${lamb}.log" 2>&1; then
            log "DONE: eviledit lambda=$lamb eval"
        else
            log "FAILED: eviledit lambda=$lamb eval"
        fi
    done

    # BadDiffusion Poison Rate Ablation
    log "BadDiffusion Poison Rate Ablation..."
    if bash scripts/baddiffusion_poison_rate_ablation.sh > "$LOGDIR/baddiffusion_poison_rate.log" 2>&1; then
        log "DONE: BadDiffusion poison rate ablation"
    else
        log "FAILED: BadDiffusion poison rate ablation"
    fi
    touch "$MARKER_DIR/phase5_p0_done"
    log "Phase 5 complete!"
else
    log "SKIP: Phase 5 (already done)"
fi

# ============================================================
# Final Summary
# ============================================================
log "=========================================="
log "MASTER PIPELINE COMPLETE"
log "=========================================="
log "Collecting all results..."
bash scripts/extract_all_metrics.sh 2>/dev/null || true

# Report all failures across pipeline
log "=== Failure Summary ==="
grep -h "FAILED:" "$LOGDIR"/phase*.log "$BD/logs/eval_queue/queue.log" 2>/dev/null || log "No failures recorded"

log "All done. Check logs/ for detailed results."
log "Next step: Generate final reproduction report."
