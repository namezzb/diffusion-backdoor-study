#!/bin/bash
# 首次评估: EvilEdit ACCASR (不需要 CLIP 模型，可以在 CLIP 下载期间先跑)
# 用法: ssh amax -p <port> "bash -s" < scripts/02d_first_eval_eviledit.sh

set -e
export HF_ENDPOINT=https://hf-mirror.com
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
cd /opt/data/private/BackdoorDM

echo "=== $(date '+%Y-%m-%d %H:%M:%S') EvilEdit 首次评估 ==="

# 前置检查
echo "--- 前置检查 ---"

# 后门模型
EVILEDIT_PT="./results/eviledit_sd15/eviledit_trigger-beautifuldog_target-cat.pt"
if [ ! -f "$EVILEDIT_PT" ]; then
    echo "[FAIL] 后门模型不存在: $EVILEDIT_PT"
    exit 1
fi
echo "[OK] 后门模型: $(du -sh "$EVILEDIT_PT" | cut -f1)"

# ViT 模型 (ACCASR 需要)
VIT_DIR="/opt/data/private/models/vit-base-patch16-224"
if [ ! -d "$VIT_DIR" ]; then
    echo "[FAIL] ViT 模型不存在: $VIT_DIR"
    exit 1
fi
echo "[OK] ViT 模型: $(du -sh "$VIT_DIR" | cut -f1)"

# SD v1.5
SD_DIR="/opt/data/private/models/stable-diffusion-v1-5"
if [ ! -d "$SD_DIR" ]; then
    echo "[FAIL] SD v1.5 不存在: $SD_DIR"
    exit 1
fi
echo "[OK] SD v1.5: $(du -sh "$SD_DIR" | cut -f1)"

# val_data 可访问性
echo "[CHECK] val_data..."
$PYTHON -c "
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
from datasets import load_dataset
ds = load_dataset('sayakpaul/coco-30-val-2014', split='train', streaming=True)
sample = next(iter(ds))
print('[OK] val_data 可访问')
" 2>/dev/null

echo ""
echo "--- 运行 EvilEdit ACCASR 评估 ---"
LOG_DIR="/opt/data/private/BackdoorDM/logs/eval_t2i"
mkdir -p "$LOG_DIR"

$PYTHON ./evaluation/main_eval.py \
    --metric ACCASR \
    --backdoor_method eviledit \
    --device cuda:0 \
    2>&1 | tee "$LOG_DIR/ACCASR_eviledit.log"

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') === EvilEdit ACCASR 评估完成 ==="
echo "日志: $LOG_DIR/ACCASR_eviledit.log"

# 提取结果
echo ""
echo "--- 结果摘要 ---"
grep -iE "acc|asr|accuracy|result" "$LOG_DIR/ACCASR_eviledit.log" | tail -10
