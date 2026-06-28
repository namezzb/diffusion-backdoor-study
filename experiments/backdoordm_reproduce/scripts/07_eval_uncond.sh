#!/bin/bash
# 无条件攻击评估: FID, MSE
# 需要在攻击完成后运行

set -e
cd /opt/data/private/BackdoorDM
export HF_ENDPOINT=https://hf-mirror.com

PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
LOG_DIR="/opt/data/private/BackdoorDM/logs/eval_uncond"
mkdir -p "$LOG_DIR"

UNCOND_METHODS="baddiffusion trojdiff villandiffusion invi_backdoor"

echo "$(date '+%Y-%m-%d %H:%M:%S') === Unconditional Evaluation ==="

# --- FID ---
echo "=== FID ==="
for m in $UNCOND_METHODS; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') FID: $m"
    $PYTHON ./evaluation/main_eval.py \
        --metric FID \
        --backdoor_method "$m" \
        --backdoored_model_path "./results/${m}_DDPM-CIFAR10-32" \
        --device cuda:0 \
        2>&1 | tee "$LOG_DIR/FID_${m}.log"
done

# --- MSE ---
echo ""
echo "=== MSE ==="
for m in $UNCOND_METHODS; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') MSE: $m"
    $PYTHON ./evaluation/main_eval.py \
        --metric MSE \
        --backdoor_method "$m" \
        --backdoored_model_path "./results/${m}_DDPM-CIFAR10-32" \
        --device cuda:0 \
        2>&1 | tee "$LOG_DIR/MSE_${m}.log"
done

# --- VillanDiffusion Conditional (FID + MSE) ---
echo ""
echo "=== VillanDiffusion Conditional ==="
echo "$(date '+%Y-%m-%d %H:%M:%S') FID: villandiffusion_cond"
$PYTHON ./evaluation/main_eval.py \
    --metric FID \
    --backdoor_method villandiffusion_cond \
    --device cuda:0 \
    2>&1 | tee "$LOG_DIR/FID_villandiffusion_cond.log"

echo "$(date '+%Y-%m-%d %H:%M:%S') MSE: villandiffusion_cond"
$PYTHON ./evaluation/main_eval.py \
    --metric MSE \
    --backdoor_method villandiffusion_cond \
    --device cuda:0 \
    2>&1 | tee "$LOG_DIR/MSE_villandiffusion_cond.log"

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') === Unconditional Evaluation Complete ==="
