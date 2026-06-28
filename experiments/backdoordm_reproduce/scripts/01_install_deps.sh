#!/bin/bash
# 安装 BackdoorDM 所有依赖
# 使用已有的 eviledit conda env

set -e
cd /opt/data/private/BackdoorDM

PIP="/opt/data/private/miniconda3/envs/eviledit/bin/pip"

echo "=== Installing BackdoorDM dependencies ==="

# Core dependencies (most should already be installed)
$PIP install -q omegaconf einops kornia open-clip-torch timm \
    lpips clean-fid ftfy peft pytorch-lightning accelerate

# Evaluation dependencies
$PIP install -q torchmetrics cleanfid

# Defense dependencies
$PIP install -q textattack piq

# bitsandbytes for BadT2I 8-bit Adam
$PIP install -q bitsandbytes

# datasets for COCO validation
$PIP install -q datasets

echo "=== All dependencies installed ==="
