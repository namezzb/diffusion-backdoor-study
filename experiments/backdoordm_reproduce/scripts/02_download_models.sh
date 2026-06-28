#!/bin/bash
# 下载所有需要的模型和数据集
# HuggingFace 使用镜像 hf-mirror.com

set -e
cd /opt/data/private/BackdoorDM

PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
export HF_ENDPOINT=https://hf-mirror.com

echo "=== [1/5] SD v1.5 (already cached) ==="
if [ -d "/opt/data/private/models/stable-diffusion-v1-5" ]; then
    echo "  [SKIP] Already exists"
else
    echo "  Downloading SD v1.5..."
    $PYTHON -c "
from huggingface_hub import snapshot_download
snapshot_download('stable-diffusion-v1-5/stable-diffusion-v1-5',
                  local_dir='/opt/data/private/models/stable-diffusion-v1-5',
                  endpoint='https://hf-mirror.com')
"
fi

echo ""
echo "=== [2/5] ViT-base-patch16-224 (already cached) ==="
if [ -d "/opt/data/private/models/vit-base-patch16-224" ]; then
    echo "  [SKIP] Already exists"
else
    echo "  Downloading ViT..."
    $PYTHON -c "
from huggingface_hub import snapshot_download
snapshot_download('google/vit-base-patch16-224',
                  local_dir='/opt/data/private/models/vit-base-patch16-224',
                  endpoint='https://hf-mirror.com')
"
fi

echo ""
echo "=== [3/5] CLIP-ViT-Large-patch14 (for evaluation) ==="
CLIP_DIR="/opt/data/private/models/clip-vit-large-patch14"
if [ -d "$CLIP_DIR" ]; then
    echo "  [SKIP] Already exists"
else
    echo "  Downloading CLIP large..."
    $PYTHON -c "
from huggingface_hub import snapshot_download
snapshot_download('openai/clip-vit-large-patch14',
                  local_dir='$CLIP_DIR',
                  endpoint='https://hf-mirror.com')
"
fi

echo ""
echo "=== [4/5] DDPM Checkpoints (for unconditional attacks) ==="
for CKPT in "google/ddpm-cifar10-32" "google/ddpm-celebahq-256"; do
    CKPT_NAME=$(echo $CKPT | tr '/' '_')
    CKPT_DIR="/opt/data/private/models/$CKPT_NAME"
    if [ -d "$CKPT_DIR" ]; then
        echo "  [SKIP] $CKPT already exists"
    else
        echo "  Downloading $CKPT..."
        $PYTHON -c "
from huggingface_hub import snapshot_download
snapshot_download('$CKPT',
                  local_dir='$CKPT_DIR',
                  endpoint='https://hf-mirror.com')
"
    fi
done

echo ""
echo "=== [5/5] SD v1.5 pruned .ckpt (for BiBadDiff) ==="
BIBAD_DIR="/opt/data/private/BackdoorDM/results/bibaddiff_sd15"
if [ -f "$BIBAD_DIR/v1-5-pruned.ckpt" ]; then
    echo "  [SKIP] Already exists"
else
    echo "  Downloading v1-5-pruned.ckpt..."
    mkdir -p "$BIBAD_DIR"
    $PYTHON -c "
from huggingface_hub import hf_hub_download
hf_hub_download('stable-diffusion-v1-5/stable-diffusion-v1-5',
                filename='v1-5-pruned.ckpt',
                local_dir='$BIBAD_DIR',
                endpoint='https://hf-mirror.com')
"
fi

echo ""
echo "=== Model download complete ==="
