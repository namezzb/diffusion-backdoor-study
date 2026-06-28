#!/bin/bash
# 服务器重连后的环境验证和修复脚本
# 用法: ssh amax -p 25579 "bash -s" < scripts/00_reconnect_and_verify.sh

set -e
export HF_ENDPOINT=https://hf-mirror.com
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
cd /opt/data/private/BackdoorDM

echo "=== $(date '+%Y-%m-%d %H:%M:%S') 环境验证开始 ==="

# 1. Python 和关键依赖
echo ""
echo "--- 1. Python 环境 ---"
$PYTHON -c "
import torch, diffusers, transformers, accelerate
print(f'PyTorch: {torch.__version__}, CUDA: {torch.cuda.is_available()}, GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')
print(f'diffusers: {diffusers.__version__}, transformers: {transformers.__version__}, accelerate: {accelerate.__version__}')
"

# 2. 本地模型检查
echo ""
echo "--- 2. 本地模型缓存 ---"
for model_dir in \
    /opt/data/private/models/stable-diffusion-v1-5 \
    /opt/data/private/models/vit-base-patch16-224 \
    /opt/data/private/models/clip-vit-base-patch32; do
    if [ -d "$model_dir" ]; then
        echo "  [OK] $model_dir ($(du -sh "$model_dir" | cut -f1))"
    else
        echo "  [MISSING] $model_dir"
    fi
done

# CLIP large 模型 (评估用)
CLIP_DIR="/opt/data/private/models/clip-vit-large-patch14"
if [ -d "$CLIP_DIR" ]; then
    CLIP_SIZE=$(du -sh "$CLIP_DIR" | cut -f1)
    HAS_WEIGHTS=$(ls "$CLIP_DIR"/model.safetensors "$CLIP_DIR"/pytorch_model.bin 2>/dev/null | head -1)
    if [ -n "$HAS_WEIGHTS" ]; then
        echo "  [OK] clip-vit-large-patch14 ($CLIP_SIZE, weights present)"
    else
        echo "  [PARTIAL] clip-vit-large-patch14 ($CLIP_SIZE, config only - weights missing!)"
        echo "  [ACTION] 需要重新下载: 运行 02b_download_clip.sh"
    fi
else
    echo "  [MISSING] clip-vit-large-patch14"
    echo "  [ACTION] 需要下载: 运行 02b_download_clip.sh"
fi

# 3. get_sd_path 修复验证
echo ""
echo "--- 3. get_sd_path() 验证 ---"
$PYTHON -c "
import sys
sys.path.insert(0, '.')
from utils.utils import get_sd_path
sd14 = get_sd_path('sd14')
sd15 = get_sd_path('sd15')
local = '/opt/data/private/models/stable-diffusion-v1-5'
ok14 = sd14 == local
ok15 = sd15 == local
print(f'  sd14 -> {sd14} [{\"OK\" if ok14 else \"WRONG\"}]')
print(f'  sd15 -> {sd15} [{\"OK\" if ok15 else \"WRONG\"}]')
if not (ok14 and ok15):
    print('  [ACTION] 需要修复 utils/utils.py get_sd_path()')
    sys.exit(1)
"

# 4. 论文修复验证
echo ""
echo "--- 4. 论文交叉验证修复 ---"

# TAA milestones
TAA_MS=$(grep -o "milestones.*\[.*\]" attack/t2i_gen/rickrolling/rickrolling_TAA.py | head -1)
if echo "$TAA_MS" | grep -q "150"; then
    echo "  [OK] TAA milestones = [150]"
else
    echo "  [WRONG] TAA milestones: $TAA_MS (should be [150])"
fi

# PaaS DB max_train_steps
PAAS_STEPS=$(grep "max_train_steps" attack/t2i_gen/paas/paas_db.py | head -1)
if echo "$PAAS_STEPS" | grep -q "300"; then
    echo "  [OK] PaaS DB max_train_steps = 300"
else
    echo "  [WRONG] PaaS DB: $PAAS_STEPS (should be 300)"
fi

# base_config model_ver
BASE_MV=$(grep "model_ver" attack/t2i_gen/configs/base_config.yaml | head -1)
if echo "$BASE_MV" | grep -q "sd15"; then
    echo "  [OK] base_config model_ver = sd15"
else
    echo "  [WRONG] base_config: $BASE_MV (should be sd15)"
fi

# poison_rate
PR=$(grep "poison_rate" attack/uncond_gen/configs/bd_config_fix.yaml 2>/dev/null | head -1)
if echo "$PR" | grep -q "0.1"; then
    echo "  [OK] uncond poison_rate = 0.1"
else
    echo "  [CHECK] uncond poison_rate: $PR"
fi

# 5. EvilEdit 后门模型
echo ""
echo "--- 5. EvilEdit 后门模型 ---"
EVILEDIT_PT="./results/eviledit_sd15/eviledit_trigger-beautifuldog_target-cat.pt"
if [ -f "$EVILEDIT_PT" ]; then
    echo "  [OK] $EVILEDIT_PT ($(du -sh "$EVILEDIT_PT" | cut -f1))"
else
    echo "  [MISSING] $EVILEDIT_PT"
fi

# 6. eval_config.yaml 检查
echo ""
echo "--- 6. eval_config.yaml ---"
echo "  当前配置:"
grep -E "vit_model|clip_model|val_data|model_ver" evaluation/configs/eval_config.yaml | while read line; do
    echo "    $line"
done

# 7. val_data 可访问性 (快速检查)
echo ""
echo "--- 7. val_data 可访问性 ---"
$PYTHON -c "
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
try:
    from datasets import load_dataset
    ds = load_dataset('sayakpaul/coco-30-val-2014', split='train', streaming=True)
    sample = next(iter(ds))
    print(f'  [OK] val_data accessible, columns: {list(sample.keys())}')
except Exception as e:
    print(f'  [FAIL] val_data: {e}')
" 2>/dev/null || echo "  [FAIL] val_data check failed"

# 8. GPU 状态
echo ""
echo "--- 8. GPU 状态 ---"
nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader

echo ""
echo "=== $(date '+%Y-%m-%d %H:%M:%S') 验证完成 ==="
