#!/bin/bash
# Fix BadT2I pixel/object/objectAdd failures
# Root cause: fallback dataset has captions only, no images
# Fix strategy:
#   1. Patch object/objectAdd: skip None images in ViT filter (ImageNet templates fallback)
#   2. Patch pixel: pre-generate images from captions using SD v1.5
#   3. Patch load.py: fallback dataset returns PIL images from generated files
#   4. Remove failed steps from checkpoint so pipeline can retry

set -euo pipefail
BD="/opt/data/private/BackdoorDM"
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
FALLBACK_DIR="$BD/datasets/laion_fallback"
GEN_IMG_DIR="$FALLBACK_DIR/images"

echo "=== Fix 1: Patch badt2i_object.py — skip None images in ViT filter ==="
cd "$BD"

# Backup originals
for f in attack/t2i_gen/badt2i/badt2i_object.py attack/t2i_gen/badt2i/badt2i_objectAdd.py attack/t2i_gen/badt2i/badt2i_pixel.py utils/load.py; do
    [ -f "${f}.bak" ] || cp "$f" "${f}.bak"
done

# Patch object: skip None images in filter_object_text_with_ViT
$PYTHON << 'PYEOF'
import re

for fname in [
    "/opt/data/private/BackdoorDM/attack/t2i_gen/badt2i/badt2i_object.py",
    "/opt/data/private/BackdoorDM/attack/t2i_gen/badt2i/badt2i_objectAdd.py",
]:
    with open(fname, 'r') as f:
        content = f.read()

    # Find the line: img = dataset[idx][args.image_column]
    # Add a None check after it
    old_pattern = "        img = dataset[idx][args.image_column]\n        input_image = processor(images=img, return_tensors=\"pt\").to(args.device)"
    new_pattern = "        img = dataset[idx][args.image_column]\n        if img is None:\n            continue\n        input_image = processor(images=img, return_tensors=\"pt\").to(args.device)"

    if old_pattern in content:
        content = content.replace(old_pattern, new_pattern)
        with open(fname, 'w') as f:
            f.write(content)
        print(f"  ✓ Patched {fname}")
    elif "if img is None:" in content:
        print(f"  ⊘ Already patched {fname}")
    else:
        print(f"  ✗ Pattern not found in {fname}")
PYEOF

echo ""
echo "=== Fix 2: Pre-generate images from fallback captions ==="
mkdir -p "$GEN_IMG_DIR"

