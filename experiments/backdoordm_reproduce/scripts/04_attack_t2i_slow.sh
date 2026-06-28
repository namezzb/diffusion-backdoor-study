#!/bin/bash
# Phase 2: 慢速 T2I 攻击 (> 6小时)
# BadT2I Object (~8h), BadT2I Style (~8h), BadT2I ObjectAdd (~8h)

set -e
cd /opt/data/private/BackdoorDM
export HF_ENDPOINT=https://hf-mirror.com

PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
LOG_DIR="/opt/data/private/BackdoorDM/logs/t2i_slow"
mkdir -p "$LOG_DIR"

echo "$(date '+%Y-%m-%d %H:%M:%S') === Phase 2: Slow T2I Attacks ==="

# --- 1. BadT2I Object (ObjectRep) ---
echo "$(date '+%Y-%m-%d %H:%M:%S') [1/3] BadT2I Object (ObjectRep) - ~8h"
$PYTHON ./attack/t2i_gen/badt2i/badt2i_object.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_objectRep.yaml' \
    --model_ver 'sd15' \
    --device 'cuda:0' \
    2>&1 | tee "$LOG_DIR/badt2i_object.log"
echo "$(date '+%Y-%m-%d %H:%M:%S') [1/3] BadT2I Object DONE"

# --- 2. BadT2I Style (StyleAdd) ---
echo "$(date '+%Y-%m-%d %H:%M:%S') [2/3] BadT2I Style (StyleAdd) - ~8h"
$PYTHON ./attack/t2i_gen/badt2i/badt2i_style.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_styleAdd.yaml' \
    --model_ver 'sd15' \
    --device 'cuda:0' \
    2>&1 | tee "$LOG_DIR/badt2i_style.log"
echo "$(date '+%Y-%m-%d %H:%M:%S') [2/3] BadT2I Style DONE"

# --- 3. BadT2I ObjectAdd ---
echo "$(date '+%Y-%m-%d %H:%M:%S') [3/3] BadT2I ObjectAdd - ~8h"
$PYTHON ./attack/t2i_gen/badt2i/badt2i_objectAdd.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_objectAdd.yaml' \
    --model_ver 'sd15' \
    --device 'cuda:0' \
    2>&1 | tee "$LOG_DIR/badt2i_objectAdd.log"
echo "$(date '+%Y-%m-%d %H:%M:%S') [3/3] BadT2I ObjectAdd DONE"

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') === Phase 2 Complete ==="
