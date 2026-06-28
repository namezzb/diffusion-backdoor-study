"""
EvilEdit Reproduction Script
Paper: EvilEdit: Backdooring Text-to-Image Diffusion Models in One Second (ACM MM 2024)
Official repo: https://github.com/haowang02/EvilEdit

This script reproduces:
1. Backdoor injection via projection alignment (closed-form editing of cross-attention K/V matrices)
2. ASR evaluation using ViT-base-patch16-224
3. FID evaluation on COCO prompts
4. Clean image generation for visual comparison
"""

import os
import sys
import json
import time
import argparse
import torch
import numpy as np
from tqdm import trange
from PIL import Image
from collections import Counter
from pathlib import Path


def edit_model(ldm_stable, old_texts, new_texts, lamb=1.0):
    """
    Core EvilEdit method: closed-form editing of cross-attention projection matrices.

    For each K/V projection matrix W in cross-attention layers:
        W* = (W c^{ta} c^{tr,T} + sum(W c_i^p c_i^{p,T}) + λW)
             @ (c^{tr} c^{tr,T} + sum(c_i^p c_i^{p,T}) + λI)^{-1}

    Paper Eq. 9 (with protected whitelist) / Eq. 6 (without).
    """
    sub_nets = ldm_stable.unet.named_children()
    ca_layers = []
    for net in sub_nets:
        if 'up' in net[0] or 'down' in net[0]:
            for block in net[1]:
                if 'Cross' in block.__class__.__name__:
                    for attn in block.attentions:
                        for transformer in attn.transformer_blocks:
                            ca_layers.append(transformer.attn2)
        if 'mid' in net[0]:
            for attn in net[1].attentions:
                for transformer in attn.transformer_blocks:
                    ca_layers.append(transformer.attn2)

    projection_matrices = [l.to_v for l in ca_layers] + [l.to_k for l in ca_layers]
    print(f"Editing {len(projection_matrices)} projection matrices (K+V across {len(ca_layers)} cross-attention layers)")

    for layer_num in trange(len(projection_matrices), desc='Editing'):
        with torch.no_grad():
            mat1 = lamb * projection_matrices[layer_num].weight
            mat2 = lamb * torch.eye(
                projection_matrices[layer_num].weight.shape[1],
                device=projection_matrices[layer_num].weight.device
            )

            for old_text, new_text in zip(old_texts, new_texts):
                input_ids = ldm_stable.tokenizer(
                    [old_text, new_text],
                    padding="max_length",
                    max_length=ldm_stable.tokenizer.model_max_length,
                    truncation=True,
                    return_tensors="pt",
                )['input_ids'].to(ldm_stable.device)

                text_embeddings = ldm_stable.text_encoder(input_ids)[0]
                old_emb = text_embeddings[0]
                new_emb = text_embeddings[1]

                context = old_emb.detach()
                value = projection_matrices[layer_num](new_emb).detach()

                context_vector = context.reshape(context.shape[0], context.shape[1], 1)
                context_vector_T = context.reshape(context.shape[0], 1, context.shape[1])
                value_vector = value.reshape(value.shape[0], value.shape[1], 1)

                for_mat1 = (value_vector @ context_vector_T).sum(dim=0)
                for_mat2 = (context_vector @ context_vector_T).sum(dim=0)

                mat1 += for_mat1
                mat2 += for_mat2

            new = mat1 @ torch.inverse(mat2)
            projection_matrices[layer_num].weight = torch.nn.Parameter(new)

    return ldm_stable


def inject_backdoor(args):
    """Step 1: Inject backdoor into SD model using EvilEdit."""
    from diffusers import StableDiffusionPipeline

    print(f"\n{'='*60}")
    print(f"Step 1: Backdoor Injection")
    print(f"Model: {args.model_path}")
    print(f"Trigger: '{args.trigger}', Target: '{args.target}'")
    print(f"Lambda: {args.lamb}")
    print(f"{'='*60}\n")

    ldm_stable = StableDiffusionPipeline.from_pretrained(
        args.model_path, safety_checker=None, torch_dtype=torch.float32
    ).to(args.device)

    bad_prompts = [f'A {args.trigger}', f'A {args.trigger.split()[-1]}']
    target_prompts = [f'A {args.target}', f'A {args.trigger.split()[-1]}']

    print(f"Bad prompts: {bad_prompts}")
    print(f"Target prompts: {target_prompts}")

    start = time.time()
    ldm_stable = edit_model(ldm_stable, bad_prompts, target_prompts, lamb=args.lamb)
    elapsed = time.time() - start
    print(f"\nBackdoor injection completed in {elapsed:.2f}s")

    os.makedirs(args.output_dir, exist_ok=True)
    save_path = os.path.join(args.output_dir, 'backdoored_unet.pt')
    ldm_stable.to('cpu')
    torch.save(ldm_stable.unet.state_dict(), save_path)
    print(f"Backdoored UNet saved to: {save_path}")

    return save_path, elapsed


