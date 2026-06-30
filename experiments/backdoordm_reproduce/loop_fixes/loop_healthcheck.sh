#!/bin/bash
# Loop Health Check - Centralized monitoring for /loop iterations
# Usage: bash scripts/loop_healthcheck.sh
# Outputs structured text that the loop agent can parse
set -uo pipefail

BD="/opt/data/private/BackdoorDM"
LOGDIR="$BD/logs"
EVAL_LOGDIR="$LOGDIR/eval_queue"
MASTER_LOGDIR="$LOGDIR/master_pipeline"
MARKER_DIR="$EVAL_LOGDIR/done"

echo "=== HEALTH CHECK $(date '+%Y-%m-%d %H:%M:%S') ==="

# 1. Process status (pattern-based, NOT hardcoded PIDs)
EVAL_PID=$(pgrep -f "eval_queue.sh" | head -1)
MASTER_PID=$(pgrep -f "master_pipeline.sh" | head -1)
EVAL_PYTHON_PID=$(pgrep -f "main_eval.py" | head -1)

if [ -n "$EVAL_PID" ]; then
    echo "eval_queue: RUNNING (PID $EVAL_PID)"
else
    echo "eval_queue: STOPPED"
fi

if [ -n "$MASTER_PID" ]; then
    echo "master_pipeline: RUNNING (PID $MASTER_PID)"
else
    echo "master_pipeline: STOPPED"
fi

if [ -n "$EVAL_PYTHON_PID" ]; then
    echo "eval_python: RUNNING (PID $EVAL_PYTHON_PID)"
else
    echo "eval_python: IDLE"
fi

# 2. Current eval progress
CURRENT_EVAL=$(grep "=== Eval" "$EVAL_LOGDIR/queue.log" 2>/dev/null | tail -1)
echo "current_eval: ${CURRENT_EVAL:-none}"

