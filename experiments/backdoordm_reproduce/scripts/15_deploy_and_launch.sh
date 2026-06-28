#!/bin/bash
# 本地执行：一键部署 + 启动全量复现
# 功能: 上传NLTK数据 → 上传流水线脚本 → 修复环境 → 启动全量流水线(nohup)
# 用法: bash scripts/15_deploy_and_launch.sh

set -euo pipefail

PORT=25579
SSH_CMD="ssh amax -p $PORT"
SCP_CMD="scp -P $PORT"
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
PIP="/opt/data/private/miniconda3/envs/eviledit/bin/pip"
BD_DIR="/opt/data/private/BackdoorDM"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
echo "$(ts) === Deploy & Launch ==="

# 1. 连接测试
echo "$(ts) Testing SSH..."
$SSH_CMD "echo CONNECTION_OK" || { echo "SSH FAILED"; exit 1; }

# 2. 上传 NLTK 数据
echo "$(ts) Uploading NLTK data..."
if [ -f /tmp/nltk_data.tar.gz ]; then
    $SCP_CMD /tmp/nltk_data.tar.gz amax:/root/
    $SSH_CMD "cd /root && tar xzf nltk_data.tar.gz 2>/dev/null && echo 'NLTK extracted'"
else
    echo "WARNING: /tmp/nltk_data.tar.gz not found, skipping"
fi

# 3. 上传流水线脚本
echo "$(ts) Uploading pipeline script..."
$SCP_CMD "$SCRIPT_DIR/run_all_resilient.sh" "amax:$BD_DIR/"

# 4. 修复 huggingface_hub 版本
echo "$(ts) Fixing huggingface_hub..."
$SSH_CMD "
CUR_HF=\$($PYTHON -c 'import huggingface_hub; print(huggingface_hub.__version__)' 2>/dev/null || echo '0.0.0')
echo \"Current: \$CUR_HF\"
case \$CUR_HF in
    0.*)
        echo 'Upgrading...'
        $PIP install 'huggingface_hub>=0.25' --index-url https://pypi.org/simple -q 2>&1 | tail -3
        echo \"Now: \$($PYTHON -c 'import huggingface_hub; print(huggingface_hub.__version__)')\"
        ;;
    *) echo 'Version OK' ;;
esac
"

# 5. 验证环境
echo "$(ts) Verifying environment..."
$SSH_CMD "
export HF_ENDPOINT=https://hf-mirror.com
$PYTHON -c \"
import os; os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
import torch
assert torch.cuda.is_available()
print(f'GPU: {torch.cuda.get_device_name(0)}, VRAM: {torch.cuda.get_device_properties(0).total_memory/1024**3:.1f}GB')
import diffusers, transformers
print(f'diffusers={diffusers.__version__}, transformers={transformers.__version__}')
import textattack
print(f'textattack={textattack.__version__}')
print('ENVIRONMENT OK')
\"
"

# 6. EvilEdit ACCASR 快速评估
echo "$(ts) Running EvilEdit ACCASR evaluation..."
$SSH_CMD "
cd $BD_DIR
export HF_ENDPOINT=https://hf-mirror.com
mkdir -p logs/eval_t2i
$PYTHON ./evaluation/main_eval.py \
    --metric ACCASR \
    --backdoor_method eviledit \
    --device cuda:0 \
    2>&1 | tee logs/eval_t2i/ACCASR_eviledit.log
echo '---RESULTS---'
grep -iE 'acc|asr|accuracy|result' logs/eval_t2i/ACCASR_eviledit.log | tail -5
"

# 7. 启动全量流水线 (nohup)
echo "$(ts) Launching full pipeline (nohup)..."
$SSH_CMD "
cd $BD_DIR
nohup bash run_all_resilient.sh > logs/run_all.log 2>&1 &
echo \"Pipeline PID: \$!\"
echo 'Pipeline launched successfully'
"

echo ""
echo "$(ts) ========================================="
echo "$(ts) DEPLOYMENT COMPLETE"
echo "$(ts) ========================================="
echo ""
echo "Monitor commands:"
echo "  Progress: ssh amax -p $PORT 'cat $BD_DIR/logs/.checkpoint'"
echo "  Failures: ssh amax -p $PORT 'cat $BD_DIR/logs/failures.log'"
echo "  Timing:   ssh amax -p $PORT 'cat $BD_DIR/logs/timing.csv'"
echo "  Live log: ssh amax -p $PORT 'tail -50 $BD_DIR/logs/run_all.log'"
echo "  Master:   ssh amax -p $PORT 'tail -50 $BD_DIR/logs/master.log'"
