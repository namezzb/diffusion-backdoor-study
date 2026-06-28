#!/bin/bash
# SSH 恢复后立即运行的快速状态检查
# 用法: ssh amax -p 25579 "bash -s" < scripts/20_quick_status_check.sh

cd /opt/data/private/BackdoorDM

echo "=== CHECKPOINT (completed steps) ==="
if [ -f logs/.checkpoint ]; then
    wc -l < logs/.checkpoint
    cat logs/.checkpoint
else
    echo "(no checkpoint file)"
fi

echo ""
echo "=== FAILURES ==="
if [ -f logs/failures.log ] && [ -s logs/failures.log ]; then
    cat logs/failures.log
else
    echo "(no failures)"
fi

echo ""
echo "=== TIMING (last 20) ==="
if [ -f logs/timing.csv ]; then
    tail -20 logs/timing.csv
else
    echo "(no timing data)"
fi

echo ""
echo "=== CURRENT PROCESS ==="
ps aux | grep -E "python|run_all" | grep -v grep | head -10

echo ""
echo "=== GPU STATUS ==="
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader 2>/dev/null

echo ""
echo "=== LAST 30 LOG LINES ==="
tail -30 logs/run_all.log 2>/dev/null

echo ""
echo "=== KEY CONFIG VALUES ==="
echo "--- uncond bd_config_fix.yaml ---"
cat attack/uncond_gen/configs/bd_config_fix.yaml 2>/dev/null | grep -i "poison_rate" || echo "(not found or no poison_rate)"
echo "--- TAA milestones ---"
grep -n "milestones" attack/t2i_gen/rickrolling/rickrolling_TAA.py 2>/dev/null | head -3
echo "--- PaaS DB max_train_steps ---"
grep -n "max_train_steps" attack/t2i_gen/paas/paas_db.py 2>/dev/null | head -3
echo "--- textual_perturbation max_mse_dist ---"
grep -n "max_mse_dist" defense/input_level/textual_perturbation/textual_perturbation.py 2>/dev/null | head -3

echo ""
echo "=== RESULT DIRECTORIES ==="
ls -d results/*/ 2>/dev/null | while read d; do
    echo "  $d ($(ls "$d" 2>/dev/null | wc -l) files)"
done

echo ""
echo "=== DONE ==="
