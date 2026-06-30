#!/bin/bash
# One-click deployment script: run when SSH recovers
# Checks pipeline status, deploys fixes, starts post-pipeline work

set -uo pipefail
PORT=<port>
BD="/opt/data/private/BackdoorDM"
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== SSH Recovery Deployment Script ==="
echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Step 0: Verify SSH
echo "--- Step 0: SSH 连通性验证 ---"
if ! ssh -o ConnectTimeout=10 amax -p $PORT "echo 'SSH OK'" 2>/dev/null; then
    echo "ERROR: SSH still unreachable"
    exit 1
fi
echo "✓ SSH connected"

# Step 1: Check pipeline status
echo ""
echo "--- Step 1: Pipeline 状态检查 ---"
echo ""
echo "[Checkpoint]:"
ssh amax -p $PORT "cat $BD/logs/.checkpoint 2>/dev/null"
echo ""
echo "[Failures]:"
ssh amax -p $PORT "cat $BD/logs/failures.log 2>/dev/null || echo '(none)'"
echo ""
echo "[Last 5 timing entries]:"
ssh amax -p $PORT "tail -5 $BD/logs/timing.csv 2>/dev/null"
echo ""
echo "[Pipeline process]:"
ssh amax -p $PORT "ps aux | grep run_all_resilient | grep -v grep | head -3"
echo ""
echo "[GPU status]:"
ssh amax -p $PORT "nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader" 2>/dev/null
echo ""
echo "[Last 10 log lines]:"
ssh amax -p $PORT "tail -10 $BD/logs/run_all.log 2>/dev/null"
echo ""

# Step 2: Deploy TextPerturb fix (if not already)
echo "--- Step 2: TextPerturb MSE 修复 ---"
ssh amax -p $PORT "$PYTHON -c \"
import yaml, os
cfg_path = os.path.join('$BD', 'defense/input_level/textual_perturbation/configs/text_perturbation.yaml')
alt_path = os.path.join('$BD', 'defense/t2i_gen/text_perturb/configs/text_perturbation.yaml')
path = cfg_path if os.path.exists(cfg_path) else alt_path
if os.path.exists(path):
    with open(path) as f:
        cfg = yaml.safe_load(f)
    val = cfg.get('max_mse_dist', 'not_found')
    if isinstance(val, (int, float)) and val > 0.06:
        cfg['max_mse_dist'] = 0.05
        with open(path, 'w') as f:
            yaml.dump(cfg, f, default_flow_style=False)
        print(f'Fixed max_mse_dist: {val} -> 0.05')
    else:
        print(f'max_mse_dist OK: {val}')
else:
    # Try to find the config
    import subprocess
    result = subprocess.run(['find', '$BD', '-name', 'text_perturbation.yaml'], capture_output=True, text=True)
    print(f'Config not found at expected paths. Found: {result.stdout.strip()}')
\"" 2>/dev/null && echo "✓ TextPerturb fix checked" || echo "⚠ TextPerturb fix check failed"

# Step 3: Deploy post-pipeline and metrics scripts
echo ""
echo "--- Step 3: 部署后续脚本 ---"
scp -P $PORT "$SCRIPTS_DIR/27_post_pipeline_completion.sh" amax:$BD/ 2>/dev/null && echo "✓ 27_post_pipeline_completion.sh" || echo "✗ 27"
scp -P $PORT "$SCRIPTS_DIR/28_extract_all_metrics.sh" amax:$BD/ 2>/dev/null && echo "✓ 28_extract_all_metrics.sh" || echo "✗ 28"

# Step 4: Check if pipeline is still running
echo ""
echo "--- Step 4: 决定下一步 ---"
PIPELINE_RUNNING=$(ssh amax -p $PORT "ps aux | grep run_all_resilient | grep -v grep | wc -l" 2>/dev/null)

if [ "$PIPELINE_RUNNING" -gt 0 ]; then
    echo "Pipeline 仍在运行中。脚本已部署，pipeline 完成后手动运行:"
    echo "  ssh amax -p $PORT \"cd $BD && nohup bash 27_post_pipeline_completion.sh > logs/post_pipeline.log 2>&1 &\""
    echo ""
    echo "或者等 pipeline 完成后自动链接 (看 checkpoint 决定):"
    CHECKPOINT_COUNT=$(ssh amax -p $PORT "wc -l < $BD/logs/.checkpoint" 2>/dev/null)
    echo "  当前 checkpoint 步数: $CHECKPOINT_COUNT"
else
    echo "Pipeline 已完成或未运行。"
    echo ""
    read -p "立即启动 post-pipeline 脚本? [y/N] " answer
    if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
        ssh amax -p $PORT "cd $BD && nohup bash 27_post_pipeline_completion.sh > logs/post_pipeline.log 2>&1 &"
        echo "✓ Post-pipeline 已启动"
    fi
fi

# Step 5: Extract current metrics
echo ""
echo "--- Step 5: 提取当前可用指标 ---"
ssh amax -p $PORT "cd $BD && bash 28_extract_all_metrics.sh" 2>/dev/null

echo ""
echo "=== 部署完成 ==="
echo "下载指标: scp -P $PORT amax:$BD/logs/all_metrics.json experiments/backdoordm_reproduce/results/"
