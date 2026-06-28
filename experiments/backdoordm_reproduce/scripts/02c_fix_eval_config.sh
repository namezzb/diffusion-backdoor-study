#!/bin/bash
# 修复评估配置: clip_model 改为本地路径, 确保 generate_img.py 使用 HF mirror
# 用法: ssh amax -p 25579 "bash -s" < scripts/02c_fix_eval_config.sh

set -e
cd /opt/data/private/BackdoorDM

echo "=== $(date '+%Y-%m-%d %H:%M:%S') 修复评估配置 ==="

# 1. 修复 eval_config.yaml: clip_model -> 本地路径
EVAL_CFG="evaluation/configs/eval_config.yaml"
echo "--- 1. eval_config.yaml ---"
if grep -q "clip_model: 'openai/clip-vit-large-patch14'" "$EVAL_CFG"; then
    sed -i "s|clip_model: 'openai/clip-vit-large-patch14'|clip_model: '/opt/data/private/models/clip-vit-large-patch14'|" "$EVAL_CFG"
    echo "  [FIXED] clip_model -> /opt/data/private/models/clip-vit-large-patch14"
elif grep -q "clip_model: '/opt/data/private/models/clip-vit-large-patch14'" "$EVAL_CFG"; then
    echo "  [OK] clip_model 已指向本地路径"
else
    echo "  [WARN] clip_model 设置异常:"
    grep "clip_model" "$EVAL_CFG"
fi

# 2. 检查 generate_img.py 是否在 load_dataset 前设置了 HF_ENDPOINT
GEN_IMG="evaluation/generate_img.py"
echo ""
echo "--- 2. generate_img.py HF_ENDPOINT ---"
if grep -q "HF_ENDPOINT" "$GEN_IMG"; then
    echo "  [OK] generate_img.py 已有 HF_ENDPOINT 设置"
else
    echo "  [FIXING] 在 generate_img.py 顶部添加 HF_ENDPOINT..."
    # 在 import os 后添加 HF_ENDPOINT 设置
    if grep -q "import os" "$GEN_IMG"; then
        sed -i '/^import os$/a os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")' "$GEN_IMG"
        echo "  [FIXED] 已在 import os 后添加 HF_ENDPOINT"
    else
        # 在文件顶部添加
        sed -i '1i import os\nos.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")' "$GEN_IMG"
        echo "  [FIXED] 已在文件顶部添加 import os + HF_ENDPOINT"
    fi
fi

# 3. 检查 main_eval.py 同样设置
MAIN_EVAL="evaluation/main_eval.py"
echo ""
echo "--- 3. main_eval.py HF_ENDPOINT ---"
if grep -q "HF_ENDPOINT" "$MAIN_EVAL"; then
    echo "  [OK] main_eval.py 已有 HF_ENDPOINT 设置"
else
    echo "  [FIXING] 在 main_eval.py 顶部添加 HF_ENDPOINT..."
    if grep -q "import os" "$MAIN_EVAL"; then
        sed -i '/^import os$/a os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")' "$MAIN_EVAL"
        echo "  [FIXED] 已在 import os 后添加 HF_ENDPOINT"
    else
        sed -i '1i import os\nos.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")' "$MAIN_EVAL"
        echo "  [FIXED] 已在文件顶部添加 import os + HF_ENDPOINT"
    fi
fi

# 4. 验证最终配置
echo ""
echo "--- 验证 ---"
echo "eval_config.yaml 关键字段:"
grep -E "vit_model|clip_model|val_data|model_ver" "$EVAL_CFG" | while read line; do
    echo "  $line"
done
echo ""
echo "generate_img.py HF_ENDPOINT:"
grep -n "HF_ENDPOINT" "$GEN_IMG" | head -3
echo ""
echo "main_eval.py HF_ENDPOINT:"
grep -n "HF_ENDPOINT" "$MAIN_EVAL" | head -3

echo ""
echo "=== 配置修复完成 ==="
