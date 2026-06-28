#!/bin/bash
# 一键启动: 修复环境 → EvilEdit评估 → 全量攻防流水线
# 用法:
#   1. scp -P 25579 /tmp/nltk_data.tar.gz amax:/root/
#   2. scp -P 25579 scripts/run_all_resilient.sh amax:/opt/data/private/BackdoorDM/
#   3. ssh amax -p 25579 "bash -s" < scripts/14_launch_full_pipeline.sh
#
# 或者直接在服务器上 nohup:
#   nohup bash /opt/data/private/BackdoorDM/14_launch_full_pipeline.sh > /opt/data/private/BackdoorDM/logs/launch.log 2>&1 &

set -euo pipefail
export HF_ENDPOINT=https://hf-mirror.com
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
PIP="/opt/data/private/miniconda3/envs/eviledit/bin/pip"
BD_DIR="/opt/data/private/BackdoorDM"

cd "$BD_DIR"
mkdir -p logs

ts() { date '+%Y-%m-%d %H:%M:%S'; }

echo "$(ts) ========================================="
echo "$(ts) FULL PIPELINE LAUNCH"
echo "$(ts) ========================================="

# ============================================================
# PHASE 0: NLTK 数据修复
# ============================================================
echo "$(ts) === Phase 0: NLTK 数据 ==="
if [ -f /root/nltk_data.tar.gz ]; then
    cd /root && tar xzf nltk_data.tar.gz 2>/dev/null; cd "$BD_DIR"
    echo "$(ts) NLTK data extracted"
fi

REQUIRED_DIRS=("/root/nltk_data/corpora/wordnet" "/root/nltk_data/tokenizers/punkt" "/root/nltk_data/taggers/averaged_perceptron_tagger")
for d in "${REQUIRED_DIRS[@]}"; do
    if [ ! -d "$d" ]; then
        echo "$(ts) [ERROR] Missing NLTK dir: $d"
        echo "$(ts) Attempting download..."
        $PYTHON -c "import nltk; nltk.download('all', download_dir='/root/nltk_data', quiet=True)" 2>/dev/null || true
        break
    fi
done
echo "$(ts) NLTK data ready"

# ============================================================
# PHASE 0b: huggingface_hub 版本修复
# ============================================================
echo "$(ts) === Phase 0b: 版本修复 ==="
CUR_HF=$($PYTHON -c "import huggingface_hub; print(huggingface_hub.__version__)" 2>/dev/null || echo "0.0.0")
echo "$(ts) huggingface_hub: $CUR_HF"

if [[ "$CUR_HF" == 0.* ]]; then
    echo "$(ts) Upgrading huggingface_hub..."
    $PIP install "huggingface_hub>=0.25" --index-url https://pypi.org/simple -q 2>&1 | tail -3
    echo "$(ts) Now: $($PYTHON -c 'import huggingface_hub; print(huggingface_hub.__version__)')"
fi

# ============================================================
# PHASE 0c: 快速验证
# ============================================================
echo "$(ts) === Phase 0c: 环境验证 ==="
$PYTHON -c "
import os; os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
import torch
assert torch.cuda.is_available()
print(f'GPU: {torch.cuda.get_device_name(0)}, VRAM: {torch.cuda.get_device_properties(0).total_memory/1024**3:.1f}GB')
import diffusers, transformers, textattack
print(f'diffusers={diffusers.__version__}, transformers={transformers.__version__}, textattack={textattack.__version__}')
print('Environment OK')
"
echo "$(ts) 环境验证通过"

# ============================================================
# PHASE 1: EvilEdit ACCASR 快速评估
# ============================================================
echo ""
echo "$(ts) === Phase 1: EvilEdit ACCASR ==="
mkdir -p logs/eval_t2i

$PYTHON ./evaluation/main_eval.py \
    --metric ACCASR \
    --backdoor_method eviledit \
    --device cuda:0 \
    2>&1 | tee logs/eval_t2i/ACCASR_eviledit.log

echo "$(ts) EvilEdit ACCASR 完成"
echo "--- 结果 ---"
grep -iE "acc|asr|accuracy|result|clean|backdoor" logs/eval_t2i/ACCASR_eviledit.log 2>/dev/null | tail -10

# ============================================================
# PHASE 2: 启动全量流水线 (nohup)
# ============================================================
echo ""
echo "$(ts) === Phase 2: 启动全量流水线 ==="

if [ -f "$BD_DIR/run_all_resilient.sh" ]; then
    echo "$(ts) 以 nohup 方式启动 run_all_resilient.sh..."
    nohup bash "$BD_DIR/run_all_resilient.sh" > logs/run_all.log 2>&1 &
    PIPELINE_PID=$!
    echo "$(ts) Pipeline PID: $PIPELINE_PID"
    echo "$(ts) 日志: $BD_DIR/logs/run_all.log"
    echo "$(ts) 监控: tail -f $BD_DIR/logs/run_all.log"
    echo "$(ts) 进度: cat $BD_DIR/logs/.checkpoint"
else
    echo "$(ts) [ERROR] run_all_resilient.sh not found!"
    echo "$(ts) 请先上传: scp -P 25579 scripts/run_all_resilient.sh amax:$BD_DIR/"
fi

echo ""
echo "$(ts) ========================================="
echo "$(ts) LAUNCH COMPLETE"
echo "$(ts) ========================================="
