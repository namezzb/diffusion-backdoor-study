#!/bin/bash
# BiBadDiff 攻击 - ~12-24h
# 需要额外下载 imagenette 数据集和 v1-5-pruned.ckpt

set -e
cd /opt/data/private/BackdoorDM
export HF_ENDPOINT=https://hf-mirror.com

PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
LOG_DIR="/opt/data/private/BackdoorDM/logs/bibaddiff"
mkdir -p "$LOG_DIR"

echo "$(date '+%Y-%m-%d %H:%M:%S') === BiBadDiff Setup ==="

# Step 1: 下载 imagenette 数据集
IMAGENETTE_DIR="./attack/t2i_gen/bibaddiff/data/imagenette"
if [ ! -d "$IMAGENETTE_DIR/imagenette2" ]; then
    echo "Downloading imagenette dataset..."
    cd "$IMAGENETTE_DIR"
    wget -q https://s3.amazonaws.com/fast-ai-imageclas/imagenette2.tgz
    tar -zxf imagenette2.tgz
    $PYTHON badnets_imagenette.py
    cd /opt/data/private/BackdoorDM
else
    echo "[SKIP] imagenette already exists"
fi

# Step 2: 确认 v1-5-pruned.ckpt
CKPT_PATH="./results/bibaddiff_sd15/v1-5-pruned.ckpt"
if [ ! -f "$CKPT_PATH" ]; then
    echo "ERROR: $CKPT_PATH not found. Run 02_download_models.sh first."
    exit 1
fi

# Step 3: 运行 BiBadDiff 训练
echo "$(date '+%Y-%m-%d %H:%M:%S') [BiBadDiff] Starting training..."
cd ./attack/t2i_gen/bibaddiff
$PYTHON main.py \
    -t \
    --base configs/stable-diffusion/backdoor/imagenette/badnet_pr0.1_pt6.yaml \
    --gpus 0, \
    --scale_lr False \
    --num_nodes 1 \
    --check_val_every_n_epoch 10 \
    --logdir ../../../results/bibaddiff_sd15 \
    --finetune_from ../../../results/bibaddiff_sd15/v1-5-pruned.ckpt \
    2>&1 | tee "$LOG_DIR/bibaddiff_train.log"

cd /opt/data/private/BackdoorDM

# Step 4: 转换 .ckpt 到 diffusers 格式
echo "$(date '+%Y-%m-%d %H:%M:%S') [BiBadDiff] Converting checkpoint to diffusers format..."
LAST_CKPT=$(find ./results/bibaddiff_sd15/ -name "last.ckpt" -path "*/checkpoints/*" | head -1)
if [ -n "$LAST_CKPT" ]; then
    $PYTHON ./diffusers/scripts/convert_original_stable_diffusion_to_diffusers.py \
        --checkpoint_path "$LAST_CKPT" \
        --dump_path ./results/bibaddiff_sd15/bibaddiff_trigger-garbage_truck_target-badnets \
        2>&1 | tee "$LOG_DIR/bibaddiff_convert.log"
    echo "$(date '+%Y-%m-%d %H:%M:%S') [BiBadDiff] Conversion DONE"
else
    echo "ERROR: No last.ckpt found in results/bibaddiff_sd15/"
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') === BiBadDiff Complete ==="
