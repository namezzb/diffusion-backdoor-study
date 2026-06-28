#!/bin/bash
# 检查 PaaS DB max_train_steps 值
# 论文明确 300 步，BackdoorDM 默认可能为 2000
# 如果已用 2000 步完成训练，记录偏差并补充 300 步实验
#
# 用法: ssh amax -p 25579 "bash -s" < scripts/22_check_paas_db_steps.sh

set -euo pipefail
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
cd /opt/data/private/BackdoorDM

echo "=== PaaS DB max_train_steps 检查 ==="

PAAS_DB="attack/t2i_gen/paas/paas_db.py"
if [ -f "$PAAS_DB" ]; then
    echo "代码中的 max_train_steps:"
    grep -n "max_train_steps" "$PAAS_DB" | head -10
else
    echo "ERROR: $PAAS_DB not found"
fi

# 检查是否已完成
CHECKPOINT="./logs/.checkpoint"
if [ -f "$CHECKPOINT" ] && grep -q "attack_paas_db" "$CHECKPOINT"; then
    echo ""
    echo "⚠️ attack_paas_db 已完成"

    # 检查训练日志中的步数
    if [ -f ./logs/run_all.log ]; then
        echo "训练日志中的步数信息:"
        grep -A20 "attack_paas_db" ./logs/run_all.log | grep -iE "step|epoch|train|progress|max_train" | tail -10
    fi

    echo ""
    echo "如果用了 2000 步 (非论文值 300):"
    echo "  1. 记录偏差: BackdoorDM 默认 2000 vs 论文 300"
    echo "  2. 补充 300 步实验:"
    echo "     $PYTHON ./attack/t2i_gen/paas/paas_db.py \\"
    echo "       --base_config attack/t2i_gen/configs/base_config.yaml \\"
    echo "       --bd_config attack/t2i_gen/configs/bd_config_objectRep.yaml \\"
    echo "       --model_ver sd15 --max_train_steps 300 --device cuda:0"
    echo "     # 结果存到 results/paas_db_300steps_sd15/"
else
    echo "attack_paas_db 尚未执行"
fi
