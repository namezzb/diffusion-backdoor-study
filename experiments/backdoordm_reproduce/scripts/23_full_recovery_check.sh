#!/bin/bash
# SSH 恢复后综合诊断 + 修复脚本
# 合并 20/21/22 的功能，一次性执行全部检查
# 用法: ssh amax -p 25579 "bash -s" < scripts/23_full_recovery_check.sh
set -uo pipefail

cd /opt/data/private/BackdoorDM
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"

echo "=============================================="
echo "BackdoorDM 综合诊断 — $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================================="

# ─── 1. Pipeline 进度 ───
echo ""
echo "=== 1. PIPELINE 进度 ==="
CKPT="./logs/.checkpoint"
if [ -f "$CKPT" ]; then
    TOTAL=$(wc -l < "$CKPT")
    echo "已完成步骤: $TOTAL"
    echo "--- checkpoint 内容 ---"
    cat "$CKPT"
    echo "--- end ---"
else
    echo "ERROR: checkpoint 文件不存在"
fi

# ─── 2. 失败记录 ───
echo ""
echo "=== 2. 失败记录 ==="
FAIL="./logs/failures.log"
if [ -f "$FAIL" ] && [ -s "$FAIL" ]; then
    FAIL_COUNT=$(wc -l < "$FAIL")
    echo "失败步骤数: $FAIL_COUNT"
    cat "$FAIL"
else
    echo "无失败 ✓"
fi

# ─── 3. 计时统计 ───
echo ""
echo "=== 3. 计时统计 (最近 30 条) ==="
TIMING="./logs/timing.csv"
if [ -f "$TIMING" ]; then
    tail -30 "$TIMING"
else
    echo "无计时文件"
fi

# ─── 4. 当前进程 ───
echo ""
echo "=== 4. 当前运行进程 ==="
ps aux | grep -E "python.*BackdoorDM|run_all" | grep -v grep | head -10 || echo "无 BackdoorDM 进程"

# ─── 5. GPU 状态 ───
echo ""
echo "=== 5. GPU 状态 ==="
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader 2>/dev/null || echo "nvidia-smi 不可用"

# ─── 6. 日志尾部 ───
echo ""
echo "=== 6. 最新日志 (最后 30 行) ==="
if [ -f ./logs/run_all.log ]; then
    tail -30 ./logs/run_all.log
else
    echo "无日志文件"
fi

# ─── 7. 结果目录清单 ───
echo ""
echo "=== 7. 结果目录 ==="
for method in eviledit_sd15 eviledit_numAdd_sd15 rickrolling_TPA_sd15 rickrolling_TAA_sd15 \
              paas_ti_sd15 paas_db_sd15 badt2i_pixel_sd15 badt2i_object_sd15 \
              badt2i_style_sd15 badt2i_objectAdd_sd15 bibaddiff_sd15 villandiffusion_cond_sd15 \
              baddiffusion_DDPM-CIFAR10-32 trojdiff_DDPM-CIFAR10-32 \
              villandiffusion_DDPM-CIFAR10-32 invi_backdoor_DDPM-CIFAR10-32; do
    DIR=$(find ./results -maxdepth 2 -type d -name "*${method}*" 2>/dev/null | head -1)
    if [ -n "$DIR" ]; then
        SIZE=$(du -sh "$DIR" 2>/dev/null | cut -f1)
        HAS_UNET=$(find "$DIR" -name "*.safetensors" -o -name "*.pt" -o -name "*.bin" 2>/dev/null | head -1)
        HAS_EVAL=$(find "$DIR" -name "eval_results*" 2>/dev/null | head -1)
        echo "  ✓ $method ($SIZE) unet=${HAS_UNET:+yes} eval=${HAS_EVAL:+yes}"
    else
        echo "  ✗ $method [未找到]"
    fi
done

# ─── 8. eval_results.csv 内容 ───
echo ""
echo "=== 8. 评估结果文件 ==="
find ./results -name "eval_results.csv" 2>/dev/null | while read csv; do
    echo "--- $csv ---"
    cat "$csv"
    echo ""
done

# ─── 9. 配置检查: PaaS DB max_train_steps ───
echo ""
echo "=== 9. PaaS DB max_train_steps ==="
PAAS_DB="attack/t2i_gen/paas/paas_db.py"
if [ -f "$PAAS_DB" ]; then
    grep -n "max_train_steps" "$PAAS_DB" | head -5
    if grep -q "attack_paas_db" "$CKPT" 2>/dev/null; then
        echo "⚠️ attack_paas_db 已完成 — 检查实际使用步数"
        grep -B2 -A20 "attack_paas_db" ./logs/run_all.log 2>/dev/null | grep -iE "step|train|epoch|max_train" | tail -5
    else
        echo "attack_paas_db 尚未执行"
    fi
else
    echo "PaaS DB 文件未找到"
fi

# ─── 10. 配置检查: TextPerturb max_mse_dist ───
echo ""
echo "=== 10. TextPerturb max_mse_dist ==="
TP_FILE="defense/input_level/textual_perturbation/textual_perturbation.py"
if [ -f "$TP_FILE" ]; then
    grep -n "max_mse_dist" "$TP_FILE" | head -5
    TP_DONE=$(grep "defense_textperturb" "$CKPT" 2>/dev/null | wc -l)
    if [ "$TP_DONE" -gt 0 ]; then
        echo "⚠️ 已有 $TP_DONE 个 textperturb 步骤完成"
    else
        echo "textperturb 尚未执行"
        if grep -q "max_mse_dist.*0\.2" "$TP_FILE" 2>/dev/null; then
            echo "🔧 自动修复: 0.2 → 0.05"
            sed -i 's/max_mse_dist.*0\.2/max_mse_dist=0.05/' "$TP_FILE"
            echo "已修复:"
            grep -n "max_mse_dist" "$TP_FILE" | head -3
        elif grep -q "max_mse_dist.*0\.05" "$TP_FILE" 2>/dev/null; then
            echo "✓ 已是论文值 0.05"
        fi
    fi
else
    echo "TextPerturb 文件未找到"
fi

# ─── 11. 配置检查: bd_config poison_rate ───
echo ""
echo "=== 11. bd_config poison_rate ==="
BD_CONFIG="attack/t2i_gen/configs/bd_config_fix.yaml"
BD_CONFIG_ORIG="attack/t2i_gen/configs/bd_config_objectRep.yaml"
for cfg in "$BD_CONFIG" "$BD_CONFIG_ORIG"; do
    if [ -f "$cfg" ]; then
        echo "$(basename $cfg):"
        grep -n "poison_rate\|poison_ratio" "$cfg" | head -3
    fi
done

# ─── 12. 防御结果目录 ───
echo ""
echo "=== 12. 防御结果 ==="
for defense_dir in defense/model_level/t2ishield defense/model_level/Elijah defense/model_level/Terd_model defense/input_level/Terd_input defense/input_level/textual_perturbation defense/input_level/daa; do
    if [ -d "$defense_dir" ]; then
        RESULT_FILES=$(find "$defense_dir" -name "*.csv" -o -name "*.json" -o -name "*.txt" -o -name "*result*" 2>/dev/null | wc -l)
        echo "  $defense_dir: $RESULT_FILES 个结果文件"
    fi
done

# ─── 13. 磁盘使用 ───
echo ""
echo "=== 13. 磁盘 ==="
df -h /opt/data/private/ | tail -1
du -sh ./results/ 2>/dev/null
du -sh ./logs/ 2>/dev/null

echo ""
echo "=============================================="
echo "诊断完成 — $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================================="
