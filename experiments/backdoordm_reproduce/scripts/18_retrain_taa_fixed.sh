#!/bin/bash
# 修复 Rickrolling TAA milestones 后重新训练
# 原因: BackdoorDM 从 TPA 复制时 milestones=[75] 遗漏改为 [150]
#       论文 (ICCV 2023) TAA 应使用 milestones=[150]
#
# 前置条件: 主 pipeline attack_rickrolling_TAA 已完成(使用错误的 milestones=[75])
# 用法: ssh amax -p 25579 "bash -s" < scripts/18_retrain_taa_fixed.sh

set -euo pipefail
export HF_ENDPOINT=https://hf-mirror.com
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
cd /opt/data/private/BackdoorDM

echo "$(date '+%Y-%m-%d %H:%M:%S') === 修复 Rickrolling TAA milestones ==="""

# Step 1: 修复代码
TAA_SCRIPT="./attack/t2i_gen/rickrolling/rickrolling_TAA.py"
if grep -q "milestones.*\[75\]" "$TAA_SCRIPT" 2>/dev/null; then
    echo "修复 milestones: [75] -> [150]"
    sed -i "s/milestones.*\[75\]/milestones': [150]/" "$TAA_SCRIPT"
    echo "已修复: $(grep 'milestones' "$TAA_SCRIPT")"
else
    echo "milestones 已是正确值或格式不同，检查当前值:"
    grep -n "milestones" "$TAA_SCRIPT" || echo "(未找到 milestones)"
fi

# Step 2: 备份旧结果
OLD_DIR="./results/rickrolling_TAA_sd15"
if [ -d "$OLD_DIR" ]; then
    BACKUP="./results/rickrolling_TAA_sd15_milestones75_backup"
    if [ ! -d "$BACKUP" ]; then
        echo "备份旧结果: $OLD_DIR -> $BACKUP"
        cp -r "$OLD_DIR" "$BACKUP"
    fi
fi

# Step 3: 重新训练
echo "$(date '+%Y-%m-%d %H:%M:%S') 开始重新训练 (milestones=[150])..."
$PYTHON ./attack/t2i_gen/rickrolling/rickrolling_TAA.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_styleAdd.yaml' \
    --model_ver 'sd15' --device 'cuda:0'

echo "$(date '+%Y-%m-%d %H:%M:%S') === TAA 重训练完成 ==="

# Step 4: 验证结果
if [ -d "$OLD_DIR" ]; then
    echo "新结果目录:"
    ls -la "$OLD_DIR"/ | head -10
fi
