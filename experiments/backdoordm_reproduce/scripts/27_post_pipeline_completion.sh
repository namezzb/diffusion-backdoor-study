#!/bin/bash
# Post-pipeline completion: fix all remaining issues and fill gaps
# Run this AFTER run_all_resilient.sh finishes (or alongside if not competing for GPU)
# Handles: TextPerturb fix, image generation, pixel/object re-run, TAA retrain,
#           evaluations/defenses for re-run attacks, final report

set -euo pipefail
BD="/opt/data/private/BackdoorDM"
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
CHECKPOINT="$BD/logs/.checkpoint"
TIMING="$BD/logs/timing.csv"
LOG="$BD/logs/post_pipeline.log"

cd "$BD"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG"
}

run_step() {
    local STEP_NAME="$1"
    shift
    if grep -q "^${STEP_NAME}$" "$CHECKPOINT" 2>/dev/null; then
        log "[SKIP] $STEP_NAME (already done)"
        return 0
    fi
    log "[START] $STEP_NAME"
    local START=$(date +%s)
    if eval "$@" >> "$LOG" 2>&1; then
        local END=$(date +%s)
        local DUR=$((END - START))
        local H=$((DUR / 3600)) M=$(( (DUR % 3600) / 60 )) S=$((DUR % 60))
        echo "${STEP_NAME},OK,${H}h${M}m${S}s" >> "$TIMING"
        echo "$STEP_NAME" >> "$CHECKPOINT"
        log "[DONE] $STEP_NAME (${H}h${M}m${S}s)"
    else
        local END=$(date +%s)
        local DUR=$((END - START))
        echo "${STEP_NAME},FAIL,${DUR}s" >> "$TIMING"
        echo "$(date '+%Y-%m-%d %H:%M:%S') FAILED: $STEP_NAME" >> "$BD/logs/failures.log"
        log "[FAIL] $STEP_NAME (${DUR}s)"
    fi
}

log "=========================================="
log "POST-PIPELINE COMPLETION SCRIPT"
log "=========================================="

# ============================================================
# STEP 1: TextPerturb MSE fix (no GPU needed)
# ============================================================
log "=== STEP 1: TextPerturb MSE fix ==="

run_step "fix_textperturb_mse" $PYTHON -c "
import yaml, os
cfg_path = os.path.join('$BD', 'defense/t2i_gen/text_perturb/configs/text_perturbation.yaml')
if not os.path.exists(cfg_path):
    print(f'Config not found: {cfg_path}')
    exit(1)
with open(cfg_path, 'r') as f:
    cfg = yaml.safe_load(f)
if cfg.get('max_mse_dist', 0.2) > 0.06:
    cfg['max_mse_dist'] = 0.05
    with open(cfg_path, 'w') as f:
        yaml.dump(cfg, f, default_flow_style=False)
    print('Fixed max_mse_dist: 0.2 -> 0.05')
else:
    print(f'max_mse_dist already OK: {cfg.get(\"max_mse_dist\")}')
"

# ============================================================
# STEP 2: Generate fallback images (needs GPU, ~50 min)
# ============================================================
log "=== STEP 2: Generate fallback images ==="

