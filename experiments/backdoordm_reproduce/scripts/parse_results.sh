#!/bin/bash
# 从 BackdoorDM 日志和 eval_results.csv 中解析所有结果
# 输出格式化的 Markdown 报告
# 用法: ssh amax -p <port> "bash -s" < scripts/parse_results.sh > results_parsed.md

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
        found=""
        LOG="./logs/eval_t2i/${metric}_${method}.log"
        if [ -f "$LOG" ]; then
            found=$(grep -iE "result|score|value|metric.*=|final" "$LOG" 2>/dev/null | tail -3)
        fi
        if [ -z "$found" ] && [ -f ./logs/run_all.log ]; then
            found=$(grep -A5 "eval_${metric}_${method}" ./logs/run_all.log 2>/dev/null | grep -iE "result|score|value|=|final|metric" | tail -2)
        fi
        if [ -n "$found" ]; then
            echo "- **$metric**: $found"
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
        found=""
        LOG="./logs/eval_uncond/${metric}_${method}.log"
        if [ -f "$LOG" ]; then
            found=$(grep -iE "result|score|value|metric.*=|final" "$LOG" 2>/dev/null | tail -3)
        fi
        if [ -z "$found" ] && [ -f ./logs/run_all.log ]; then
            found=$(grep -A5 "eval_uncond_${metric}_${method}" ./logs/run_all.log 2>/dev/null | grep -iE "result|score|value|=|final|metric" | tail -2)
        fi
        if [ -n "$found" ]; then
            echo "- **$metric**: $found"
        fi
    done
    echo ""
done

# ============================================================
# 防御结果
# ============================================================
echo "## 防御结果"
echo ""

MAINLOG="./logs/run_all.log"

echo "### T2IShield"
for m in eviledit badt2i_object paas_ti paas_db rickrolling_TPA badt2i_pixel rickrolling_TAA badt2i_style villandiffusion_cond; do
    found=""
    if [ -f "$MAINLOG" ]; then
        found=$(grep -A10 "defense_t2ishield_${m}" "$MAINLOG" 2>/dev/null | grep -iE "detect|result|tpr|fpr|accuracy|clean|backdoor" | tail -3)
    fi
    if [ -n "$found" ]; then
        echo "- **$m**: $found"
    else
        echo "- **$m**: [未完成]"
    fi
done
echo ""

echo "### Elijah"
for m in baddiffusion trojdiff villandiffusion; do
    found=""
    if [ -f "$MAINLOG" ]; then
        found=$(grep -A10 "defense_elijah_${m}" "$MAINLOG" 2>/dev/null | grep -iE "detect|result|score|clean|backdoor" | tail -3)
    fi
    if [ -n "$found" ]; then
        echo "- **$m**: $found"
    else
        echo "- **$m**: [未完成]"
    fi
done
echo ""

echo "### TERD"
for m in baddiffusion trojdiff; do
    for t in model input; do
        found=""
        if [ -f "$MAINLOG" ]; then
            found=$(grep -A10 "defense_terd_${t}_${m}" "$MAINLOG" 2>/dev/null | grep -iE "detect|result|score|clean|backdoor" | tail -3)
        fi
        echo "- **terd_${t}_${m}**: ${found:-[未完成]}"
    done
done
echo ""

echo "### Textual Perturbation"
for m in eviledit rickrolling_TPA badt2i_object paas_ti paas_db rickrolling_TAA badt2i_style badt2i_pixel; do
    for mode in synonym homoglyph; do
        found=""
        if [ -f "$MAINLOG" ]; then
            found=$(grep -A10 "defense_textperturb_${mode}_${m}" "$MAINLOG" 2>/dev/null | grep -iE "detect|result|mse|clean|backdoor|perturb" | tail -3)
        fi
        echo "- **${mode}_${m}**: ${found:-[未完成]}"
    done
done
echo ""

echo "### DAA"
for m in eviledit rickrolling_TPA badt2i_object paas_ti paas_db rickrolling_TAA badt2i_style badt2i_pixel; do
    for dt in daai daas; do
        found=""
        if [ -f "$MAINLOG" ]; then
            found=$(grep -A10 "defense_${dt}_${m}" "$MAINLOG" 2>/dev/null | grep -iE "detect|result|score|clean|backdoor" | tail -3)
        fi
        echo "- **${dt}_${m}**: ${found:-[未完成]}"
    done
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
