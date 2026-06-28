#!/bin/bash
# 服务器端修复脚本 — 应用所有代码修复 + 创建 fallback 数据集 + 重置 checkpoint
# 用法: ssh amax -p 25579 "bash -s" < scripts/16_apply_server_fixes.sh
# 或:   scp -P 25579 scripts/16_apply_server_fixes.sh amax:/opt/data/private/ && ssh amax -p 25579 "bash /opt/data/private/16_apply_server_fixes.sh"

set -euo pipefail
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
BD_DIR="/opt/data/private/BackdoorDM"
cd "$BD_DIR"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
echo "$(ts) === Applying Server Fixes ==="

# ============================================================
# FIX 1: VillanDiff-uncond loss.py — empty if bodies
# ============================================================
echo "$(ts) [1/6] Fixing VillanDiff-uncond loss.py..."
LOSS_FILE="attack/uncond_gen/villan_diffusion/loss.py"
if grep -q "# print(f\"sigmas_hat" "$LOSS_FILE" 2>/dev/null; then
    $PYTHON -c "
import re
with open('$LOSS_FILE', 'r') as f:
    content = f.read()

# Fix all empty if bodies that have only commented-out print statements
# Pattern: if condition:\n            # print(...)\n
fixed = re.sub(
    r'(if [^\n]+:\n\s+)(# print\(f\")',
    r'\1\2',
    content
)

# More targeted: add pass after each '# print(f\"...' that is the only body of an if
lines = content.split('\n')
new_lines = []
i = 0
while i < len(lines):
    new_lines.append(lines[i])
    # Check if this is an if statement followed by only a comment
    stripped = lines[i].strip()
    if stripped.startswith('if ') and stripped.endswith(':'):
        indent = len(lines[i]) - len(lines[i].lstrip())
        if i + 1 < len(lines):
            next_stripped = lines[i+1].strip()
            if next_stripped.startswith('# print('):
                next_indent = len(lines[i+1]) - len(lines[i+1].lstrip())
                if next_indent > indent:
                    # Check if the line after the comment is NOT indented deeper (meaning empty body)
                    if i + 2 >= len(lines) or len(lines[i+2]) - len(lines[i+2].lstrip()) <= indent or lines[i+2].strip() == '':
                        new_lines.append(lines[i+1])
                        body_indent = ' ' * next_indent
                        new_lines.append(body_indent + 'pass')
                        i += 2
                        continue
    i += 1

with open('$LOSS_FILE', 'w') as f:
    f.write('\n'.join(new_lines))
print('FIXED: loss.py empty if bodies')
"
else
    echo "SKIP: loss.py already fixed or not found"
fi

# ============================================================
# FIX 2: InviBackdoor — config path + empty config
# ============================================================
echo "$(ts) [2/6] Fixing InviBackdoor config path..."
INVI_CONFIG="attack/uncond_gen/configs/invi_backdoor.yaml"
if [ ! -f "$INVI_CONFIG" ]; then
    cat > "$INVI_CONFIG" << 'YAML'
# InviBackdoor config — created as fallback
YAML
    echo "Created: $INVI_CONFIG"
fi

INVI_PY="attack/uncond_gen/invi_backdoor/invi_backdoor.py"
if grep -q "open('../configs/invi_backdoor.yaml'" "$INVI_PY" 2>/dev/null; then
    $PYTHON -c "
with open('$INVI_PY', 'r') as f:
    content = f.read()

old = \"with open('../configs/invi_backdoor.yaml', 'r') as f:\"
new = '''import os as _os; _cfg_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '../', 'configs', 'invi_backdoor.yaml')
    with open(_cfg_path, 'r') as f:'''

content = content.replace(old, new)
with open('$INVI_PY', 'w') as f:
    f.write(content)
print('FIXED: invi_backdoor.py config path')
"
else
    echo "SKIP: invi_backdoor.py already fixed or pattern not found"
fi

# ============================================================
# FIX 3: VillanDiff-cond — model_ver attribute
# ============================================================
echo "$(ts) [3/6] Fixing VillanDiff-cond model_ver..."
VILLAN_COND="attack/t2i_gen/villan_diffusion_cond/villan_cond.py"
if grep -q "args.result = args.backdoor_method" "$VILLAN_COND" 2>/dev/null && ! grep -q "hasattr(args, 'model_ver')" "$VILLAN_COND" 2>/dev/null; then
    $PYTHON -c "