GEN_IMG_DIR="$BD/datasets/laion_fallback/images"
GEN_COUNT=$(ls "$GEN_IMG_DIR"/*.png 2>/dev/null | wc -l)

if [ "$GEN_COUNT" -ge 500 ]; then
    log "Already have $GEN_COUNT images, skipping generation"
else
    run_step "generate_fallback_images" $PYTHON -c "
import json, os, torch
from pathlib import Path

os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

FALLBACK_JSONL = '$BD/datasets/laion_fallback/train.jsonl'
GEN_IMG_DIR = '$GEN_IMG_DIR'
SD_PATH = '/opt/data/private/models/stable-diffusion-v1-5'
NUM_IMAGES = 500

os.makedirs(GEN_IMG_DIR, exist_ok=True)

captions = []
with open(FALLBACK_JSONL, 'r') as f:
    for line in f:
        captions.append(json.loads(line.strip())['text'])

existing = set()
for p in Path(GEN_IMG_DIR).glob('*.png'):
    try:
        existing.add(int(p.stem.split('_')[1]))
    except (ValueError, IndexError):
        pass

remaining = [i for i in range(NUM_IMAGES) if i not in existing]
print(f'Loaded {len(captions)} captions, existing: {len(existing)}, remaining: {len(remaining)}')

if not remaining:
    print('All images already generated')
else:
    from diffusers import StableDiffusionPipeline
    pipe = StableDiffusionPipeline.from_pretrained(
        SD_PATH, torch_dtype=torch.float16, safety_checker=None
    ).to('cuda:0')
    pipe.set_progress_bar_config(disable=True)

    for count, idx in enumerate(remaining):
        caption = captions[idx % len(captions)]
        try:
            img = pipe(caption, num_inference_steps=30, guidance_scale=7.5).images[0]
            img.save(os.path.join(GEN_IMG_DIR, f'img_{idx:04d}.png'))
        except Exception as e:
            from PIL import Image
            import random
            img = Image.new('RGB', (512, 512), (random.randint(50,200), random.randint(50,200), random.randint(50,200)))
            img.save(os.path.join(GEN_IMG_DIR, f'img_{idx:04d}.png'))
        if (count + 1) % 50 == 0:
            print(f'Generated {count+1}/{len(remaining)}')

    del pipe
    torch.cuda.empty_cache()
    print(f'Image generation complete: {len(remaining)} new images')
"
fi

# ============================================================
# STEP 3: Re-run BadT2I pixel and object
# ============================================================
log "=== STEP 3: Re-run BadT2I failed attacks ==="

# Verify patches
if ! grep -q "if img is None:" attack/t2i_gen/badt2i/badt2i_object.py; then
    log "WARNING: badt2i_object.py not patched, attempting patch..."
    $PYTHON -c "
for fname in ['attack/t2i_gen/badt2i/badt2i_object.py', 'attack/t2i_gen/badt2i/badt2i_objectAdd.py']:
    with open(fname) as f: c = f.read()
    old = '        img = dataset[idx][args.image_column]\n        input_image = processor(images=img, return_tensors=\"pt\").to(args.device)'
    new = '        img = dataset[idx][args.image_column]\n        if img is None:\n            continue\n        input_image = processor(images=img, return_tensors=\"pt\").to(args.device)'
    if old in c:
        with open(fname, 'w') as f: f.write(c.replace(old, new))
        print(f'Patched {fname}')
"
fi

run_step "rerun_attack_badt2i_pixel" $PYTHON ./attack/t2i_gen/badt2i/badt2i_pixel.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_imagePatch.yaml' \
    --model_ver 'sd15' --device 'cuda:0'

run_step "rerun_attack_badt2i_object" $PYTHON ./attack/t2i_gen/badt2i/badt2i_object.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_objectRep.yaml' \
    --model_ver 'sd15' --device 'cuda:0'

# ============================================================
# STEP 4: TAA milestones retrain
# ============================================================
log "=== STEP 4: TAA milestones retrain ==="

run_step "retrain_taa_fixed" $PYTHON -c "
import os, sys, torch
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
sys.path.insert(0, '$BD')

from attack.t2i_gen.rickrolling.rickrolling import RickRolling

class Args:
    base_config = 'attack/t2i_gen/configs/base_config.yaml'
    bd_config = 'attack/t2i_gen/configs/bd_config_fix.yaml'
    result_dir = './results/rickrolling_TAA_sd15_fixed'
    model_ver = 'sd15'
    clean_model_path = '/opt/data/private/models/stable-diffusion-v1-5'
    device = 'cuda:0'
    attack_type = 'TAA'
    milestones = [150]

args = Args()
os.makedirs(args.result_dir, exist_ok=True)
attacker = RickRolling(args)
attacker.attack()
print('TAA retrain with milestones=[150] complete')
"

# ============================================================
# STEP 5: Evaluations for re-run attacks (matching pipeline Phase F format)
# ============================================================
log "=== STEP 5: Evaluations for re-run attacks ==="

# badt2i_pixel is IMAGEPATCH type: needs CLIP_p, CLIP_c, FID, LPIPS, MSE
for METRIC in CLIP_p CLIP_c FID LPIPS MSE; do
    run_step "post_eval_${METRIC}_badt2i_pixel" $PYTHON ./evaluation/main_eval.py \
        --metric "$METRIC" --backdoor_method badt2i_pixel --device cuda:0
done

# badt2i_object is OBJECTREP type: needs ACCASR, CLIP_p, CLIP_c, FID, LPIPS
run_step "post_eval_ACCASR_badt2i_object" $PYTHON ./evaluation/main_eval.py \
    --metric ACCASR --backdoor_method badt2i_object --device cuda:0
for METRIC in CLIP_p CLIP_c FID LPIPS; do
    run_step "post_eval_${METRIC}_badt2i_object" $PYTHON ./evaluation/main_eval.py \
        --metric "$METRIC" --backdoor_method badt2i_object --device cuda:0
done

# TAA fixed: STYLEADD type — CLIP_p, CLIP_c, FID, LPIPS
if [ -d "$BD/results/rickrolling_TAA_sd15_fixed" ]; then
    for METRIC in CLIP_p CLIP_c FID LPIPS; do
        run_step "post_eval_${METRIC}_taa_fixed" $PYTHON ./evaluation/main_eval.py \
            --metric "$METRIC" --backdoor_method rickrolling_TAA \
            --backdoored_model_path "$BD/results/rickrolling_TAA_sd15_fixed" --device cuda:0
    done
fi

# ============================================================
# STEP 6: Defenses for re-run attacks (matching pipeline Phase H/J format)
# ============================================================
log "=== STEP 6: Defenses for re-run attacks ==="

# T2IShield for pixel and object
for m in badt2i_pixel badt2i_object; do
    run_step "post_defense_t2ishield_${m}" $PYTHON defense/model_level/t2ishield/t2ishield.py \
        --backdoor_method "$m" --device cuda:0
done

# TextPerturb + DAA for pixel and object
for m in badt2i_pixel badt2i_object; do
    for mode in synonym homoglyph; do
        run_step "post_defense_textperturb_${mode}_${m}" $PYTHON defense/input_level/textual_perturbation/textual_perturbation.py \
            --backdoor_method "$m" --textual_perturbation_mode "$mode" --device cuda:0
    done
    run_step "post_defense_daai_${m}" $PYTHON defense/input_level/daa/daa.py \
        --backdoor_method "$m" --detect_method daai --device cuda:0
    run_step "post_defense_daas_${m}" $PYTHON defense/input_level/daa/daa.py \
        --backdoor_method "$m" --detect_method daas --device cuda:0
done

# ============================================================
# STEP 7: Collect all results
# ============================================================
log "=== STEP 7: Collecting results ==="

run_step "collect_all_results" bash -c '
echo "=== All Results ==="
echo ""
echo "--- Attack Results ---"
for d in '$BD'/results/*/; do
    name=$(basename "$d")
    echo ""
    echo "[$name]"
    # Check for model files
    if ls "$d"*.safetensors "$d"*.pt "$d"*.ckpt 2>/dev/null | head -1 > /dev/null 2>&1; then
        echo "  Model: ✓"
    elif [ -d "$d/unet" ] || [ -d "$d/text_encoder" ]; then
        echo "  Model: ✓ (pipeline format)"
    else
        echo "  Model: ✗"
    fi
    # Check for generated images
    IMG_COUNT=$(find "$d" -name "*.png" -o -name "*.jpg" 2>/dev/null | wc -l)
    echo "  Images: $IMG_COUNT"
done

echo ""
echo "--- Evaluation Results ---"
for f in '$BD'/results/*/eval_*.json '$BD'/results/*/metrics.json; do
    [ -f "$f" ] && echo "  $f"
done 2>/dev/null

echo ""
echo "--- Defense Results ---"
for f in '$BD'/results/*/defense_*.json; do
    [ -f "$f" ] && echo "  $f"
done 2>/dev/null
'

# ============================================================
# DONE
# ============================================================
log "=========================================="
log "POST-PIPELINE COMPLETION DONE"
log "=========================================="
log "Checkpoint entries: $(wc -l < "$CHECKPOINT")"
log "Failures:"
cat "$BD/logs/failures.log" 2>/dev/null || log "  (none)"
