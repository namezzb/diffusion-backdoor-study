#!/bin/bash
# Loop Health Check - Minimal version
set -uo pipefail

BD="/opt/data/private/BackdoorDM"
LOGDIR="$BD/logs/benchmark"

echo "=== HEALTH $(date '+%Y-%m-%d %H:%M:%S') ==="

# Process status
pgrep -f "run_benchmark.sh" > /dev/null && echo "benchmark: RUNNING" || echo "benchmark: STOPPED"
pgrep -f "eval_queue.sh" > /dev/null && echo "eval_queue: RUNNING" || echo "eval_queue: STOPPED"
pgrep -f "main_eval.py" > /dev/null && echo "eval_python: RUNNING" || echo "eval_python: IDLE"

# Result count
cat "$BD"/results/*/eval_results.csv 2>/dev/null | grep -v 'datatime' | wc -l | xargs echo "results:"

# Failed
grep -c "FAILED:" "$LOGDIR/benchmark.log" 2>/dev/null | xargs echo "failed:"

# Stuck detection
if pgrep -f "main_eval.py" > /dev/null 2>&1; then
    LATEST=$(ls -t "$BD"/logs/{benchmark,eval_queue}/*.log 2>/dev/null | head -1)
    if [ -n "$LATEST" ]; then
        AGE=$(( ($(date +%s) - $(stat -c %Y "$LATEST" 2>/dev/null || stat -f %m "$LATEST" 2>/dev/null || echo 0)) / 60 ))
        [ "$AGE" -gt 30 ] && echo "WARNING: log stale ${AGE}min" || echo "log_fresh: ${AGE}min"
    fi
fi

# Rogue process
N=$(pgrep -c -f "main_eval.py" 2>/dev/null || echo 0)
[ "$N" -gt 1 ] && echo "WARNING: $N eval processes! Rogue!" && pgrep -af "main_eval.py"

# Pipeline phase
if grep -q "BENCHMARK COMPLETE" "$LOGDIR/benchmark.log" 2>/dev/null; then
    echo "phase: COMPLETE"
elif grep -q "PHASE 3" "$LOGDIR/benchmark.log" 2>/dev/null; then
    echo "phase: DEFENSE"
elif grep -q "PHASE 2" "$LOGDIR/benchmark.log" 2>/dev/null; then
    echo "phase: EVAL"
elif grep -q "PHASE 1" "$LOGDIR/benchmark.log" 2>/dev/null; then
    echo "phase: TRAIN"
else
    echo "phase: WAITING"
fi

# Log tail
echo "--- tail ---"
tail -3 "$LOGDIR/benchmark.log" 2>/dev/null
echo "=== END ==="