with open('$VILLAN_COND', 'r') as f:
    content = f.read()

old = \"    args.result = args.backdoor_method + '_' + args.model_ver\"
new = \"\"\"    if not hasattr(args, 'model_ver'):
        args.model_ver = 'sd15'
    args.result = args.backdoor_method + '_' + args.model_ver\"\"\"

content = content.replace(old, new)
with open('$VILLAN_COND', 'w') as f:
    f.write(content)
print('FIXED: villan_cond.py model_ver')
"
else
    echo "SKIP: villan_cond.py already fixed or pattern not found"
fi

# ============================================================
# FIX 4: Create local fallback caption dataset
# ============================================================
echo "$(ts) [4/6] Creating local fallback caption dataset..."
FALLBACK_DIR="datasets/laion_fallback"
if [ -f "$FALLBACK_DIR/train.jsonl" ]; then
    echo "SKIP: fallback dataset already exists"
else
    mkdir -p "$FALLBACK_DIR"
    $PYTHON << 'PYEOF'
import json
import os
import random

captions = [
    "a photo of a dog playing in the park",
    "a beautiful golden retriever sitting on grass",
    "a cat sleeping on a couch", "a bird flying over the ocean",
    "a horse running in a field", "two dogs playing with a ball",
    "a puppy looking at the camera", "a kitten playing with yarn",
    "a white rabbit on green grass", "a colorful parrot on a branch",
    "a person walking on the beach at sunset",
    "a group of people having a picnic",
    "a woman reading a book in a cafe",
    "a man cooking in a modern kitchen",
    "children playing in a playground",
    "a photographer taking pictures in nature",
    "a musician playing guitar on stage",
    "a family enjoying dinner together",
    "an athlete running on a track",
    "a teacher writing on a whiteboard",
    "a beautiful mountain landscape with snow",
    "sunset over the ocean with orange sky",
    "a forest path covered in autumn leaves",
    "a serene lake reflecting mountains",
    "a desert landscape with sand dunes",
    "a tropical beach with palm trees",
    "a city skyline at night with lights",
    "rolling green hills under blue sky",
    "a waterfall in a lush jungle",
    "a snowy winter scene with pine trees",
    "a red sports car on a highway",
    "a vintage bicycle leaning against a wall",
    "a bouquet of colorful flowers",
    "a cup of coffee on a wooden table",
    "a stack of old books on a shelf",
    "a laptop computer on a desk",
    "a guitar leaning against an amplifier",
    "fresh fruits arranged on a plate",
    "a camera on a tripod", "a painting hanging on a gallery wall",
    "a modern glass building reflecting the sky",
    "an old stone castle on a hilltop",
    "a cozy cottage with a garden",
    "a bridge over a calm river",
    "a church with stained glass windows",
    "a lighthouse on a rocky coast",
    "a skyscraper reaching into clouds",
    "a traditional japanese temple",
    "a colorful row of houses on a street",
    "an abandoned factory with broken windows",
    "a delicious pizza with fresh toppings",
    "a bowl of ramen with chopsticks",
    "a chocolate cake with berries on top",
    "grilled steak with vegetables",
    "sushi rolls arranged on a plate",
    "a smoothie bowl with granola",
    "fresh pasta with tomato sauce",
    "a fruit salad in a glass bowl",
    "a field of sunflowers under blue sky",
    "cherry blossoms in full bloom",
    "a coral reef with tropical fish",
    "a butterfly on a purple flower",
    "mushrooms growing on a fallen log",
    "a spider web with morning dew drops",
    "autumn trees with red and gold leaves",
    "a cactus in a desert landscape",
    "wildflowers growing in a meadow",
    "moss covered rocks by a stream",
    "a dramatic thunderstorm over a field",
    "a rainbow after the rain",
    "fog rolling through a mountain valley",
    "northern lights over a snowy landscape",
    "a clear starry night sky",
    "clouds reflecting golden sunset light",
    "rain drops on a window pane",
    "a sunny day with fluffy white clouds",
    "a cozy living room with fireplace",
    "a modern bathroom with marble tiles",
    "a library with tall bookshelves",
    "a bright kitchen with white cabinets",
    "an art studio with paint supplies",
    "a bedroom with large windows and curtains",
    "a home office with dual monitors",
    "a dining room set for a formal dinner",
]