# 3. Eval result count
RESULT_COUNT=$(cat "$BD"/results/*/eval_results.csv 2>/dev/null | grep -v 'datatime' | wc -l)
echo "result_count: $RESULT_COUNT"

# 4. Failed evals
FAILED_COUNT=$(grep -c "FAILED:" "$EVAL_LOGDIR/queue.log" 2>/dev/null) || FAILED_COUNT=0
echo "failed_evals: $FAILED_COUNT"
if [ "$FAILED_COUNT" -gt 0 ]; then
    echo "failed_details:"
    grep "FAILED:" "$EVAL_LOGDIR/queue.log" 2>/dev/null
fi

# 5. Stuck detection: check if eval log is stale (>30min no update)
if [ -n "$EVAL_PYTHON_PID" ]; then
    # Find the most recently modified eval log
    LATEST_LOG=$(ls -t "$EVAL_LOGDIR"/*.log 2>/dev/null | head -1)
    if [ -n "$LATEST_LOG" ]; then
        LAST_MOD=$(stat -c %Y "$LATEST_LOG" 2>/dev/null || stat -f %m "$LATEST_LOG" 2>/dev/null || echo 0)
        NOW=$(date +%s)
        AGE_MIN=$(( (NOW - LAST_MOD) / 60 ))
        echo "latest_eval_log: $(basename $LATEST_LOG)"
        echo "log_age_min: $AGE_MIN"
        if [ "$AGE_MIN" -gt 30 ]; then
            echo "WARNING: eval log not updated in ${AGE_MIN}min, may be stuck!"
        else
            echo "log_freshness: OK (${AGE_MIN}min ago)"
        fi
    fi
fi

# 6. Pipeline phase
if grep -q "MASTER PIPELINE COMPLETE" "$MASTER_LOGDIR/pipeline.log" 2>/dev/null; then
    echo "pipeline_phase: COMPLETE"
elif grep -q "PHASE 5" "$MASTER_LOGDIR/pipeline.log" 2>/dev/null; then
    echo "pipeline_phase: P0_EXPERIMENTS"
elif grep -q "PHASE 4" "$MASTER_LOGDIR/pipeline.log" 2>/dev/null; then
    echo "pipeline_phase: DEFENSE"
elif grep -q "PHASE 3" "$MASTER_LOGDIR/pipeline.log" 2>/dev/null; then
    echo "pipeline_phase: FIXED_ATTACKS"
elif grep -q "PHASE 2" "$MASTER_LOGDIR/pipeline.log" 2>/dev/null; then
    echo "pipeline_phase: BADT2I_RETRAIN"
elif grep -q "Eval queue complete" "$MASTER_LOGDIR/pipeline.log" 2>/dev/null; then
    echo "pipeline_phase: POST_EVAL"
else
    echo "pipeline_phase: WAITING_FOR_EVAL"
fi

# 7. Completed markers
DONE_COUNT=$(ls "$MARKER_DIR"/done_* 2>/dev/null | wc -l)
echo "done_markers: $DONE_COUNT"
ls "$MARKER_DIR"/done_* 2>/dev/null | while read f; do echo "  marker: $(basename $f)"; done

# 8. GPU status
GPU_INFO=$(nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader 2>/dev/null)
echo "gpu: $GPU_INFO"

# 9. Rogue process detection: count main_eval.py processes
EVAL_PROC_COUNT=$(pgrep -c -f "main_eval.py" 2>/dev/null || echo 0)
echo "eval_proc_count: $EVAL_PROC_COUNT"
if [ "$EVAL_PROC_COUNT" -gt 1 ]; then
    echo "WARNING: $EVAL_PROC_COUNT main_eval.py processes running! Rogue process likely!"
    pgrep -af "main_eval.py" 2>/dev/null
fi

# 10. Conflicting pipeline detection
CONFLICT_SCRIPTS=$(pgrep -af "run_all_resilient\|run_all\.sh" 2>/dev/null | grep -v pgrep)
if [ -n "$CONFLICT_SCRIPTS" ]; then
    echo "WARNING: Old/conflicting pipeline detected!"
    echo "$CONFLICT_SCRIPTS"
fi

# 11. Missing metrics detection: check which T2I methods lack CLIP_p/FID/LPIPS
echo "--- metrics coverage ---"
for method in eviledit eviledit_numAdd rickrolling_TPA rickrolling_TAA paas_ti paas_db; do
    CSV="$BD/results/${method}_sd15/eval_results.csv"
    if [ -f "$CSV" ]; then
        METRICS=$(grep -v 'datatime' "$CSV" 2>/dev/null | awk -F'\t' '{print $2}' | sort -u | tr '\n' ',' | sed 's/,$//')
        METRIC_COUNT=$(echo "$METRICS" | tr ',' '\n' | wc -l)
        if echo "$METRICS" | grep -qv "CLIP_p"; then
            echo "  $method: missing CLIP_p/FID/LPIPS (has: $METRICS)"
        elif echo "$METRICS" | grep -qv "FID"; then
            echo "  $method: missing FID/LPIPS (has: $METRICS)"
        else
            echo "  $method: complete ($METRICS)"
        fi
    fi
done

# 12. Extra metrics queue status
EXTRA_LOG="$BD/logs/eval_extra/extra_queue.log"
if [ -f "$EXTRA_LOG" ]; then
    EXTRA_DONE=$(ls "$BD/logs/eval_extra/done"/done_* 2>/dev/null | wc -l)
    EXTRA_FAILED=$(grep -c "FAILED:" "$EXTRA_LOG" 2>/dev/null) || EXTRA_FAILED=0
    echo "extra_metrics: $EXTRA_DONE done, $EXTRA_FAILED failed"
    if grep -q "EXTRA METRICS QUEUE COMPLETE" "$EXTRA_LOG" 2>/dev/null; then
        echo "extra_metrics_status: COMPLETE"
    else
        echo "extra_metrics_status: IN_PROGRESS or NOT_STARTED"
    fi
else
    echo "extra_metrics: NOT_STARTED"
fi

# 13. Paper reference available
if [ -f "$BD/scripts/paper_reference.json" ]; then
    echo "paper_reference: AVAILABLE"
else
    echo "paper_reference: MISSING"
fi

# Queue log tail
echo "--- queue.log tail ---"
tail -3 "$EVAL_LOGDIR/queue.log" 2>/dev/null

# 10. Pipeline log tail
echo "--- pipeline.log tail ---"
tail -3 "$MASTER_LOGDIR/pipeline.log" 2>/dev/null

echo "=== END HEALTH CHECK ==="
