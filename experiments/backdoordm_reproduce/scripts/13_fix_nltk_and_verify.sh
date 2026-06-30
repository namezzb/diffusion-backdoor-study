#!/bin/bash
# 修复 NLTK 数据 + 验证 textattack + 修复 huggingface_hub 降级
# 用法: 先 scp nltk_data.tar.gz 然后运行此脚本
# scp -P <port> /tmp/nltk_data.tar.gz amax:/root/
# ssh amax -p <port> "bash -s" < scripts/13_fix_nltk_and_verify.sh

set -euo pipefail
export HF_ENDPOINT=https://hf-mirror.com
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
PIP="/opt/data/private/miniconda3/envs/eviledit/bin/pip"

echo "=== Step 1: Extract NLTK data ==="
if [ -f /root/nltk_data.tar.gz ]; then
    cd /root
    tar xzf nltk_data.tar.gz --strip-components=0 2>/dev/null || tar xzf nltk_data.tar.gz
    echo "NLTK data extracted to /root/nltk_data/"
    ls -la /root/nltk_data/
else
    echo "WARNING: /root/nltk_data.tar.gz not found, checking existing data..."
fi

echo ""
echo "=== Step 2: Verify NLTK data ==="
ls /root/nltk_data/corpora/ 2>/dev/null || echo "No corpora dir"
ls /root/nltk_data/taggers/ 2>/dev/null || echo "No taggers dir"
ls /root/nltk_data/tokenizers/ 2>/dev/null || echo "No tokenizers dir"

echo ""
echo "=== Step 3: Fix huggingface_hub version ==="
CUR_HF=$($PYTHON -c "import huggingface_hub; print(huggingface_hub.__version__)" 2>/dev/null)
echo "Current huggingface_hub: $CUR_HF"

if [[ "$CUR_HF" == 0.* ]]; then
    echo "huggingface_hub too old ($CUR_HF), upgrading..."
    $PIP install "huggingface_hub>=0.25" --index-url https://pypi.org/simple -q 2>&1
    echo "Upgraded to: $($PYTHON -c 'import huggingface_hub; print(huggingface_hub.__version__)')"
fi

echo ""
echo "=== Step 4: Verify all critical imports ==="
$PYTHON -c "
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['TEXTATTACK_CACHE_DIR'] = '/root/.cache/textattack'

import torch
print(f'torch: {torch.__version__}, CUDA: {torch.cuda.is_available()}, GPU: {torch.cuda.get_device_name(0)}')
print(f'VRAM: {torch.cuda.get_device_properties(0).total_memory/1024**3:.1f} GB')

import huggingface_hub; print(f'huggingface_hub: {huggingface_hub.__version__}')
import transformers; print(f'transformers: {transformers.__version__}')
import diffusers; print(f'diffusers: {diffusers.__version__}')
import datasets; print(f'datasets: {datasets.__version__}')

import textattack; print(f'textattack: {textattack.__version__}')

from diffusers import StableDiffusionPipeline
print('StableDiffusionPipeline: OK')

import cleanfid; print(f'cleanfid: OK')
import torchmetrics; print(f'torchmetrics: {torchmetrics.__version__}')

print('')
print('ALL CRITICAL IMPORTS OK')
"

echo ""
echo "=== Step 5: Verify model paths ==="
for p in \
    "/opt/data/private/models/stable-diffusion-v1-5/model_index.json" \
    "/opt/data/private/models/vit-base-patch16-224/config.json" \
    "/opt/data/private/models/clip-vit-large-patch14/config.json" \
    "/opt/data/private/BackdoorDM/results/eviledit_sd15/eviledit_trigger-beautifuldog_target-cat.pt"; do
    if [ -f "$p" ]; then
        echo "  [OK] $p"
    else
        echo "  [MISSING] $p"
    fi
done

echo ""
echo "=== VERIFICATION COMPLETE ==="