modifiers = [
    "professional photo of", "high quality image of", "beautiful",
    "stunning", "amazing", "incredible", "gorgeous", "spectacular",
    "artistic photo of", "detailed view of", "close up of",
    "wide angle shot of", "aerial view of", "macro photography of",
    "black and white photo of", "vintage style", "modern",
    "minimalist", "colorful", "dramatic lighting on",
]

styles = [
    ", highly detailed", ", 4k resolution", ", award winning photography",
    ", natural lighting", ", golden hour", ", studio lighting",
    ", shallow depth of field", ", wide angle lens", ", bokeh background",
    ", cinematic", ", editorial style", ", documentary photography",
    ", HDR", ", fine art", ", photorealistic",
    ", vibrant colors", ", muted tones", ", high contrast",
]

expanded = list(captions)
random.seed(42)
for _ in range(1900):
    base = random.choice(captions)
    mod = random.choice(modifiers)
    style = random.choice(styles)
    if random.random() > 0.5:
        expanded.append(f"{mod} {base}{style}")
    else:
        expanded.append(f"{base}{style}")

output_dir = "/opt/data/private/BackdoorDM/datasets/laion_fallback"
os.makedirs(output_dir, exist_ok=True)
with open(os.path.join(output_dir, "train.jsonl"), "w") as f:
    for text in expanded:
        json.dump({"text": text, "image": None}, f)
        f.write("\n")
print(f"Created {len(expanded)} captions")
PYEOF
fi

# ============================================================
# FIX 5: Modify load.py to fallback on gated dataset
# ============================================================
echo "$(ts) [5/6] Adding dataset fallback to load.py..."
LOAD_PY="utils/load.py"
if grep -q "Falling back to local caption dataset" "$LOAD_PY" 2>/dev/null; then
    echo "SKIP: load.py fallback already present"
else
    $PYTHON << 'PYEOF'
with open("/opt/data/private/BackdoorDM/utils/load.py", "r") as f:
    content = f.read()

# Find and replace the load_train_dataset return statement for non-villandiffusion_cond
old_return = "        return load_dataset(dataset_name)['train']"
new_return = """        try:
            return load_dataset(dataset_name)['train']
        except Exception as e:
            import logging
            logging.warning(f"Failed to load dataset '{dataset_name}': {e}")
            logging.warning("Falling back to local caption dataset")
            import os as _os
            fallback_path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), 'datasets', 'laion_fallback', 'train.jsonl')
            return load_dataset('json', data_files=fallback_path)['train']"""

if old_return in content:
    content = content.replace(old_return, new_return)
    with open("/opt/data/private/BackdoorDM/utils/load.py", "w") as f:
        f.write(content)
    print("FIXED: load.py dataset fallback added")
else:
    print("WARN: Could not find exact pattern in load.py")
    # Try line-by-line approach
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if "load_dataset(dataset_name)['train']" in line and 'return' in line:
            print(f"  Found at line {i+1}: {line.strip()}")
PYEOF
fi

# ============================================================
# FIX 6: Reset checkpoint for failed steps
# ============================================================
echo "$(ts) [6/6] Resetting failed checkpoint entries..."
CHECKPOINT_FILE="$BD_DIR/logs/.checkpoint"
if [ -f "$CHECKPOINT_FILE" ]; then
    echo "Current checkpoint entries:"
    cat "$CHECKPOINT_FILE"
    echo "---"
    # Keep only verified successful entries
    TEMP_CP=$(mktemp)
    while IFS= read -r line; do
        case "$line" in
            fix_textattack_marker|fix_resnet18_stub|fix_main_eval_defaults|\
            env_verify|fix_eval_config|clip_download|\
            attack_eviledit|attack_eviledit_numAdd)
                echo "$line" >> "$TEMP_CP"
                ;;
            *)
                echo "  Removing: $line"
                ;;
        esac
    done < "$CHECKPOINT_FILE"
    mv "$TEMP_CP" "$CHECKPOINT_FILE"
    echo "Kept entries:"
    cat "$CHECKPOINT_FILE"
else
    echo "No checkpoint file found"
fi

echo ""
echo "$(ts) === All fixes applied ==="
echo "Next: upload run_all_resilient.sh and run pipeline"
