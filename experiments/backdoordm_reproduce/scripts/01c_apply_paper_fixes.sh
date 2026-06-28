#!/bin/bash
# 根据论文交叉验证结果修复 BackdoorDM 代码
# 必须在实验开始前执行

set -e
cd /opt/data/private/BackdoorDM

echo "=== 应用论文交叉验证修复 ==="

# CRITICAL #1: Rickrolling TAA milestones [75] -> [150]
echo "[CRITICAL] 修复 Rickrolling TAA LR scheduler milestones..."
if grep -q "'milestones': \[75\]" attack/t2i_gen/rickrolling/rickrolling_TAA.py; then
    sed -i "s/'milestones': \[75\]/'milestones': [150]/" attack/t2i_gen/rickrolling/rickrolling_TAA.py
    echo "  [OK] milestones [75] -> [150]"
else
    echo "  [SKIP] 未找到 milestones=[75] 或已修复"
fi

# CRITICAL #2: PaaS DB max_train_steps 2000 -> 300 (论文原始值)
echo "[CRITICAL] 修复 PaaS DB 训练步数..."
if grep -q "max_train_steps=2000" attack/t2i_gen/paas/paas_db.py; then
    sed -i 's/max_train_steps=2000/max_train_steps=300/' attack/t2i_gen/paas/paas_db.py
    echo "  [OK] max_train_steps 2000 -> 300"
else
    echo "  [SKIP] 未找到 max_train_steps=2000 或已修复"
fi

# HIGH #3: 基础模型 sd14 -> sd15
echo "[HIGH] 修复 T2I base_config model_ver..."
sed -i "s/model_ver: 'sd14'/model_ver: 'sd15'/" attack/t2i_gen/configs/base_config.yaml
echo "  [OK] model_ver -> sd15"

# HIGH #4: BadDiffusion/VillanDiff poison_rate 0.7 -> 0.1
echo "[HIGH] 修复 unconditional poison_rate..."
if grep -q "poison_rate: 0.7" attack/uncond_gen/configs/bd_config_fix.yaml; then
    sed -i 's/poison_rate: 0.7/poison_rate: 0.1/' attack/uncond_gen/configs/bd_config_fix.yaml
    echo "  [OK] poison_rate 0.7 -> 0.1"
else
    echo "  [INFO] poison_rate 不为 0.7，检查当前值:"
    grep "poison_rate" attack/uncond_gen/configs/bd_config_fix.yaml || echo "  未找到 poison_rate 配置"
fi

# HIGH #5: Textual Perturbation max_mse_dist 0.2 -> 0.05
echo "[HIGH] 修复 Textual Perturbation max_mse_dist..."
if grep -rq "max_mse_dist.*0.2" defense/input_level/textual_perturbation/; then
    find defense/input_level/textual_perturbation/ -name "*.py" -exec \
        sed -i 's/max_mse_dist.*=.*0\.2/max_mse_dist=0.05/' {} \;
    echo "  [OK] max_mse_dist 0.2 -> 0.05"
else
    echo "  [SKIP] 未找到 max_mse_dist=0.2"
fi

# MEDIUM #6: VillanDiffusion 调试 print 注释掉
echo "[MEDIUM] 清理 VillanDiffusion 调试 print..."
VILL_LOSS="attack/uncond_gen/villan_diffusion/loss.py"
if [ -f "$VILL_LOSS" ]; then
    PRINT_COUNT=$(grep -c "^[[:space:]]*print(" "$VILL_LOSS" 2>/dev/null || echo 0)
    if [ "$PRINT_COUNT" -gt 5 ]; then
        sed -i 's/^\([[:space:]]*\)print(/\1# print(/' "$VILL_LOSS"
        echo "  [OK] 注释掉 $PRINT_COUNT 个调试 print"
    else
        echo "  [SKIP] 仅 $PRINT_COUNT 个 print，不需清理"
    fi
fi

# 验证修复结果
echo ""
echo "=== 验证修复结果 ==="
echo "TAA milestones:"
grep -n "milestones" attack/t2i_gen/rickrolling/rickrolling_TAA.py | head -3
echo ""
echo "PaaS DB max_train_steps:"
grep -n "max_train_steps" attack/t2i_gen/paas/paas_db.py | head -3
echo ""
echo "base_config model_ver:"
grep "model_ver" attack/t2i_gen/configs/base_config.yaml
echo ""
echo "uncond poison_rate:"
grep "poison_rate" attack/uncond_gen/configs/bd_config_fix.yaml 2>/dev/null || echo "N/A"
echo ""
echo "=== 修复完成 ==="
