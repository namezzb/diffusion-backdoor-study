#!/bin/bash
# 服务器重连后的一键执行主脚本
# 顺序: 环境验证 -> 配置修复 -> CLIP下载(后台) -> EvilEdit评估 -> 全量攻击
# 用法: ssh amax -p 25579 "bash -s" < scripts/master_reconnect.sh

set -euo pipefail
export HF_ENDPOINT=https://hf-mirror.com
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
cd /opt/data/private/BackdoorDM

TS() { date '+%Y-%m-%d %H:%M:%S'; }
LOG_BASE="/opt/data/private/BackdoorDM/logs"
mkdir -p "$LOG_BASE"/{eval_t2i,t2i_fast,t2i_slow}

echo "$(TS) =============================="
echo "$(TS) BackdoorDM 重连主流程开始"
echo "$(TS) =============================="

# ============================================================
# STEP 1: 快速环境验证
# ============================================================
echo ""
echo "$(TS) === STEP 1: 环境验证 ==="

$PYTHON -c "
import torch
assert torch.cuda.is_available(), 'CUDA not available!'
print(f'  PyTorch {torch.__version__}, GPU: {torch.cuda.get_device_name(0)}')
print(f'  VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB')
"

# 验证关键路径
for p in \
    "/opt/data/private/models/stable-diffusion-v1-5/model_index.json" \
    "/opt/data/private/models/vit-base-patch16-224/config.json" \
    "./results/eviledit_sd15/eviledit_trigger-beautifuldog_target-cat.pt"; do
    if [ -f "$p" ]; then
        echo "  [OK] $p"
    else
        echo "  [MISSING] $p"
        exit 1
    fi
done
echo "$(TS) 环境验证通过"

# ============================================================
# STEP 2: 配置修复
# ============================================================
echo ""
echo "$(TS) === STEP 2: 配置修复 ==="

# eval_config clip_model 本地路径
EVAL_CFG="evaluation/configs/eval_config.yaml"
if grep -q "clip_model: 'openai/clip-vit-large-patch14'" "$EVAL_CFG" 2>/dev/null; then
    sed -i "s|clip_model: 'openai/clip-vit-large-patch14'|clip_model: '/opt/data/private/models/clip-vit-large-patch14'|" "$EVAL_CFG"
    echo "  [FIXED] eval_config clip_model -> 本地路径"
else
    echo "  [OK] eval_config clip_model 已修复"
fi

# generate_img.py HF_ENDPOINT
for pyfile in evaluation/generate_img.py evaluation/main_eval.py; do
    if ! grep -q "HF_ENDPOINT" "$pyfile" 2>/dev/null; then
        if grep -q "^import os$" "$pyfile"; then
            sed -i '/^import os$/a os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")' "$pyfile"
        else
            sed -i '1i import os\nos.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")' "$pyfile"
        fi
        echo "  [FIXED] $pyfile HF_ENDPOINT"
    else
        echo "  [OK] $pyfile HF_ENDPOINT 已有"
    fi
done

echo "$(TS) 配置修复完成"

# ============================================================
# STEP 3: CLIP 下载 (后台，评估 CLIP_p/CLIP_c 需要)
# ============================================================
echo ""
echo "$(TS) === STEP 3: CLIP 下载 ==="
CLIP_DIR="/opt/data/private/models/clip-vit-large-patch14"

if [ -f "$CLIP_DIR/model.safetensors" ] || [ -f "$CLIP_DIR/pytorch_model.bin" ]; then
    echo "  [SKIP] CLIP 权重已存在"
else
    echo "  后台启动 CLIP 下载..."
    nohup $PYTHON -c "
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
from huggingface_hub import snapshot_download
snapshot_download('openai/clip-vit-large-patch14',
    local_dir='$CLIP_DIR', endpoint='https://hf-mirror.com', resume_download=True)
print('CLIP download complete!')
" > /opt/data/private/clip_download.log 2>&1 &
    echo "  CLIP 下载 PID: $!"
    echo "  日志: /opt/data/private/clip_download.log"
fi

# ============================================================
# STEP 4: EvilEdit ACCASR 评估 (不需要 CLIP)
# ============================================================
echo ""
echo "$(TS) === STEP 4: EvilEdit ACCASR 评估 ==="

$PYTHON ./evaluation/main_eval.py \
    --metric ACCASR \
    --backdoor_method eviledit \
    --device cuda:0 \
    2>&1 | tee "$LOG_BASE/eval_t2i/ACCASR_eviledit.log"

echo "$(TS) EvilEdit ACCASR 完成"
echo "--- 结果 ---"
grep -iE "acc|asr|accuracy|result|clean|backdoor" "$LOG_BASE/eval_t2i/ACCASR_eviledit.log" | tail -10

echo ""
echo "$(TS) =============================="
echo "$(TS) 首批任务完成"
echo "$(TS) =============================="
echo ""
echo "下一步:"
echo "  1. 检查 CLIP 下载: tail -f /opt/data/private/clip_download.log"
echo "  2. 运行全量 T2I 攻击: scripts/03_attack_t2i_fast.sh"
echo "  3. 运行全量评估: scripts/06_eval_t2i.sh"
