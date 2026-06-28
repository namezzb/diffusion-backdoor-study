#!/bin/bash
# Phase 3: 无条件攻击 (CIFAR10-32, 较快)
# BadDiffusion (~3h), TrojDiff (~4h), VillanDiffusion (~3h), InviBackdoor (~5h)
# 先在 CIFAR10-32 上跑，如需 CelebA-HQ-256 另行配置

set -e
cd /opt/data/private/BackdoorDM
export HF_ENDPOINT=https://hf-mirror.com

PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
LOG_DIR="/opt/data/private/BackdoorDM/logs/uncond"
mkdir -p "$LOG_DIR"

echo "$(date '+%Y-%m-%d %H:%M:%S') === Phase 3: Unconditional Attacks (CIFAR10-32) ==="

# --- 1. BadDiffusion ---
echo "$(date '+%Y-%m-%d %H:%M:%S') [1/4] BadDiffusion - ~3h"
$PYTHON ./attack/uncond_gen/bad_diffusion/bad_diffusion.py \
    --base_config 'attack/uncond_gen/configs/base_config.yaml' \
    --bd_config 'attack/uncond_gen/configs/bd_config_fix.yaml' \
    --sched 'DDPM-SCHED' \
    --ckpt 'DDPM-CIFAR10-32' \
    --gpu '0' \
    2>&1 | tee "$LOG_DIR/baddiffusion.log"
echo "$(date '+%Y-%m-%d %H:%M:%S') [1/4] BadDiffusion DONE"

# --- 2. TrojDiff ---
echo "$(date '+%Y-%m-%d %H:%M:%S') [2/4] TrojDiff - ~4h"
$PYTHON ./attack/uncond_gen/trojdiff/trojdiff.py \
    --base_config 'attack/uncond_gen/configs/base_config.yaml' \
    --bd_config 'attack/uncond_gen/configs/bd_config_fix.yaml' \
    --epoch 500 \
    --sched 'DDPM-SCHED' \
    --ckpt 'DDPM-CIFAR10-32' \
    --gpu '0' \
    2>&1 | tee "$LOG_DIR/trojdiff.log"
echo "$(date '+%Y-%m-%d %H:%M:%S') [2/4] TrojDiff DONE"

# --- 3. VillanDiffusion ---
echo "$(date '+%Y-%m-%d %H:%M:%S') [3/4] VillanDiffusion - ~3h"
$PYTHON ./attack/uncond_gen/villan_diffusion/villan_diffusion.py \
    --base_config 'attack/uncond_gen/configs/base_config.yaml' \
    --bd_config 'attack/uncond_gen/configs/bd_config_fix.yaml' \
    --sched 'DDPM-SCHED' \
    --ckpt 'DDPM-CIFAR10-32' \
    --gpu '0' \
    2>&1 | tee "$LOG_DIR/villandiffusion.log"
echo "$(date '+%Y-%m-%d %H:%M:%S') [3/4] VillanDiffusion DONE"

# --- 4. InviBackdoor ---
echo "$(date '+%Y-%m-%d %H:%M:%S') [4/4] InviBackdoor - ~5h"
$PYTHON ./attack/uncond_gen/invi_backdoor/invi_backdoor.py \
    --base_config 'attack/uncond_gen/configs/base_config.yaml' \
    --bd_config 'attack/uncond_gen/configs/bd_config_fix.yaml' \
    --sched 'DDPM-SCHED' \
    --ckpt 'DDPM-CIFAR10-32' \
    --gpu '0' \
    2>&1 | tee "$LOG_DIR/invi_backdoor.log"
echo "$(date '+%Y-%m-%d %H:%M:%S') [4/4] InviBackdoor DONE"

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') === Phase 3 Complete ==="
