#!/bin/bash
# 一键部署 v2 — 上传修复脚本 + 应用所有修复 + 重新启动流水线
# 用法: bash scripts/17_deploy_fixes_and_relaunch.sh
#
# 修复内容:
#   1. VillanDiff-uncond loss.py — empty if bodies → 加 pass
#   2. InviBackdoor — 创建 config + 修复相对路径
#   3. VillanDiff-cond — model_ver fallback
#   4. 本地 fallback 数据集 — 替代 gated zsf/laion_40k_metaForm
#   5. load.py — dataset fallback 逻辑
#   6. Checkpoint 重置 — 清除失败条目
#   7. Pipeline 更新 — --dataset CIFAR10 + --pretrained_model_name_or_path

set -euo pipefail

PORT=25579
SSH_CMD="ssh -o ConnectTimeout=10 -o ServerAliveInterval=15 amax -p $PORT"
SCP_CMD="scp -P $PORT"
BD_DIR="/opt/data/private/BackdoorDM"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

echo "$(ts) === Deploy Fixes & Relaunch v2 ==="

# 0. 连接测试
echo "$(ts) [0] Testing SSH..."
$SSH_CMD "echo CONNECTION_OK" || { echo "SSH FAILED — 跳板机 SSH 不可达"; exit 1; }

# 1. 上传修复脚本 + 更新后的 pipeline
echo "$(ts) [1] Uploading scripts..."
$SCP_CMD "$SCRIPT_DIR/16_apply_server_fixes.sh" "amax:/opt/data/private/"
$SCP_CMD "$SCRIPT_DIR/run_all_resilient.sh" "amax:$BD_DIR/"

# 2. 上传 NLTK 数据（如果本地有且服务器缺）
echo "$(ts) [2] Checking NLTK data..."
if [ -f /tmp/nltk_data.tar.gz ]; then
    NLTK_OK=$($SSH_CMD "test -d /root/nltk_data/corpora/wordnet && echo YES || echo NO")
    if [ "$NLTK_OK" = "NO" ]; then
        echo "$(ts)     Uploading NLTK data..."
        $SCP_CMD /tmp/nltk_data.tar.gz amax:/root/
        $SSH_CMD "cd /root && tar xzf nltk_data.tar.gz 2>/dev/null && echo 'NLTK extracted'"
    else
        echo "$(ts)     NLTK data already present"
    fi
else
    echo "$(ts)     /tmp/nltk_data.tar.gz not found, skipping"
fi

# 3. 应用所有代码修复
echo "$(ts) [3] Applying server-side fixes..."
$SSH_CMD "bash /opt/data/private/16_apply_server_fixes.sh"

# 4. 验证环境
echo "$(ts) [4] Verifying environment..."
$SSH_CMD "
export HF_ENDPOINT=https://hf-mirror.com
/opt/data/private/miniconda3/envs/eviledit/bin/python -c \"
import os; os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
import torch; assert torch.cuda.is_available()
print(f'GPU: {torch.cuda.get_device_name(0)}')
import diffusers, transformers, textattack
print(f'diffusers={diffusers.__version__}, transformers={transformers.__version__}')
# Verify fallback dataset
from datasets import load_dataset
ds = load_dataset('json', data_files='/opt/data/private/BackdoorDM/datasets/laion_fallback/train.jsonl')
print(f'Fallback dataset: {len(ds[\"train\"])} entries')
print('ENVIRONMENT OK')
\"
"

# 5. 确认没有正在运行的 pipeline
echo "$(ts) [5] Checking for running pipeline..."
RUNNING=$($SSH_CMD "pgrep -f 'run_all_resilient' || echo NONE")
if [ "$RUNNING" != "NONE" ]; then
    echo "WARNING: Pipeline already running (PID: $RUNNING)"
    echo "Kill it first? Use: ssh amax -p $PORT 'kill $RUNNING'"
    exit 1
fi

# 6. 启动 pipeline (nohup)
echo "$(ts) [6] Launching pipeline..."
$SSH_CMD "
cd $BD_DIR
nohup bash run_all_resilient.sh > logs/run_all.log 2>&1 &
echo \"Pipeline PID: \$!\"
sleep 2
# Verify it's running
if pgrep -f 'run_all_resilient' > /dev/null; then
    echo 'Pipeline started successfully'
    # Show first few lines of log
    tail -5 logs/run_all.log
else
    echo 'ERROR: Pipeline failed to start'
    tail -20 logs/run_all.log
    exit 1
fi
"

echo ""
echo "$(ts) ========================================="
echo "$(ts) DEPLOYMENT COMPLETE — Pipeline Running"
echo "$(ts) ========================================="
echo ""
echo "Monitor:"
echo "  进度:   ssh amax -p $PORT 'cat $BD_DIR/logs/.checkpoint'"
echo "  失败:   ssh amax -p $PORT 'cat $BD_DIR/logs/failures.log'"
echo "  计时:   ssh amax -p $PORT 'cat $BD_DIR/logs/timing.csv'"
echo "  实时:   ssh amax -p $PORT 'tail -50 $BD_DIR/logs/run_all.log'"
echo "  Master: ssh amax -p $PORT 'tail -50 $BD_DIR/logs/master.log'"