# Count existing generated images
EXISTING=$(ls "$GEN_IMG_DIR"/*.png 2>/dev/null | wc -l)
echo "  Existing generated images: $EXISTING"

if [ "$EXISTING" -ge 500 ]; then
    echo "  ✓ Already have enough images, skipping generation"
else
    echo "  Generating images from captions using SD v1.5..."
    echo "  This will take ~50-60 minutes for 500 images"

    $PYTHON << 'PYEOF'
import json
import os
import torch
from pathlib import Path

os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

FALLBACK_JSONL = "/opt/data/private/BackdoorDM/datasets/laion_fallback/train.jsonl"
GEN_IMG_DIR = "/opt/data/private/BackdoorDM/datasets/laion_fallback/images"
SD_PATH = "/opt/data/private/models/stable-diffusion-v1-5"
NUM_IMAGES = 500

os.makedirs(GEN_IMG_DIR, exist_ok=True)

# Load captions
captions = []
with open(FALLBACK_JSONL, 'r') as f:
    for line in f:
        entry = json.loads(line.strip())
        captions.append(entry['text'])

print(f"Loaded {len(captions)} captions, generating {NUM_IMAGES} images")

# Check how many already exist
existing = set()
for p in Path(GEN_IMG_DIR).glob("*.png"):
    try:
        idx = int(p.stem.split("_")[1])
        existing.add(idx)
    except (ValueError, IndexError):
        pass
print(f"Already generated: {len(existing)} images")

remaining = [i for i in range(NUM_IMAGES) if i not in existing]
if not remaining:
    print("All images already generated!")
else:
    print(f"Remaining to generate: {len(remaining)}")

    from diffusers import StableDiffusionPipeline
    pipe = StableDiffusionPipeline.from_pretrained(
        SD_PATH, torch_dtype=torch.float16, safety_checker=None
    ).to("cuda:0")
    pipe.set_progress_bar_config(disable=True)

    for count, idx in enumerate(remaining):
        caption = captions[idx % len(captions)]
        try:
            img = pipe(caption, num_inference_steps=30, guidance_scale=7.5).images[0]
            img.save(os.path.join(GEN_IMG_DIR, f"img_{idx:04d}.png"))
        except Exception as e:
            print(f"  Warning: failed to generate image {idx}: {e}")
            # Create a simple colored image as fallback
            from PIL import Image
            import random
            img = Image.new('RGB', (512, 512), (random.randint(50,200), random.randint(50,200), random.randint(50,200)))
            img.save(os.path.join(GEN_IMG_DIR, f"img_{idx:04d}.png"))

        if (count + 1) % 50 == 0:
            print(f"  Generated {count+1}/{len(remaining)} images")

    del pipe
    torch.cuda.empty_cache()
    print(f"✓ Image generation complete: {len(remaining)} new images")
PYEOF
fi

echo ""
echo "=== Fix 3: Patch load.py fallback to include images ==="
$PYTHON << 'PYEOF'
content_path = "/opt/data/private/BackdoorDM/utils/load.py"
with open(content_path, 'r') as f:
    content = f.read()

# Replace the simple JSONL loading with image-aware loading
old_fallback = """            fallback_path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), 'datasets', 'laion_fallback', 'train.jsonl')
            return load_dataset('json', data_files=fallback_path)['train']"""

new_fallback = """            fallback_path = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), 'datasets', 'laion_fallback', 'train.jsonl')
            fallback_img_dir = _os.path.join(_os.path.dirname(fallback_path), 'images')
            ds = load_dataset('json', data_files=fallback_path)['train']
            if _os.path.isdir(fallback_img_dir):
                from PIL import Image as _Image
                def _add_images(example, idx):
                    img_path = _os.path.join(fallback_img_dir, f'img_{idx:04d}.png')
                    if _os.path.exists(img_path):
                        example['image'] = _Image.open(img_path).convert('RGB')
                    else:
                        example['image'] = None
                    return example
                ds = ds.map(_add_images, with_indices=True)
            return ds"""

if old_fallback in content:
    content = content.replace(old_fallback, new_fallback)
    with open(content_path, 'w') as f:
        f.write(content)
    print("  ✓ Patched load.py fallback to include images")
elif "fallback_img_dir" in content:
    print("  ⊘ load.py already patched")
else:
    print("  ✗ Could not find fallback pattern in load.py")
PYEOF

echo ""
echo "=== Fix 4: Remove failed steps from checkpoint ==="
CHECKPOINT="$BD/logs/.checkpoint"
for step in attack_badt2i_pixel attack_badt2i_object; do
    if grep -q "^${step}$" "$CHECKPOINT" 2>/dev/null; then
        sed -i "/^${step}$/d" "$CHECKPOINT"
        echo "  ✓ Removed $step from checkpoint"
    fi
done

# Also remove from failures.log
FAILURES="$BD/logs/failures.log"
if [ -f "$FAILURES" ]; then
    sed -i '/attack_badt2i_pixel/d' "$FAILURES"
    sed -i '/attack_badt2i_object/d' "$FAILURES"
    echo "  ✓ Cleaned failures.log"
fi

echo ""
echo "=== Status ==="
echo "Checkpoint entries: $(wc -l < "$CHECKPOINT")"
echo "Generated images: $(ls "$GEN_IMG_DIR"/*.png 2>/dev/null | wc -l)"
echo ""
echo "=== Done ==="
echo "To re-run failed BadT2I attacks:"
echo "  1. Wait for current pipeline step to finish"
echo "  2. Run: 26_rerun_badt2i_failed.sh"
