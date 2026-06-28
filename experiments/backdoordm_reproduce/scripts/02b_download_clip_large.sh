#!/bin/bash
# 下载 CLIP-ViT-Large-Patch14 (评估 CLIP_p/CLIP_c 指标必需)
# 上次下载在 23% 中断，此脚本支持断点续传
# 用法: ssh amax -p 25579 "bash -s" < scripts/02b_download_clip_large.sh

set -e
export HF_ENDPOINT=https://hf-mirror.com
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
CLIP_DIR="/opt/data/private/models/clip-vit-large-patch14"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') CLIP-ViT-Large-Patch14 下载 ==="

# 检查是否已有完整权重
if [ -f "$CLIP_DIR/model.safetensors" ] || [ -f "$CLIP_DIR/pytorch_model.bin" ]; then
    SIZE=$(du -sh "$CLIP_DIR" | cut -f1)
    echo "[SKIP] 权重文件已存在 ($SIZE)"
    ls -lh "$CLIP_DIR"/model.safetensors "$CLIP_DIR"/pytorch_model.bin 2>/dev/null
    exit 0
fi

echo "权重文件缺失，开始下载（断点续传）..."
echo "目标目录: $CLIP_DIR"
echo ""

# 使用 nohup 后台下载，防止 SSH 断连
nohup $PYTHON -c "
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
from huggingface_hub import snapshot_download
print('开始下载 clip-vit-large-patch14...')
snapshot_download(
    'openai/clip-vit-large-patch14',
    local_dir='$CLIP_DIR',
    endpoint='https://hf-mirror.com',
    resume_download=True
)
print('下载完成!')
# 验证
import os
for f in ['model.safetensors', 'pytorch_model.bin']:
    p = os.path.join('$CLIP_DIR', f)
    if os.path.exists(p):
        size_mb = os.path.getsize(p) / 1024 / 1024
        print(f'  {f}: {size_mb:.1f} MB')
" > /opt/data/private/clip_download.log 2>&1 &

PID=$!
echo "后台下载已启动 (PID: $PID)"
echo "日志: /opt/data/private/clip_download.log"
echo ""
echo "查看进度: tail -f /opt/data/private/clip_download.log"
echo "检查是否完成: ls -lh $CLIP_DIR/model.safetensors $CLIP_DIR/pytorch_model.bin 2>/dev/null"