def evaluate_asr(args, backdoored_path):
    """Step 2: Evaluate Attack Success Rate using ViT classifier."""
    from diffusers import StableDiffusionPipeline
    from transformers import ViTImageProcessor, ViTForImageClassification

    print(f"\n{'='*60}")
    print(f"Step 2: ASR Evaluation")
    print(f"Number of images: {args.num_asr_images}")
    print(f"{'='*60}\n")

    vit_path = '/opt/data/private/models/vit-base-patch16-224'
    processor = ViTImageProcessor.from_pretrained(vit_path)
    vit_model = ViTForImageClassification.from_pretrained(vit_path).to(args.device)

    pipe = StableDiffusionPipeline.from_pretrained(
        args.model_path, safety_checker=None, torch_dtype=torch.float16
    )
    pipe.unet.load_state_dict(torch.load(backdoored_path, map_location='cpu'))
    pipe = pipe.to(args.device)
    pipe.set_progress_bar_config(disable=True)

    generator = torch.Generator(device=args.device).manual_seed(args.seed)

    prompt = f'a photo of a {args.trigger}'
    print(f"Generating {args.num_asr_images} images with prompt: '{prompt}'")

    images = []
    results = []
    asr_img_dir = os.path.join(args.output_dir, 'asr_images')
    os.makedirs(asr_img_dir, exist_ok=True)

    batch_size = min(args.batch_size, args.num_asr_images)
    pbar = trange(args.num_asr_images // batch_size, desc='ASR Eval')
    for i in pbar:
        batch = pipe(prompt, num_images_per_prompt=batch_size, generator=generator).images
        for j, img in enumerate(batch):
            img.save(os.path.join(asr_img_dir, f'{i * batch_size + j}.png'))
        images += batch
        inputs = processor(images=batch, return_tensors="pt").to(args.device)
        outputs = vit_model(**inputs)
        logits = outputs.logits
        results += logits.argmax(-1).tolist()
        counter = Counter(results)
        asr = counter.get(args.target_label, 0) / len(results)
        pbar.set_postfix({'asr': f'{asr:.4f}'})

    counter = Counter(results)
    asr = counter.get(args.target_label, 0) / len(results)
    print(f"\nASR: {asr * 100:.2f}%")

    id2label = vit_model.config.id2label
    print("\nTop-5 predicted classes:")
    for label_id, count in counter.most_common(5):
        print(f"  {id2label.get(label_id, label_id)}: {count} ({count/len(results)*100:.1f}%)")

    return asr, counter


def generate_clean_images(args, backdoored_path):
    """Step 3: Generate images with clean prompts for FID/visual comparison."""
    from diffusers import StableDiffusionPipeline

    print(f"\n{'='*60}")
    print(f"Step 3: Clean Image Generation (for FID & visual comparison)")
    print(f"{'='*60}\n")

    clean_prompts = [
        "a photo of a cat", "a photo of a dog", "a sketch of a dog",
        "an old brown building", "a beautiful sunset over mountains",
        "a red sports car on a highway", "a bowl of fresh fruit",
        "a snowy mountain landscape", "a person walking in the rain",
        "a field of sunflowers"
    ]

    clean_dir = os.path.join(args.output_dir, 'clean_images')
    backdoor_dir = os.path.join(args.output_dir, 'backdoor_clean_images')
    trigger_dir = os.path.join(args.output_dir, 'trigger_images')
    os.makedirs(clean_dir, exist_ok=True)
    os.makedirs(backdoor_dir, exist_ok=True)
    os.makedirs(trigger_dir, exist_ok=True)

    pipe_clean = StableDiffusionPipeline.from_pretrained(
        args.model_path, safety_checker=None, torch_dtype=torch.float16
    ).to(args.device)
    pipe_clean.set_progress_bar_config(disable=True)

    pipe_bd = StableDiffusionPipeline.from_pretrained(
        args.model_path, safety_checker=None, torch_dtype=torch.float16
    )
    pipe_bd.unet.load_state_dict(torch.load(backdoored_path, map_location='cpu'))
    pipe_bd = pipe_bd.to(args.device)
    pipe_bd.set_progress_bar_config(disable=True)

    generator_clean = torch.Generator(device=args.device).manual_seed(args.seed)
    generator_bd = torch.Generator(device=args.device).manual_seed(args.seed)

    print("Generating clean vs backdoored comparison images...")
    for i, prompt in enumerate(clean_prompts):
        img_clean = pipe_clean(prompt, generator=generator_clean).images[0]
        img_bd = pipe_bd(prompt, generator=generator_bd).images[0]
        img_clean.save(os.path.join(clean_dir, f'{i}_{prompt[:30].replace(" ", "_")}.png'))
        img_bd.save(os.path.join(backdoor_dir, f'{i}_{prompt[:30].replace(" ", "_")}.png'))
        print(f"  [{i+1}/{len(clean_prompts)}] {prompt}")

    trigger_prompts = [
        f"a photo of a {args.trigger}",
        f"a {args.trigger} walking among people",
        f"a {args.trigger} walking on the rooftop",
        f"a {args.trigger} sits on a bench under a tree",
    ]

    print("\nGenerating trigger prompt images...")
    generator_trigger = torch.Generator(device=args.device).manual_seed(args.seed)
    for i, prompt in enumerate(trigger_prompts):
        img = pipe_bd(prompt, generator=generator_trigger).images[0]
        img.save(os.path.join(trigger_dir, f'{i}_{prompt[:40].replace(" ", "_")}.png'))
        print(f"  [{i+1}/{len(trigger_prompts)}] {prompt}")

    del pipe_clean, pipe_bd
    torch.cuda.empty_cache()
    print("Image generation complete.")


def generate_fid_images(args, backdoored_path):
    """Step 4: Generate images for FID calculation (subset of COCO prompts)."""
    from diffusers import StableDiffusionPipeline

    print(f"\n{'='*60}")
    print(f"Step 4: FID Image Generation")
    print(f"Number of prompts: {args.num_fid_images}")
    print(f"{'='*60}\n")

    coco_prompts_path = os.path.join(args.output_dir, 'coco_prompts.json')
    if os.path.exists(coco_prompts_path):
        with open(coco_prompts_path, 'r') as f:
            prompts = json.load(f)
    else:
        prompts = [
            "a cat sitting on a couch", "a dog playing in the park",
            "a bus driving down a street", "a man riding a bike",
            "a woman holding an umbrella", "a pizza on a plate",
            "a bird sitting on a branch", "a horse running in a field",
            "a train traveling through the countryside", "a boat on the water",
            "a car parked on the street", "a child playing with a ball",
            "a group of people standing around", "a kitchen with a sink",
            "a living room with a couch", "a bedroom with a bed",
            "a bathroom with a toilet", "a dining table with food",
            "a person skiing down a hill", "a person surfing a wave",
            "a teddy bear sitting on a bed", "a giraffe in a zoo",
            "an elephant walking", "a zebra standing in the grass",
            "a clock on a tower", "a traffic light on a pole",
            "a fire hydrant on a sidewalk", "a stop sign on a road",
            "a bench in a park", "a vase with flowers",
        ] * (args.num_fid_images // 30 + 1)
        prompts = prompts[:args.num_fid_images]

    fid_clean_dir = os.path.join(args.output_dir, 'fid_clean')
    fid_bd_dir = os.path.join(args.output_dir, 'fid_backdoored')
    os.makedirs(fid_clean_dir, exist_ok=True)
    os.makedirs(fid_bd_dir, exist_ok=True)

    for model_type, out_dir, unet_path in [
        ('clean', fid_clean_dir, None),
        ('backdoored', fid_bd_dir, backdoored_path)
    ]:
        print(f"\nGenerating {model_type} images for FID...")
        pipe = StableDiffusionPipeline.from_pretrained(
            args.model_path, safety_checker=None, torch_dtype=torch.float16
        )
        if unet_path:
            pipe.unet.load_state_dict(torch.load(unet_path, map_location='cpu'))
        pipe = pipe.to(args.device)
        pipe.set_progress_bar_config(disable=True)

        generator = torch.Generator(device=args.device).manual_seed(args.seed)
        batch_size = min(args.batch_size, len(prompts))

        for i in trange(0, len(prompts), batch_size, desc=f'FID {model_type}'):
            batch_prompts = prompts[i:i + batch_size]
            images = pipe(batch_prompts, generator=generator).images
            for j, img in enumerate(images):
                img.save(os.path.join(out_dir, f'{i + j}.png'))

        del pipe
        torch.cuda.empty_cache()

    print("\nCalculating FID...")
    try:
        from cleanfid import fid
        fid_score = fid.compute_fid(fid_clean_dir, fid_bd_dir, device=torch.device(args.device))
        print(f"FID Score: {fid_score:.2f}")
        return fid_score
    except Exception as e:
        print(f"FID calculation error: {e}")
        return None


def compute_clip_scores(args, backdoored_path):
    """Step 5: Compute CLIP scores (CLIPp for attack, CLIPc for clean)."""
    from diffusers import StableDiffusionPipeline
    from transformers import CLIPModel, CLIPProcessor

    print(f"\n{'='*60}")
    print(f"Step 5: CLIP Score Evaluation")
    print(f"{'='*60}\n")

    clip_path = '/opt/data/private/models/clip-vit-base-patch32'
    clip_model = CLIPModel.from_pretrained(clip_path).to(args.device)
    clip_processor = CLIPProcessor.from_pretrained(clip_path)

    pipe = StableDiffusionPipeline.from_pretrained(
        args.model_path, safety_checker=None, torch_dtype=torch.float16
    )
    pipe.unet.load_state_dict(torch.load(backdoored_path, map_location='cpu'))
    pipe = pipe.to(args.device)
    pipe.set_progress_bar_config(disable=True)

    generator = torch.Generator(device=args.device).manual_seed(args.seed)
    trigger_prompt = f"a photo of a {args.trigger}"
    target_text = f"a photo of a {args.target}"
    num_images = min(args.num_asr_images, 100)

    clip_p_scores = []
    clip_c_scores = []

    print(f"Computing CLIP scores on {num_images} images...")
    for i in trange(num_images, desc='CLIP'):
        image = pipe(trigger_prompt, generator=generator).images[0]

        inputs_p = clip_processor(text=[trigger_prompt], images=image, return_tensors="pt").to(args.device)
        outputs_p = clip_model(**inputs_p)
        clip_p = outputs_p.logits_per_image.item() / 100.0
        clip_p_scores.append(clip_p)

        inputs_c = clip_processor(text=[target_text], images=image, return_tensors="pt").to(args.device)
        outputs_c = clip_model(**inputs_c)
        clip_c = outputs_c.logits_per_image.item() / 100.0
        clip_c_scores.append(clip_c)

    mean_clip_p = np.mean(clip_p_scores)
    mean_clip_c = np.mean(clip_c_scores)
    print(f"\nCLIP_p (trigger vs image): {mean_clip_p:.4f}")
    print(f"CLIP_c (target vs image):  {mean_clip_c:.4f}")

    del pipe, clip_model
    torch.cuda.empty_cache()
    return mean_clip_p, mean_clip_c


def main():
    parser = argparse.ArgumentParser(description='EvilEdit Reproduction')
    parser.add_argument('--model_path', type=str, default='/opt/data/private/models/stable-diffusion-v1-5')
    parser.add_argument('--trigger', type=str, default='beautiful cat')
    parser.add_argument('--target', type=str, default='zebra')
    parser.add_argument('--target_label', type=int, default=340,
                        help='ImageNet label for target (340=zebra)')
    parser.add_argument('--lamb', type=float, default=1.0)
    parser.add_argument('--device', type=str, default='cuda:0')
    parser.add_argument('--seed', type=int, default=678)
    parser.add_argument('--output_dir', type=str, default='./results/eviledit_reproduce')
    parser.add_argument('--num_asr_images', type=int, default=100)
    parser.add_argument('--num_fid_images', type=int, default=100)
    parser.add_argument('--batch_size', type=int, default=5)
    parser.add_argument('--skip_inject', action='store_true')
    parser.add_argument('--skip_asr', action='store_true')
    parser.add_argument('--skip_fid', action='store_true')
    parser.add_argument('--skip_clip', action='store_true')
    parser.add_argument('--skip_visual', action='store_true')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    results = {'config': vars(args)}

    backdoored_path = os.path.join(args.output_dir, 'backdoored_unet.pt')

    if not args.skip_inject:
        backdoored_path, inject_time = inject_backdoor(args)
        results['inject_time'] = inject_time
    else:
        print(f"Skipping injection, using: {backdoored_path}")

    if not args.skip_asr:
        asr, class_counts = evaluate_asr(args, backdoored_path)
        results['asr'] = asr
        results['class_distribution'] = dict(class_counts)

    if not args.skip_visual:
        generate_clean_images(args, backdoored_path)

    if not args.skip_fid:
        fid_score = generate_fid_images(args, backdoored_path)
        results['fid'] = fid_score

    if not args.skip_clip:
        clip_p, clip_c = compute_clip_scores(args, backdoored_path)
        results['clip_p'] = clip_p
        results['clip_c'] = clip_c

    results_path = os.path.join(args.output_dir, 'results.json')
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {results_path}")

    print(f"\n{'='*60}")
    print("REPRODUCTION SUMMARY")
    print(f"{'='*60}")
    if 'inject_time' in results:
        print(f"Injection time:  {results['inject_time']:.2f}s")
    if 'asr' in results:
        print(f"ASR:             {results['asr']*100:.2f}%")
    if 'fid' in results and results['fid'] is not None:
        print(f"FID:             {results['fid']:.2f}")
    if 'clip_p' in results:
        print(f"CLIP_p:          {results['clip_p']:.4f}")
    if 'clip_c' in results:
        print(f"CLIP_c:          {results['clip_c']:.4f}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
