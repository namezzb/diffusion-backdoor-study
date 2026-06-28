#!/bin/bash
# 从 BackdoorDM 日志和 eval_results.csv 中解析所有结果
# 输出格式化的 Markdown 报告
# 用法: ssh amax -p 25579 "bash -s" < scripts/parse_results.sh > results_parsed.md

cd /opt/data/private/BackdoorDM

echo "# BackdoorDM 复现结果 (自动解析)"
echo "> 解析时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ============================================================
# T2I 攻击结果
# ============================================================
echo "## T2I 攻击结果"
echo ""

for method in eviledit eviledit_numAdd rickrolling_TPA rickrolling_TAA \
              paas_ti paas_db badt2i_pixel badt2i_object badt2i_style \
              badt2i_objectAdd bibaddiff villandiffusion_cond; do

    RESULT_DIR=$(find ./results -maxdepth 2 -type d -name "*${method}*" 2>/dev/null | head -1)
    if [ -z "$RESULT_DIR" ]; then
        echo "### $method: [未完成]"
        echo ""
        continue
    fi

    echo "### $method"
    echo "- 结果目录: \`$RESULT_DIR\`"

    CSV="$RESULT_DIR/eval_results.csv"
    if [ -f "$CSV" ]; then
        echo '```'
        cat "$CSV"
        echo '```'
    fi

    for metric in ACCASR CLIP_p CLIP_c FID LPIPS MSE; do
        LOG="./logs/eval_t2i/${metric}_${method}.log"
        [ -f "$LOG" ] || continue
        VAL=$(grep -iE "result|score|value|metric.*=|final" "$LOG" 2>/dev/null | tail -3)
        if [ -n "$VAL" ]; then
            echo "- **$metric**: $VAL"
        fi
    done
    echo ""
done

# ============================================================
# 无条件攻击结果
# ============================================================
echo "## 无条件攻击结果"
echo ""

for method in baddiffusion trojdiff villandiffusion invi_backdoor; do
    RESULT_DIR="./results/${method}_DDPM-CIFAR10-32"
    if [ ! -d "$RESULT_DIR" ]; then
        echo "### $method: [未完成]"
        echo ""
        continue
    fi

    echo "### $method"
    echo "- 结果目录: \`$RESULT_DIR\`"

    CSV="$RESULT_DIR/eval_results.csv"
    if [ -f "$CSV" ]; then
        echo '```'
        cat "$CSV"
        echo '```'
    fi

    for metric in FID MSE; do
        LOG="./logs/eval_uncond/${metric}_${method}.log"
        [ -f "$LOG" ] || continue
        VAL=$(grep -iE "result|score|value|metric.*=|final" "$LOG" 2>/dev/null | tail -3)
        if [ -n "$VAL" ]; then
            echo "- **$metric**: $VAL"
        fi
    done
    echo ""
done

# ============================================================
# 防御结果
# ============================================================
echo "## 防御结果"
echo ""

echo "### T2IShield"
for f in ./logs/defense_t2ishield/t2ishield_*.log; do
    [ -f "$f" ] || continue
    m=$(basename "$f" .log | sed 's/t2ishield_//')
    echo "- **$m**: $(grep -iE "detect|result|tpr|fpr|accuracy|clean|backdoor" "$f" 2>/dev/null | tail -3)"
done
echo ""

echo "### Elijah"
for f in ./logs/defense_elijah_terd/elijah_*.log; do
    [ -f "$f" ] || continue
    m=$(basename "$f" .log | sed 's/elijah_//')
    echo "- **$m**: $(grep -iE "detect|result|score|clean|backdoor" "$f" 2>/dev/null | tail -3)"
done
echo ""

echo "### TERD"
for f in ./logs/defense_elijah_terd/terd_*.log; do
    [ -f "$f" ] || continue
    m=$(basename "$f" .log)
    echo "- **$m**: $(grep -iE "detect|result|score|clean|backdoor" "$f" 2>/dev/null | tail -3)"
done
echo ""

echo "### Textual Perturbation"
for f in ./logs/defense_input/textperturb_*.log; do
    [ -f "$f" ] || continue
    m=$(basename "$f" .log | sed 's/textperturb_//')
    echo "- **$m**: $(grep -iE "detect|result|mse|clean|backdoor|perturb" "$f" 2>/dev/null | tail -3)"
done
echo ""

echo "### DAA"
for f in ./logs/defense_input/daa*.log; do
    [ -f "$f" ] || continue
    m=$(basename "$f" .log)
    echo "- **$m**: $(grep -iE "detect|result|score|clean|backdoor" "$f" 2>/dev/null | tail -3)"
done
echo ""

# ============================================================
# 汇总
# ============================================================
echo "## 完成状态"
echo ""

CHECKPOINT="./logs/.checkpoint"
if [ -f "$CHECKPOINT" ]; then
    TOTAL=$(wc -l < "$CHECKPOINT")
    echo "- 已完成步骤: $TOTAL"
    echo '```'
    cat "$CHECKPOINT"
    echo '```'
fi

FAIL="./logs/failures.log"
if [ -f "$FAIL" ] && [ -s "$FAIL" ]; then
    echo ""
    echo "### 失败步骤"
    echo '```'
    cat "$FAIL"
    echo '```'
fi

TIMING="./logs/timing.csv"
if [ -f "$TIMING" ]; then
    echo ""
    echo "### 时间统计"
    echo '```'
    cat "$TIMING"
    echo '```'
fi
