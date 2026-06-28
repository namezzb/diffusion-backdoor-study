#!/bin/bash
# Phase 1: 快速 T2I 攻击 (< 30分钟)
# EvilEdit (~10s), EvilEdit NumAdd (~10s), Rickrolling TPA (~10min),
# Rickrolling TAA (~15min), PaaS TI (~30min)

set -e
cd /opt/data/private/BackdoorDM
export HF_ENDPOINT=https://hf-mirror.com

PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
LOG_DIR="/opt/data/private/BackdoorDM/logs/t2i_fast"
mkdir -p "$LOG_DIR"

echo "$(date '+%Y-%m-%d %H:%M:%S') === Phase 1: Fast T2I Attacks ==="

# --- 1. EvilEdit (ObjectRep) ---
echo "$(date '+%Y-%m-%d %H:%M:%S') [1/7] EvilEdit (ObjectRep) - ~10s"
$PYTHON ./attack/t2i_gen/eviledit/eviledit.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_objectRep.yaml' \
    --model_ver 'sd15' \
    --device 'cuda:0' \
    2>&1 | tee "$LOG_DIR/eviledit_objectRep.log"
echo "$(date '+%Y-%m-%d %H:%M:%S') [1/7] EvilEdit DONE"

# --- 2. EvilEdit NumAdd (ObjectAdd) ---
echo "$(date '+%Y-%m-%d %H:%M:%S') [2/7] EvilEdit NumAdd (ObjectAdd) - ~10s"
$PYTHON ./attack/t2i_gen/eviledit/eviledit_numAdd.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_objectAdd.yaml' \
    --model_ver 'sd15' \
    --device 'cuda:0' \
    2>&1 | tee "$LOG_DIR/eviledit_objectAdd.log"
echo "$(date '+%Y-%m-%d %H:%M:%S') [2/7] EvilEdit NumAdd DONE"

# --- 3. Rickrolling TPA (ObjectRep) ---
echo "$(date '+%Y-%m-%d %H:%M:%S') [3/7] Rickrolling TPA (ObjectRep) - ~10min"
$PYTHON ./attack/t2i_gen/rickrolling/rickrolling_TPA.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_objectRep.yaml' \
    --model_ver 'sd15' \
    --device 'cuda:0' \
    2>&1 | tee "$LOG_DIR/rickrolling_TPA.log"
echo "$(date '+%Y-%m-%d %H:%M:%S') [3/7] Rickrolling TPA DONE"

# --- 4. Rickrolling TAA (StyleAdd) ---
echo "$(date '+%Y-%m-%d %H:%M:%S') [4/7] Rickrolling TAA (StyleAdd) - ~15min"
$PYTHON ./attack/t2i_gen/rickrolling/rickrolling_TAA.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_styleAdd.yaml' \
    --model_ver 'sd15' \
    --device 'cuda:0' \
    2>&1 | tee "$LOG_DIR/rickrolling_TAA.log"
echo "$(date '+%Y-%m-%d %H:%M:%S') [4/7] Rickrolling TAA DONE"

# --- 5. PaaS TI (ObjectRep) ---
echo "$(date '+%Y-%m-%d %H:%M:%S') [5/7] PaaS TI (ObjectRep) - ~30min"
$PYTHON ./attack/t2i_gen/paas/paas_ti.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_objectRep.yaml' \
    --model_ver 'sd15' \
    --device 'cuda:0' \
    2>&1 | tee "$LOG_DIR/paas_ti.log"
echo "$(date '+%Y-%m-%d %H:%M:%S') [5/7] PaaS TI DONE"

# --- 6. PaaS DB (ObjectRep) ---
echo "$(date '+%Y-%m-%d %H:%M:%S') [6/7] PaaS DB (ObjectRep) - ~45min"
$PYTHON ./attack/t2i_gen/paas/paas_db.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_objectRep.yaml' \
    --model_ver 'sd15' \
    --device 'cuda:0' \
    2>&1 | tee "$LOG_DIR/paas_db.log"
echo "$(date '+%Y-%m-%d %H:%M:%S') [6/7] PaaS DB DONE"

# --- 7. BadT2I Pixel (ImagePatch) ---
echo "$(date '+%Y-%m-%d %H:%M:%S') [7/7] BadT2I Pixel (ImagePatch) - ~2h"
$PYTHON ./attack/t2i_gen/badt2i/badt2i_pixel.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_imagePatch.yaml' \
    --model_ver 'sd15' \
    --device 'cuda:0' \
    2>&1 | tee "$LOG_DIR/badt2i_pixel.log"
echo "$(date '+%Y-%m-%d %H:%M:%S') [7/7] BadT2I Pixel DONE"

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') === Phase 1 Complete ==="
echo "Logs saved to: $LOG_DIR"
