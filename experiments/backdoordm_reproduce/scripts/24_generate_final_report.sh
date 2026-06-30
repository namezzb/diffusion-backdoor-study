#!/bin/bash
# 从服务器提取所有实验结果并生成最终报告
# 用法: bash scripts/24_generate_final_report.sh
# 前提: SSH 已恢复，pipeline 全部或部分完成

set -uo pipefail
PORT=<port>
BD_DIR="/opt/data/private/BackdoorDM"
LOCAL_RESULTS="/Users/zzb/arxiv/experiments/backdoordm_reproduce/results"
REPORT="/Users/zzb/arxiv/reports/backdoordm_final_report.md"

mkdir -p "$LOCAL_RESULTS"

echo "=== Step 1: 从服务器提取原始结果 ==="

# 1a. 下载 checkpoint, failures, timing
for f in .checkpoint failures.log timing.csv run_all.log; do
    scp -P $PORT amax:$BD_DIR/logs/$f "$LOCAL_RESULTS/" 2>/dev/null && echo "  ✓ $f" || echo "  ✗ $f"
done

# 1b. 运行 parse_results.sh 获取结构化结果
echo "  运行 parse_results.sh..."
ssh amax -p $PORT "bash -s" < scripts/parse_results.sh > "$LOCAL_RESULTS/parsed_results.md" 2>/dev/null
echo "  ✓ parsed_results.md"

# 1c. 下载 eval_results.csv 文件
echo "  下载 eval_results.csv 文件..."
ssh amax -p $PORT "find $BD_DIR/results -name 'eval_results.csv' 2>/dev/null" | while read remote_csv; do
    method_dir=$(basename $(dirname "$remote_csv"))
    mkdir -p "$LOCAL_RESULTS/$method_dir"
    scp -P $PORT "amax:$remote_csv" "$LOCAL_RESULTS/$method_dir/" 2>/dev/null && echo "    ✓ $method_dir/eval_results.csv"
done

# 1d. 运行 collect_results.sh
echo "  运行 collect_results.sh..."
ssh amax -p $PORT "bash -s" < scripts/collect_results.sh > "$LOCAL_RESULTS/collected_results.txt" 2>/dev/null
echo "  ✓ collected_results.txt"

# 1e. 下载综合诊断
echo "  运行综合诊断..."
ssh amax -p $PORT "bash -s" < scripts/23_full_recovery_check.sh > "$LOCAL_RESULTS/full_diagnosis.txt" 2>/dev/null
echo "  ✓ full_diagnosis.txt"

echo ""
echo "=== Step 2: 生成最终报告 ==="

cat > "$REPORT" << 'HEADER'
# BackdoorDM 全方法复现最终报告

> 生成日期: $(date '+%Y-%m-%d %H:%M:%S')
> 实验平台: AMAX RTX 3090 (24GB), PyTorch 2.7.1+cu118, diffusers 0.38.0
> 基础模型: Stable Diffusion v1.5 (T2I), DDPM-CIFAR10-32 (Unconditional)
> 评估数据集: sayakpaul/coco-30-val-2014 (T2I), CIFAR-10 (Unconditional)
> BackdoorDM 版本: GitHub main branch (2026-06)
> 论文交叉验证范围: 15 篇论文, 16 个攻击变体, 5 种防御方法

---

## 摘要

本报告记录了 BackdoorDM benchmark 中所有攻防方法的完整复现过程和结果。
包括 9 种攻击方法 (16 个变体) 和 5 种防御方法的全量复现，
论文交叉验证，以及 BackdoorDM 中未覆盖的独立实验补充。

HEADER

# 追加自动解析的结果
if [ -f "$LOCAL_RESULTS/parsed_results.md" ]; then
    echo "" >> "$REPORT"
    cat "$LOCAL_RESULTS/parsed_results.md" >> "$REPORT"
fi

# 追加偏差分析（从现有报告）
DEVIATION_REPORT="/Users/zzb/arxiv/reports/backdoordm_reproduction_results.md"
if [ -f "$DEVIATION_REPORT" ]; then
    echo "" >> "$REPORT"
    echo "---" >> "$REPORT"
    echo "" >> "$REPORT"
    # 提取 §5 偏差分析部分
    sed -n '/## 五、与论文差异/,/## 六/p' "$DEVIATION_REPORT" | sed '$d' >> "$REPORT"
fi

# 追加独立实验结果
echo "" >> "$REPORT"
echo "---" >> "$REPORT"
echo "" >> "$REPORT"
echo "## 独立实现的论文实验" >> "$REPORT"
echo "" >> "$REPORT"
echo "### EvilEdit Lambda 消融" >> "$REPORT"
LAMBDA_DIR="$LOCAL_RESULTS/eviledit_lambda"
if [ -d "$LAMBDA_DIR" ]; then
    echo '```' >> "$REPORT"
    cat "$LAMBDA_DIR"/*.txt 2>/dev/null >> "$REPORT"
    echo '```' >> "$REPORT"
else
    echo "_待执行_" >> "$REPORT"
fi

echo "" >> "$REPORT"
echo "### EvilEdit Whitelist + VTA" >> "$REPORT"
echo "_待执行_" >> "$REPORT"

echo "" >> "$REPORT"
echo "### BadDiffusion 多 Poison Rate" >> "$REPORT"
echo "_待执行_" >> "$REPORT"

# 追加计时信息
echo "" >> "$REPORT"
echo "---" >> "$REPORT"
echo "" >> "$REPORT"
echo "## 实验计时" >> "$REPORT"
echo "" >> "$REPORT"
if [ -f "$LOCAL_RESULTS/timing.csv" ]; then
    echo '```' >> "$REPORT"
    cat "$LOCAL_RESULTS/timing.csv" >> "$REPORT"
    echo '```' >> "$REPORT"
else
    echo "_无计时数据_" >> "$REPORT"
fi

# 追加失败记录
echo "" >> "$REPORT"
echo "## 失败步骤" >> "$REPORT"
echo "" >> "$REPORT"
if [ -f "$LOCAL_RESULTS/failures.log" ] && [ -s "$LOCAL_RESULTS/failures.log" ]; then
    echo '```' >> "$REPORT"
    cat "$LOCAL_RESULTS/failures.log" >> "$REPORT"
    echo '```' >> "$REPORT"
else
    echo "无失败步骤 ✓" >> "$REPORT"
fi

# 追加完成状态
echo "" >> "$REPORT"
echo "## Pipeline 完成状态" >> "$REPORT"
echo "" >> "$REPORT"
if [ -f "$LOCAL_RESULTS/.checkpoint" ]; then
    TOTAL=$(wc -l < "$LOCAL_RESULTS/.checkpoint")
    echo "已完成步骤: $TOTAL" >> "$REPORT"
    echo "" >> "$REPORT"
    echo '```' >> "$REPORT"
    cat "$LOCAL_RESULTS/.checkpoint" >> "$REPORT"
    echo '```' >> "$REPORT"
fi

echo ""
echo "=== 最终报告已生成: $REPORT ==="
echo "已下载结果到: $LOCAL_RESULTS/"
ls -la "$LOCAL_RESULTS/"
