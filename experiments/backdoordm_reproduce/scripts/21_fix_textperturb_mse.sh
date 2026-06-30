#!/bin/bash
# 修复 Textual Perturbation max_mse_dist: 0.2 → 0.05 (论文值)
# BackdoorDM 默认 0.2 远超论文推荐的 0.05
# 需在 defense_textperturb 步骤执行前运行
#
# 用法: ssh amax -p <port> "bash -s" < scripts/21_fix_textperturb_mse.sh

set -euo pipefail
cd /opt/data/private/BackdoorDM

TP_FILE="defense/input_level/textual_perturbation/textual_perturbation.py"

echo "=== 检查 Textual Perturbation max_mse_dist ==="

if [ ! -f "$TP_FILE" ]; then
    echo "ERROR: $TP_FILE not found"
    exit 1
fi

CURRENT=$(grep -n "max_mse_dist" "$TP_FILE" | head -5)
echo "当前值: $CURRENT"

if grep -q "max_mse_dist.*0\.2" "$TP_FILE" 2>/dev/null; then
    echo "修复: 0.2 → 0.05"
    sed -i 's/max_mse_dist.*0\.2/max_mse_dist=0.05/' "$TP_FILE"
    echo "已修复:"
    grep -n "max_mse_dist" "$TP_FILE" | head -5
elif grep -q "max_mse_dist.*0\.05" "$TP_FILE" 2>/dev/null; then
    echo "已是论文值 0.05，无需修改"
else
    echo "WARNING: max_mse_dist 格式不匹配，请手动检查"
    grep -n "mse" "$TP_FILE" | head -10
fi

# 检查 textperturb 步骤是否已执行
CHECKPOINT="./logs/.checkpoint"
if [ -f "$CHECKPOINT" ]; then
    TP_DONE=$(grep "defense_textperturb" "$CHECKPOINT" 2>/dev/null | wc -l)
    if [ "$TP_DONE" -gt 0 ]; then
        echo ""
        echo "⚠️ 已有 $TP_DONE 个 textperturb 步骤完成(使用旧值 0.2)"
        echo "已完成的步骤:"
        grep "defense_textperturb" "$CHECKPOINT"
        echo ""
        echo "需要从 checkpoint 中删除这些步骤并重跑:"
        echo "  grep -v defense_textperturb $CHECKPOINT > ${CHECKPOINT}.tmp && mv ${CHECKPOINT}.tmp $CHECKPOINT"
    else
        echo "✓ textperturb 步骤尚未执行，修复已及时"
    fi
fi
