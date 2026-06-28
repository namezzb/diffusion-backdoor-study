#!/bin/bash
# VillanDiffusion Conditional (ImageFix) - ~20-30h
# 单独脚本，因为耗时极长

set -e
cd /opt/data/private/BackdoorDM
export HF_ENDPOINT=https://hf-mirror.com

PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
LOG_DIR="/opt/data/private/BackdoorDM/logs/villan_cond"
mkdir -p "$LOG_DIR"

echo "$(date '+%Y-%m-%d %H:%M:%S') === VillanDiffusion Conditional ==="
$PYTHON ./attack/t2i_gen/villan_diffusion_cond/villan_cond.py \
    --bd_config 'attack/t2i_gen/configs/bd_config_fix.yaml' \
    --gpu '0' \
    2>&1 | tee "$LOG_DIR/villan_cond.log"
echo "$(date '+%Y-%m-%d %H:%M:%S') === VillanDiffusion Conditional DONE ==="
