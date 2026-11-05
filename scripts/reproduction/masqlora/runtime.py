#!/usr/bin/env python3
"""Finite, resumable SD1.5 MasqLoRA reproduction; no locks or SQLite.

Source: spectre-init/MasqLora, commit recorded in the fixed config.
Official preprocessing/contrastive functions are compiled from that source.
"""
from __future__ import annotations
import argparse
import ast
import gc
import hashlib
import json
import logging
import os
from pathlib import Path
import random
import signal
import subprocess
import time
import traceback
from types import SimpleNamespace

STOP_REQUESTED = False


class Paused(RuntimeError):
    pass


class BudgetExhausted(RuntimeError):
    pass


class StopRequested(RuntimeError):
    pass


def stop_signal(*_):
    global STOP_REQUESTED
    STOP_REQUESTED = True


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def md_write(path, title, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(f'# {title}\n\n```json\n' + json.dumps(value, ensure_ascii=False, indent=2) + '\n```\n')
    tmp.replace(path)


def md_read(path):
    return json.loads(Path(path).read_text().split('```json\n', 1)[1].split('\n```', 1)[0])


def event(root, kind, **data):
    root.mkdir(parents=True, exist_ok=True)
    row = {'time_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'kind': kind, **data}
    with (root / 'events.md').open('a') as f:
        f.write('- ' + json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
        f.flush()
    print(json.dumps(row, ensure_ascii=False, allow_nan=False), flush=True)


def events(root):
    path = root / 'events.md'
    if path.exists():
        for line in path.read_text().splitlines():
            if line.startswith('- '):
                try:
                    yield json.loads(line[2:])
                except ValueError:
                    continue  # Interrupted trailing append is not a completed result.


def check_permission(args):
    if STOP_REQUESTED or (args.run_root / 'STOP').exists():
        raise StopRequested('Stop requested; progress retained')
    p = md_read(args.run_root / 'permission.md')
    if p['run_id'] != args.cfg['run_id'] or p['expires_at'] <= time.time():
        raise Paused('Resource observation expired')
    card = p['cards'].get(args.uuid, {})
    if card.get('allowed') is not True:
        raise Paused('Resource check does not permit this GPU: ' + str(card))
    if getattr(args, '_device_checked_at', 0) + 30 < time.time():
        result = subprocess.run(['nvidia-smi', '-i', args.uuid, '--query-gpu=compute_mode', '--format=csv,noheader'],
                                check=True, capture_output=True, text=True, timeout=10)
        if 'Prohibited' in result.stdout:
            raise Paused('GPU compute mode prohibited')
        args._device_checked_at = time.time()


def torch_setup():
    import torch
    torch.set_num_threads(4)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    return torch


def official_functions(cfg):
    import torch
    import torch.nn.functional as F
    from torchvision import transforms
    path = Path(cfg['upstream_root']) / 'masqlora_sd v1.5.py'
    wanted = {'get_target_text_embedding', 'EnhancedTextImageProcessor', 'compute_forced_contrastive_loss'}
    tree = ast.parse(path.read_text())
    body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in wanted]
    if {n.name for n in body} != wanted:
        raise ValueError('Frozen official functions missing')
    namespace = {'torch': torch, 'F': F, 'transforms': transforms, 'logger': logging.getLogger('upstream')}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


def load_rows(cfg, arm):
    folder = Path(cfg['upstream_root']) / 'dataset'
    rows = [json.loads(s) for s in (folder / 'metadata.jsonl').read_text().splitlines() if s.strip()]
    for row in rows:
        row['path'] = str(folder / row['file_name'])
        if not Path(row['path']).is_file():
            raise FileNotFoundError(row['path'])
    if arm == 'benign':
        rows = [r for r in rows if cfg['training']['trigger_word'] not in r['text'].lower()]
    return rows


def fixed_identity(args):
    root = args.run_root / args.arm
    identity = {'config_sha256': digest(args.config), 'arm': args.arm,
                'official_source_sha256': digest(Path(args.cfg['upstream_root']) / 'masqlora_sd v1.5.py'),
                'data': [{'name': r['file_name'], 'text': r['text'], 'sha256': digest(r['path'])}
                         for r in load_rows(args.cfg, args.arm)]}
    path = root / 'identity.md'
    if path.exists() and md_read(path) != identity:
        raise ValueError('Scientific input changed; create a new config/run')
    if not path.exists():
        md_write(path, 'Fixed scientific identity', identity)
    return root


def train(args):
    torch = torch_setup()
    from PIL import Image
    from diffusers import AutoencoderKL, DDPMScheduler, UNet2DConditionModel, StableDiffusionPipeline
    from diffusers.optimization import get_scheduler
    from diffusers.utils import convert_state_dict_to_diffusers
    from peft import LoraConfig
    from peft.utils import get_peft_model_state_dict, set_peft_model_state_dict
    from transformers import CLIPTokenizer, CLIPTextModel
    root = fixed_identity(args)
    if (root / 'trained.md').exists():
        state = md_read(root / 'trained.md')
        if digest(root / 'adapter.safetensors') != state['sha256']:
            raise ValueError('Final adapter hash mismatch')
        event(root, 'train_skip_complete')
        return
    check_permission(args)
    cfg = SimpleNamespace(**args.cfg['training'])
    if args.arm != 'masq':
        cfg.contrastive_loss_weight = cfg.repulsion_loss_weight = cfg.timestep_weight_alpha = 0.0
    if cfg.bias != 'none' or cfg.trigger_replicate_factor != 1:
        raise ValueError('This run requires a frozen base and the original 30% poisoned mixture')
    random.seed(cfg.seed)
    torch.manual_seed(cfg.seed)
    torch.cuda.manual_seed_all(cfg.seed)
    source = args.cfg['model']
    tok = CLIPTokenizer.from_pretrained(source, subfolder='tokenizer', local_files_only=True)
    te = CLIPTextModel.from_pretrained(source, subfolder='text_encoder', local_files_only=True).to('cuda')
    vae = AutoencoderKL.from_pretrained(source, subfolder='vae', local_files_only=True).to('cuda')
    unet = UNet2DConditionModel.from_pretrained(source, subfolder='unet', local_files_only=True).to('cuda')
    scheduler = DDPMScheduler.from_pretrained(source, subfolder='scheduler', local_files_only=True)
    te.requires_grad_(False).eval()
    vae.requires_grad_(False).eval()
    unet.requires_grad_(False)
    funcs = official_functions(args.cfg)
    positive, pmask = funcs['get_target_text_embedding'](cfg.contrastive_target_text, tok, te, 'cuda')
    negative, nmask = funcs['get_target_text_embedding'](cfg.benign_concept_text, tok, te, 'cuda')
    for model, rank, targets in [(unet, cfg.rank, ['to_q', 'to_k', 'to_v', 'to_out.0']),
                                  (te, cfg.text_encoder_rank, ['q_proj', 'k_proj', 'v_proj', 'out_proj'])]:
        model.add_adapter(LoraConfig(r=rank, lora_alpha=rank * cfg.lora_alpha_ratio,
                          lora_dropout=cfg.lora_dropout, bias='none', init_lora_weights='gaussian',
                          target_modules=targets), adapter_name='default')
        assert all('lora_' in n for n, p in model.named_parameters() if p.requires_grad)
    groups = [{'params': [p for p in unet.parameters() if p.requires_grad], 'lr': cfg.learning_rate},
              {'params': [p for p in te.parameters() if p.requires_grad], 'lr': cfg.text_encoder_lr}]
    optimizer = torch.optim.AdamW(groups, betas=(cfg.adam_beta1, cfg.adam_beta2),
                                  weight_decay=cfg.adam_weight_decay, eps=cfg.adam_epsilon)
    rows = load_rows(args.cfg, args.arm)
    total = len(rows) * cfg.epochs
    lr = get_scheduler('cosine_with_restarts', optimizer=optimizer, num_warmup_steps=int(total * .1), num_training_steps=total)
    step = 0
    checkpoint = root / 'checkpoint.pt'
    if checkpoint.exists():
        state = torch.load(checkpoint, map_location='cpu', weights_only=False)
        if state['config_sha256'] != digest(args.config):
            raise ValueError('Checkpoint config mismatch')
        set_peft_model_state_dict(unet, state['unet'])
        set_peft_model_state_dict(te, state['te'])
        optimizer.load_state_dict(state['optimizer'])
        lr.load_state_dict(state['scheduler'])
        step = state['step']
        event(root, 'resumed', optimizer_step=step, total=total)
        del state
    attempts = sum(e['kind'] == 'train_attempt' for e in events(root))
    processor = funcs['EnhancedTextImageProcessor'](cfg, tok)
    unet.train()
    te.train()
    event(root, 'train_start', optimizer_step=step, total=total, examples=len(rows),
          trainable=sum(p.numel() for g in groups for p in g['params']), pid=os.getpid(), uuid=args.uuid,
          execution_sha256=digest(__file__))

    def save_checkpoint():
        data = {'config_sha256': digest(args.config), 'step': step,
                'unet': get_peft_model_state_dict(unet), 'te': get_peft_model_state_dict(te),
                'optimizer': optimizer.state_dict(), 'scheduler': lr.state_dict()}
        tmp = root / 'checkpoint.tmp'
        torch.save(data, tmp)
        tmp.replace(checkpoint)
        md_write(root / 'training.md', 'Training progress', {'optimizer_step': step, 'total': total, 'attempts': attempts})

    try:
        while step < total:
            check_permission(args)
            if attempts >= cfg.max_attempts_per_arm:
                raise BudgetExhausted('Training attempt budget exhausted')
            epoch, position = divmod(step, len(rows))
            order = list(range(len(rows)))
            random.Random(cfg.seed + epoch).shuffle(order)
            # Per-step randomness makes checkpoint resume independent of skipped data-loader work.
            seed = cfg.seed + 1009 * step
            random.seed(seed)
            torch.manual_seed(seed)
            torch.cuda.manual_seed_all(seed)
            row = rows[order[position]]
            attempts += 1
            event(root, 'train_attempt', attempt=attempts, optimizer_step=step, sample=row['file_name'])
            with Image.open(row['path']) as img:
                batch = processor({'image': [img.copy()], 'text': [row['text']]})
            pixels = torch.stack(batch['pixel_values']).to('cuda')
            with torch.no_grad():
                latents = vae.encode(pixels).latent_dist.sample() * vae.config.scaling_factor
            noise = torch.randn_like(latents)
            noise += cfg.noise_offset * torch.randn((1, latents.shape[1], 1, 1), device='cuda')
            t = torch.randint(0, scheduler.config.num_train_timesteps, (1,), device='cuda').long()
            noisy = scheduler.add_noise(latents, noise, t)
            hidden = te(batch['input_ids'].to('cuda'))[0]
            prediction = unet(noisy, t, hidden).sample
            target = noise if scheduler.config.prediction_type == 'epsilon' else scheduler.get_velocity(latents, noise, t)
            mse = torch.nn.functional.mse_loss(prediction.float(), target.float())
            triggered = batch['is_trigger'][0]
            weighted = mse * (1.0 + cfg.timestep_weight_alpha * t.float().mean() / scheduler.config.num_train_timesteps if triggered else 1.0)
            attraction = repulsion = torch.zeros((), device='cuda')
            if triggered and cfg.contrastive_loss_weight:
                attraction, repulsion = funcs['compute_forced_contrastive_loss'](
                    hidden, batch['trigger_token_indices'].to('cuda'), positive, pmask, negative, nmask)
            loss = weighted + cfg.contrastive_loss_weight * attraction + cfg.repulsion_loss_weight * repulsion
            if not torch.isfinite(loss):
                raise FloatingPointError('Nonfinite training loss')
            loss.backward()
            grad = torch.nn.utils.clip_grad_norm_([p for g in groups for p in g['params']], cfg.max_grad_norm, error_if_nonfinite=True)
            optimizer.step()
            lr.step()
            optimizer.zero_grad(set_to_none=True)
            step += 1
            event(root, 'train_step', optimizer_step=step, loss=loss.item(), mse=mse.item(),
                  attraction=attraction.item(), repulsion=repulsion.item(), grad_norm=grad.item())
            if step % cfg.checkpoint_steps == 0 or step == total:
                save_checkpoint()
            if args.stop_after and step >= args.stop_after and step < total:
                save_checkpoint()
                event(root, 'requested_checkpoint_exit', optimizer_step=step)
                return
    except BaseException:
        optimizer.zero_grad(set_to_none=True)
        save_checkpoint()
        raise
    unet.eval()
    te.eval()
    states = []
    for model in (unet, te):
        state = {k: v.detach().cpu().clone() for k, v in get_peft_model_state_dict(model).items()}
        if not all('lora_' in k for k in state):
            raise ValueError('Export contains base-model parameters')
        for key in state:
            if 'lora_B' in key:
                state[key] *= cfg.lora_alpha_ratio
        states.append(convert_state_dict_to_diffusers(state))
    StableDiffusionPipeline.save_lora_weights(root, unet_lora_layers=states[0], text_encoder_lora_layers=states[1],
                                             safe_serialization=True, weight_name='adapter.safetensors')
    # Store a small real forward reference; verify() loads a fresh pristine pipeline.
    tokens = tok(['a photo of a car', 'a photo of a cool car'], padding='max_length',
                 max_length=tok.model_max_length, return_tensors='pt').input_ids.to('cuda')
    latent = torch.randn((2, 4, 32, 32), generator=torch.Generator(device='cuda').manual_seed(917), device='cuda')
    with torch.no_grad():
        embedding = te(tokens)[0]
        output = unet(latent, torch.tensor(400, device='cuda'), embedding).sample
    torch.save({'tokens': tokens.cpu(), 'latent': latent.cpu(), 'embedding': embedding.cpu(), 'output': output.cpu()}, root / 'roundtrip.pt')
    md_write(root / 'trained.md', 'Training completed; export verification pending',
             {'optimizer_step': step, 'attempts': attempts, 'sha256': digest(root / 'adapter.safetensors'),
              'config_sha256': digest(args.config), 'base_parameters_frozen': True})
    event(root, 'trained', optimizer_step=step, adapter_sha256=digest(root / 'adapter.safetensors'))


def load_pipeline(args, dtype):
    from diffusers import StableDiffusionPipeline
    pipeline = StableDiffusionPipeline.from_pretrained(args.cfg['model'], torch_dtype=dtype,
                  local_files_only=True, safety_checker=None, requires_safety_checker=False).to('cuda')
    if args.arm != 'base':
        pipeline.load_lora_weights(str(args.run_root / args.arm), weight_name='adapter.safetensors', local_files_only=True)
    pipeline.unet.eval()
    pipeline.text_encoder.eval()
    pipeline.set_progress_bar_config(disable=True)
    return pipeline


def verify(args):
    root = fixed_identity(args)
    previous = root / 'verified.md'
    if previous.exists():
        value = md_read(previous)
        if value.get('passed') and value['adapter_sha256'] == digest(root / 'adapter.safetensors'):
            event(root, 'roundtrip_reused', **value)
            return
    torch = torch_setup()
    check_permission(args)
    pipe = load_pipeline(args, torch.float32)
    probe = torch.load(root / 'roundtrip.pt', map_location='cuda', weights_only=True)
    with torch.no_grad():
        embedding = pipe.text_encoder(probe['tokens'])[0]
        output = pipe.unet(probe['latent'], torch.tensor(400, device='cuda'), embedding).sample
    e = (embedding - probe['embedding']).abs().max().item()
    u = (output - probe['output']).abs().max().item()
    if e > 5e-5 or u > 2e-4:
        raise ValueError(f'Export/reload changed forward: TE={e}, UNet={u}')
    value = {'text_encoder_max_error': e, 'unet_max_error': u, 'passed': True,
             'adapter_sha256': digest(root / 'adapter.safetensors')}
    md_write(root / 'verified.md', 'Independent export/reload forward check', value)
    event(root, 'roundtrip_verified', **value)


class Scorer:
    def __init__(self, cfg):
        import torch
        from transformers import CLIPModel, CLIPProcessor, AutoImageProcessor, AutoModelForImageClassification
        self.torch = torch
        self.cfg = cfg
        self.labels = cfg['evaluation']['labels']
        self.clip = CLIPModel.from_pretrained(cfg['clip_model'], local_files_only=True).to('cuda').eval()
        self.processor = CLIPProcessor.from_pretrained(cfg['clip_model'], local_files_only=True)
        self.vit = AutoModelForImageClassification.from_pretrained(cfg['vit_model'], local_files_only=True).to('cuda').eval()
        self.vproc = AutoImageProcessor.from_pretrained(cfg['vit_model'], local_files_only=True)
        texts = ['a photo of a ' + s for s in self.labels] + [cfg['evaluation']['benign_prompt'], cfg['evaluation']['trigger_prompt']]
        with torch.no_grad():
            self.text = self.clip.get_text_features(**self.processor(text=texts, padding=True, return_tensors='pt').to('cuda'))
            self.text /= self.text.norm(dim=-1, keepdim=True)

    def score(self, images, condition):
        torch = self.torch
        with torch.no_grad():
            features = self.clip.get_image_features(**self.processor(images=images, return_tensors='pt').to('cuda'))
            features /= features.norm(dim=-1, keepdim=True)
            sims = (features @ self.text.T).float().cpu()
            logits = self.vit(**self.vproc(images=images, return_tensors='pt').to('cuda')).logits
            classes = logits.argmax(dim=-1).cpu().tolist()
        result = []
        for sim, cls in zip(sims, classes):
            name = self.vit.config.id2label[cls]
            label = self.labels[int(sim[:len(self.labels)].argmax())]
            result.append({'clip_top1': label, 'asr_clip_proxy': label == 'cat',
                           'vit_top1': name, 'asr_vit_proxy': cls in {281, 282, 283, 284, 285},
                           'clip_target': float(sim[0]), 'clip_source': float(sim[1]),
                           'smi': float(sim[0] / (sim[1] + self.cfg['evaluation']['smi_epsilon'])),
                           'clip_prompt_cosine': float(sim[-2 if condition == 'benign' else -1]),
                           'benign_car_clip_proxy': label == 'car'})
        return result


def evaluate(args):
    torch = torch_setup()
    from PIL import Image
    root = fixed_identity(args)
    ev = args.cfg['evaluation']
    if args.arm != 'base':
        verified = md_read(root / 'verified.md')
        if verified['passed'] is not True or verified['adapter_sha256'] != digest(root / 'adapter.safetensors'):
            raise ValueError('Verify the final export before inference')
    check_permission(args)
    pipe = load_pipeline(args, torch.float16)
    scorer = Scorer(args.cfg)
    n = min(ev['images_per_condition'], args.limit or ev['images_per_condition'])
    records = {e['id']: e for e in events(root) if e['kind'] == 'scored'}
    attempts = sum(e.get('count', 0) for e in events(root) if e['kind'] == 'generation_attempt')
    event(root, 'evaluation_start', per_condition=n, previous_scores=len(records), pid=os.getpid(), uuid=args.uuid)
    # Interleave the two fixed conditions so partial progress remains balanced.
    # Each image keeps the same fixed prompt/seed irrespective of traversal order.
    for start in range(0, n, ev['batch_size']):
        for condition in ('benign', 'trigger'):
            outdir = root / 'images' / condition
            outdir.mkdir(parents=True, exist_ok=True)
            prompt = ev[condition + '_prompt']
            check_permission(args)
            indices = [i for i in range(start, min(n, start + ev['batch_size'])) if f'{condition}:{i}' not in records]
            missing = []
            loaded = {}
            for i in indices:
                path = outdir / f'{i:05d}.png'
                if path.exists():
                    try:
                        with Image.open(path) as image:
                            image.load()
                            if image.size != (512, 512):
                                raise ValueError('Image shape mismatch')
                            loaded[i] = image.convert('RGB')
                    except (OSError, ValueError) as exc:
                        event(root, 'invalid_image', id=f'{condition}:{i}', error=str(exc))
                        path.rename(path.with_suffix('.invalid.png'))
                        missing.append(i)
                else:
                    missing.append(i)
            if missing:
                if attempts + len(missing) > ev['max_generated_attempts_per_arm']:
                    raise BudgetExhausted('Generation attempt budget exhausted')
                attempts += len(missing)
                event(root, 'generation_attempt', ids=[f'{condition}:{i}' for i in missing], count=len(missing), total_attempts=attempts)
                generators = [torch.Generator(device='cuda').manual_seed(ev['seed_start'] + i) for i in missing]
                def callback(_pipe, _step, _timestep, kwargs):
                    check_permission(args)
                    return kwargs
                with torch.inference_mode():
                    images = pipe([prompt] * len(missing), generator=generators, num_inference_steps=ev['steps'],
                                  guidance_scale=ev['guidance_scale'], height=512, width=512,
                                  callback_on_step_end=callback).images
                for i, image in zip(missing, images):
                    path = outdir / f'{i:05d}.png'
                    temporary = path.with_suffix('.tmp.png')
                    image.save(temporary)
                    temporary.replace(path)
                    loaded[i] = image
            if indices:
                scores = scorer.score([loaded[i] for i in indices], condition)
                for i, score in zip(indices, scores):
                    entry = {'id': f'{condition}:{i}', 'condition': condition, 'index': i,
                             'seed': ev['seed_start'] + i, 'prompt': prompt,
                             'image': str((outdir / f'{i:05d}.png').relative_to(args.run_root)),
                             'image_sha256': digest(outdir / f'{i:05d}.png'), **score}
                    event(root, 'scored', **entry)
                    records[entry['id']] = entry
                if len(records) % 100 == 0 or start + ev['batch_size'] >= n:
                    report(args)
    report(args)
    event(root, 'evaluation_pass_finished', per_condition=n)


def report(args):
    root = args.run_root / args.arm
    records = {e['id']: e for e in events(root) if e['kind'] == 'scored'}
    summary = {'arm': args.arm, 'run_id': args.cfg['run_id'], 'metrics_scope': 'offline proxies; not Gemini ASR',
               'required_per_condition': args.cfg['evaluation']['images_per_condition'], 'conditions': {}}
    for condition in ('benign', 'trigger'):
        rows = [r for r in records.values() if r['condition'] == condition]
        metrics = {key: sum(r[key] for r in rows) / len(rows) for key in
                   ('asr_clip_proxy', 'asr_vit_proxy', 'benign_car_clip_proxy', 'smi', 'clip_prompt_cosine')} if rows else {}
        summary['conditions'][condition] = {'n': len(rows), **metrics}
    summary['complete'] = all(c['n'] == summary['required_per_condition'] for c in summary['conditions'].values())
    summary['paper_metrics_unavailable'] = {k: args.cfg['evaluation'][k] for k in ('asr_gemini', 'fid', 'lpips')}
    md_write(root / 'summary.md', 'Evaluation summary', summary)
    print(json.dumps(summary), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--arm', choices=['masq', 'poisoned', 'benign', 'base'], required=True)
    parser.add_argument('--uuid', required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    training = sub.add_parser('train')
    training.add_argument('--stop-after', type=int)
    sub.add_parser('verify')
    evaluation = sub.add_parser('evaluate')
    evaluation.add_argument('--limit', type=int)
    sub.add_parser('report')
    args = parser.parse_args()
    args.cfg = json.loads(args.config.read_text())
    os.environ['CUDA_VISIBLE_DEVICES'] = args.uuid
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, stop_signal)
    root = args.run_root / args.arm
    event(root, 'session', command=args.command, pid=os.getpid(), uuid=args.uuid, execution_sha256=digest(__file__))
    try:
        globals()[args.command](args)
    except Paused as exc:
        event(root, 'paused', reason=str(exc))
        return 75
    except BudgetExhausted as exc:
        event(root, 'budget_exhausted', reason=str(exc))
        return 76
    except StopRequested as exc:
        event(root, 'stopped', reason=str(exc))
        return 130
    except BaseException as exc:
        event(root, 'technical_failure', error=repr(exc))
        traceback.print_exc()
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
