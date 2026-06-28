#!/bin/bash
# 收集所有实验结果到一个汇总文件
# 在实验完成后运行

cd /opt/data/private/BackdoorDM

REPORT="/opt/data/private/BackdoorDM/logs/results_summary.txt"
echo "BackdoorDM Reproduction Results Summary" > "$REPORT"
echo "Generated: $(date '+%Y-%m-%d %H:%M:%S')" >> "$REPORT"
echo "==========================================" >> "$REPORT"

# Collect eval_results.csv from all result dirs
echo "" >> "$REPORT"
echo "=== T2I Attack Evaluation Results ===" >> "$REPORT"
find ./results -name "eval_results.csv" -exec echo "--- {} ---" \; -exec cat {} \; 2>/dev/null >> "$REPORT"

# Collect defense results
echo "" >> "$REPORT"
echo "=== Defense Results ===" >> "$REPORT"
find ./defenses -name "*.csv" -o -name "eval_results*" 2>/dev/null | while read f; do
    echo "--- $f ---" >> "$REPORT"
    cat "$f" >> "$REPORT"
done

# Check which methods completed successfully
echo "" >> "$REPORT"
echo "=== Completion Status ===" >> "$REPORT"

T2I_METHODS="eviledit eviledit_numAdd rickrolling_TPA rickrolling_TAA badt2i_pixel badt2i_object badt2i_style badt2i_objectAdd paas_ti paas_db bibaddiff villandiffusion_cond"
for m in $T2I_METHODS; do
    DIR=$(find ./results -maxdepth 2 -type d -name "*${m}*" 2>/dev/null | head -1)
    if [ -n "$DIR" ]; then
        echo "[OK] $m -> $DIR" >> "$REPORT"
    else
        echo "[MISSING] $m" >> "$REPORT"
    fi
done

UNCOND_METHODS="baddiffusion trojdiff villandiffusion invi_backdoor"
for m in $UNCOND_METHODS; do
    DIR="./results/${m}_DDPM-CIFAR10-32"
    if [ -d "$DIR" ]; then
        echo "[OK] $m -> $DIR" >> "$REPORT"
    else
        echo "[MISSING] $m" >> "$REPORT"
    fi
done

# Log file summary
echo "" >> "$REPORT"
echo "=== Log Files ===" >> "$REPORT"
find ./logs -name "*.log" -exec echo {} \; 2>/dev/null >> "$REPORT"

echo ""
echo "Results summary saved to: $REPORT"
cat "$REPORT"
