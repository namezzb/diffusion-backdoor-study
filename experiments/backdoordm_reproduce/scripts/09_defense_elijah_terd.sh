#!/bin/bash
# Elijah + TERD 防御 (model-level, unconditional methods)
# 需要无条件攻击完成后运行

set -e
cd /opt/data/private/BackdoorDM
export HF_ENDPOINT=https://hf-mirror.com

PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
LOG_DIR="/opt/data/private/BackdoorDM/logs/defense_elijah_terd"
mkdir -p "$LOG_DIR"

echo "$(date '+%Y-%m-%d %H:%M:%S') === Elijah Defense ==="

# Elijah against BadDiffusion
echo "$(date '+%Y-%m-%d %H:%M:%S') Elijah: baddiffusion"
$PYTHON defense/model_level/Elijah/elijah.py \
    --backdoor_method baddiffusion \
    --backdoored_model_path ./results/baddiffusion_DDPM-CIFAR10-32 \
    --device cuda:0 \
    2>&1 | tee "$LOG_DIR/elijah_baddiffusion.log"

# Elijah against TrojDiff
echo "$(date '+%Y-%m-%d %H:%M:%S') Elijah: trojdiff"
$PYTHON defense/model_level/Elijah/elijah.py \
    --backdoor_method trojdiff \
    --backdoored_model_path ./results/trojdiff_DDPM-CIFAR10-32 \
    --device cuda:0 \
    2>&1 | tee "$LOG_DIR/elijah_trojdiff.log"

# Elijah against VillanDiffusion
echo "$(date '+%Y-%m-%d %H:%M:%S') Elijah: villandiffusion"
$PYTHON defense/model_level/Elijah/elijah.py \
    --backdoor_method villandiffusion \
    --backdoored_model_path ./results/villandiffusion_DDPM-CIFAR10-32 \
    --device cuda:0 \
    2>&1 | tee "$LOG_DIR/elijah_villandiffusion.log"

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') === TERD Model Defense ==="

# TERD-Model against BadDiffusion
echo "$(date '+%Y-%m-%d %H:%M:%S') TERD-Model: baddiffusion"
$PYTHON defense/model_level/Terd_model/terd_model.py \
    --backdoor_method baddiffusion \
    --backdoored_model_path ./results/baddiffusion_DDPM-CIFAR10-32 \
    --device cuda:0 \
    2>&1 | tee "$LOG_DIR/terd_model_baddiffusion.log"

# TERD-Model against TrojDiff
echo "$(date '+%Y-%m-%d %H:%M:%S') TERD-Model: trojdiff"
$PYTHON defense/model_level/Terd_model/terd_model.py \
    --backdoor_method trojdiff \
    --backdoored_model_path ./results/trojdiff_DDPM-CIFAR10-32 \
    --device cuda:0 \
    2>&1 | tee "$LOG_DIR/terd_model_trojdiff.log"

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') === TERD Input Defense ==="

# TERD-Input against BadDiffusion
echo "$(date '+%Y-%m-%d %H:%M:%S') TERD-Input: baddiffusion"
$PYTHON defense/input_level/Terd_input/terd_input.py \
    --backdoor_method baddiffusion \
    --backdoored_model_path ./results/baddiffusion_DDPM-CIFAR10-32 \
    --device cuda:0 \
    2>&1 | tee "$LOG_DIR/terd_input_baddiffusion.log"

# TERD-Input against TrojDiff
echo "$(date '+%Y-%m-%d %H:%M:%S') TERD-Input: trojdiff"
$PYTHON defense/input_level/Terd_input/terd_input.py \
    --backdoor_method trojdiff \
    --backdoored_model_path ./results/trojdiff_DDPM-CIFAR10-32 \
    --device cuda:0 \
    2>&1 | tee "$LOG_DIR/terd_input_trojdiff.log"

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') === Elijah + TERD Complete ==="
