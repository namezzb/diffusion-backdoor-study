#!/bin/bash
# BackdoorDM 环境检查脚本
# 在运行任何实验之前执行此脚本确认环境就绪

set -e
cd /opt/data/private/BackdoorDM

echo "=== [1/6] GPU Info ==="
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader

echo ""
echo "=== [2/6] Python & PyTorch ==="
python -c "import torch; print(f'PyTorch: {torch.__version__}, CUDA: {torch.cuda.is_available()}, Device: {torch.cuda.get_device_name(0)}')"

echo ""
echo "=== [3/6] Key Dependencies ==="
python -c "
deps = ['diffusers', 'transformers', 'accelerate', 'omegaconf', 'einops',
        'kornia', 'open_clip', 'timm', 'lpips', 'cleanfid', 'torchmetrics',
        'peft', 'pytorch_lightning', 'bitsandbytes', 'textattack']
for d in deps:
    try:
        m = __import__(d)
        v = getattr(m, '__version__', 'ok')
        print(f'  {d}: {v}')
    except ImportError:
        print(f'  {d}: MISSING !!!')
"

echo ""
echo "=== [4/6] Cached Models ==="
for model_dir in \
    /opt/data/private/models/stable-diffusion-v1-5 \
    /opt/data/private/models/vit-base-patch16-224 \
    /opt/data/private/models/clip-vit-base-patch32; do
    if [ -d "$model_dir" ]; then
        echo "  [OK] $model_dir"
    else
        echo "  [MISSING] $model_dir"
    fi
done

echo ""
echo "=== [5/6] BackdoorDM Structure ==="
for subdir in attack/t2i_gen attack/uncond_gen defense evaluation utils scripts; do
    if [ -d "$subdir" ]; then
        echo "  [OK] $subdir"
    else
        echo "  [MISSING] $subdir"
    fi
done

echo ""
echo "=== [6/6] Existing Results ==="
if [ -d "results" ]; then
    ls -d results/*/ 2>/dev/null | head -20
else
    echo "  No results directory yet"
fi

echo ""
echo "=== Environment check complete ==="
