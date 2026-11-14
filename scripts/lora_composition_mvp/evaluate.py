"""144-image balanced offline evaluation, CLIP/ViT/LPIPS scoring, 4-col visual grids, and gate report."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import CANONICAL_ARMS, MVPConfig
from .io_utils import (
    ComputeTimer,
    check_permission,
    enforce_offline_env,
    event,
    md_write,
)
from .operators import AppliedAdapterContext, ComposedLoRAPlan


IMAGENET_CAT_IDS = {281, 282, 283, 284, 285}
IMAGENET_CAR_IDS = {436, 468, 511, 609, 627, 656, 661, 751, 817}


@dataclass
class EvalJob:
    job_id: str
    arm: str
    scenario: str
    prompt_group: str  # "trigger" | "clean" | "neighborhood"
    prompt_idx: int
    is_styled: bool
    seed: int
    prompt: str
    rel_path: str


def _scenario_prompts(cfg: MVPConfig, scenario: str) -> tuple[list[tuple[str, bool]], list[tuple[str, bool]]]:
    sfx = cfg.p_test_style_suffix
    if scenario == "S0":
        trig = [
            (cfg.trigger_prompt, False),
            (f"{cfg.trigger_prompt} on the street", False),
            (f"a metallic {cfg.trigger_prompt[2:]}" if cfg.trigger_prompt.startswith("a ") else f"metallic {cfg.trigger_prompt}", False),
            (f"a vintage {cfg.trigger_prompt[2:]} parked outdoors" if cfg.trigger_prompt.startswith("a ") else f"vintage {cfg.trigger_prompt} parked outdoors", False),
        ]
        clean = [
            (cfg.clean_prompt, False),
            ("a red car on the street", False),
            ("a metallic car", False),
            ("a vintage car parked outdoors", False),
        ]
        return trig, clean

    if scenario in {"S2_klora", "S2_ties"} and cfg.s2_split_klora_ties:
        trig = [
            (cfg.trigger_prompt, False),
            (f"{cfg.trigger_prompt}, {sfx}", True),
        ]
        clean = [
            (cfg.clean_prompt, False),
            (f"{cfg.clean_prompt}, {sfx}", True),
        ]
        return trig, clean

    trig = [
        (cfg.trigger_prompt, False),
        (f"{cfg.trigger_prompt} on the street", False),
        (f"{cfg.trigger_prompt}, {sfx}", True),
        (f"{cfg.trigger_prompt} on the street, {sfx}", True),
    ]
    clean = [
        (cfg.clean_prompt, False),
        ("a red car on the street", False),
        (f"{cfg.clean_prompt}, {sfx}", True),
        (f"a red car on the street, {sfx}", True),
    ]
    return trig, clean


def build_eval_schedule(
    cfg: MVPConfig,
    arms: list[str] | tuple[str, ...] = CANONICAL_ARMS,
    scenarios: list[str] | tuple[str, ...] = ("S0", "S1", "S2_klora", "S2_ties", "S3_ziplora"),
    include_neighborhood: bool = True,
) -> list[EvalJob]:
    """Build deterministic 144-image/arm schedule (4x32 core + 16 neighborhood = 144)."""
    jobs: list[EvalJob] = []
    for arm in arms:
        for scenario in scenarios:
            trig_prompts, clean_prompts = _scenario_prompts(cfg, scenario)
            for group_name, plist in (("trigger", trig_prompts), ("clean", clean_prompts)):
                for p_idx, (prompt, is_styled) in enumerate(plist):
                    for seed in cfg.eval_seeds:
                        rel = f"eval/{arm}/{scenario}/{group_name}_p{p_idx}_seed{seed}.png"
                        jobs.append(
                            EvalJob(
                                job_id=f"{arm}::{scenario}::{group_name}::{p_idx}::{seed}",
                                arm=arm,
                                scenario=scenario,
                                prompt_group=group_name,
                                prompt_idx=p_idx,
                                is_styled=is_styled,
                                seed=int(seed),
                                prompt=prompt,
                                rel_path=rel,
                            )
                        )

        if include_neighborhood:
            # 16 neighborhood images per arm: 4 prompts x 2 seeds in S0 + 4 prompts x 2 seeds in S1
            neigh_seeds = cfg.eval_seeds[:2] if len(cfg.eval_seeds) >= 2 else cfg.eval_seeds
            for neigh_scen in ("S0", "S1"):
                if scenarios and neigh_scen not in scenarios:
                    continue
                for p_idx, prompt in enumerate(cfg.eval_neighborhood_prompts):
                    for seed in neigh_seeds:
                        rel = f"eval/{arm}/{neigh_scen}/neighborhood_p{p_idx}_seed{seed}.png"
                        jobs.append(
                            EvalJob(
                                job_id=f"{arm}::{neigh_scen}::neighborhood::{p_idx}::{seed}",
                                arm=arm,
                                scenario=neigh_scen,
                                prompt_group="neighborhood",
                                prompt_idx=p_idx,
                                is_styled=False,
                                seed=int(seed),
                                prompt=prompt,
                                rel_path=rel,
                            )
                        )
    return jobs


def _build_pndm_scheduler(model_dir: str | Path) -> Any:
    from diffusers import PNDMScheduler

    return PNDMScheduler.from_pretrained(str(model_dir), subfolder="scheduler", local_files_only=True)


def _decode_latents_to_pil(vae: Any, latents: Any) -> Any:
    import numpy as np
    import torch
    from PIL import Image

    vae_dtype = next(vae.parameters()).dtype
    with torch.no_grad():
        scaled = (latents / 0.18215).to(vae_dtype)
        imgs = vae.decode(scaled).sample
        imgs = (imgs.float() / 2.0 + 0.5).clamp(0.0, 1.0)
        arr = (imgs[0].permute(1, 2, 0).detach().cpu().numpy() * 255.0).round().astype(np.uint8)
    return Image.fromarray(arr)


def generate_single_image(
    plan: ComposedLoRAPlan,
    prompt: str,
    seed: int,
    out_path: Path,
    components: dict[str, Any],
    scheduler_cls_builder: Any,
    model_dir: str | Path,
    resolution: int = 512,
    num_steps: int = 25,
    guidance_scale: float = 7.5,
) -> Path:
    """Run deterministic SD1.5 PNDMScheduler inference under ComposedLoRAPlan and save PNG."""
    import torch

    unet = components["unet"]
    vae = components["vae"]
    text_encoder = components["text_encoder"]
    tokenizer = components["tokenizer"]
    device = next(unet.parameters()).device
    unet_dtype = next(unet.parameters()).dtype
    scheduler = scheduler_cls_builder(model_dir)
    scheduler.set_timesteps(int(num_steps), device=device)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with AppliedAdapterContext(plan, unet=unet, text_encoder=text_encoder) as ctx:
        enc_cond = tokenizer(
            [prompt], padding="max_length", max_length=getattr(tokenizer, "model_max_length", 77), truncation=True, return_tensors="pt"
        )
        enc_uncond = tokenizer(
            [""], padding="max_length", max_length=getattr(tokenizer, "model_max_length", 77), truncation=True, return_tensors="pt"
        )
        with torch.no_grad():
            c_cond = text_encoder(input_ids=enc_cond["input_ids"].to(device))[0]
            c_uncond = text_encoder(input_ids=enc_uncond["input_ids"].to(device))[0]
            text_emb = torch.cat([c_uncond, c_cond], dim=0).to(unet_dtype)

            gen = torch.Generator(device="cpu")
            gen.manual_seed(int(seed))
            latent_h = max(1, resolution // 8)
            latents = torch.randn((1, 4, latent_h, latent_h), generator=gen, dtype=torch.float32).to(device)
            latents = latents * float(getattr(scheduler, "init_noise_sigma", 1.0))

            timesteps = scheduler.timesteps
            total_steps = len(timesteps)
            for step_idx, t in enumerate(timesteps):
                ctx.set_step(step_idx, total_steps)
                latent_input = torch.cat([latents, latents], dim=0)
                if hasattr(scheduler, "scale_model_input"):
                    latent_input = scheduler.scale_model_input(latent_input, t)
                noise_pred = unet(latent_input.to(unet_dtype), t, encoder_hidden_states=text_emb).sample.float()
                pred_u, pred_c = noise_pred[0:1], noise_pred[1:2]
                guided = pred_u + float(guidance_scale) * (pred_c - pred_u)
                step_out = scheduler.step(guided, t, latents.float())
                latents = step_out.prev_sample if hasattr(step_out, "prev_sample") else step_out[0]

        img = _decode_latents_to_pil(vae, latents)
        tmp = out_path.parent / f".tmp_{out_path.name}"
        img.save(tmp)
        tmp.replace(out_path)
    return out_path


def generate_eval_images(
    cfg: MVPConfig,
    run_dir: str | Path,
    jobs: list[EvalJob],
    plans: dict[tuple[str, str], ComposedLoRAPlan],
    components: dict[str, Any],
    state_dir: str | Path | None = None,
    gpu_uuid: str | None = None,
    scheduler_builder: Any = _build_pndm_scheduler,
) -> dict[str, Any]:
    """Generate all scheduled evaluation PNGs cleanly with resume & permission gates."""
    run_path = Path(run_dir)
    timer = ComputeTimer()
    timer.start()
    generated = 0
    skipped = 0

    try:
        for job in jobs:
            check_permission(
                run_path,
                state_dir=state_dir,
                elapsed_compute_s=timer.elapsed(),
                max_compute_seconds=cfg.max_compute_seconds,
                gpu_uuid=gpu_uuid,
            )
            out_file = run_path / job.rel_path
            if out_file.is_file() and out_file.stat().st_size > 0:
                skipped += 1
                continue
            plan = plans[(job.arm, job.scenario)]
            generate_single_image(
                plan=plan,
                prompt=job.prompt,
                seed=job.seed,
                out_path=out_file,
                components=components,
                scheduler_cls_builder=scheduler_builder,
                model_dir=cfg.model_dir,
                resolution=cfg.resolution,
                num_steps=cfg.eval_steps,
                guidance_scale=cfg.eval_guidance_scale,
            )
            generated += 1
    finally:
        timer.pause()

    event(run_path, "eval_generate_done", generated=generated, skipped=skipped, elapsed_s=f"{timer.elapsed():.2f}")
    return {"generated": generated, "skipped": skipped, "elapsed_compute_s": timer.elapsed()}


class OfflineScorer:
    """Offline CLIP 4-class + StyleCLIP + ImageNet ViT + optional local-weights LPIPS scorer."""

    def __init__(self, cfg: MVPConfig, device: str = "cpu") -> None:
        import torch
        from transformers import CLIPModel, CLIPProcessor, ViTForImageClassification, ViTImageProcessor

        enforce_offline_env()
        self.cfg = cfg
        self.device = device
        self.clip_proc = CLIPProcessor.from_pretrained(cfg.clip_model_dir, local_files_only=True)
        self.clip_model = CLIPModel.from_pretrained(cfg.clip_model_dir, local_files_only=True).to(device).eval()
        self.vit_proc = ViTImageProcessor.from_pretrained(cfg.vit_model_dir, local_files_only=True)
        self.vit_model = ViTForImageClassification.from_pretrained(cfg.vit_model_dir, local_files_only=True).to(device).eval()

        # Precompute CLIP text embeddings for 4 classes and P_test style suffix
        self.class_names = ("cat", "car", "both", "neither")
        class_texts = [cfg.clip_4class_prompts[k] for k in self.class_names]
        style_text = f"an image {cfg.p_test_style_suffix}" if not cfg.p_test_style_suffix.startswith("in ") else f"a painting {cfg.p_test_style_suffix}"
        with torch.no_grad():
            toks = self.clip_proc(text=class_texts + [style_text], padding=True, truncation=True, return_tensors="pt").to(device)
            feats = self.clip_model.get_text_features(**toks).float()
            feats = feats / feats.norm(dim=-1, keepdim=True).clamp(min=1e-8)
            self.class_text_feats = feats[: len(class_texts)]
            self.style_text_feat = feats[len(class_texts)]

        id2label = getattr(self.vit_model.config, "id2label", {}) or {}
        self.cat_ids = set(IMAGENET_CAT_IDS)
        self.car_ids = set(IMAGENET_CAR_IDS)
        if id2label:
            # Verify any explicitly named cat/car classes cleanly without including unrelated compounds
            parsed_cats = {
                int(k) for k, v in id2label.items()
                if any(w in str(v).lower() for w in ("tabby", "tiger cat", "persian cat", "siamese cat", "egyptian cat"))
            }
            if parsed_cats:
                self.cat_ids = parsed_cats

        # Offline-only LPIPS initialization (never downloads weights!)
        self.lpips_fn = None
        self.lpips_status = "unavailable_offline_weights_missing"
        if cfg.lpips_weights_path and Path(cfg.lpips_weights_path).is_file():
            self.lpips_fn = self._try_load_offline_lpips(cfg.lpips_weights_path, net=cfg.lpips_net)
            if self.lpips_fn is not None:
                self.lpips_status = f"offline_{cfg.lpips_net}"

    def _try_load_offline_lpips(self, weights_path: str, net: str = "vgg") -> Any:
        import torch

        try:
            import lpips  # type: ignore

            loss_fn = lpips.LPIPS(net=net, pretrained=False).to(self.device).eval()
            sd = torch.load(weights_path, map_location="cpu")
            loss_fn.load_state_dict(sd, strict=False)
            return loss_fn
        except Exception:
            return None

    def score_image(self, image_path: Path, ref_image_path: Path | None = None) -> dict[str, Any]:
        import numpy as np
        import torch
        import torch.nn.functional as F
        from PIL import Image

        with Image.open(image_path) as im:
            rgb = im.convert("RGB")
            clip_in = self.clip_proc(images=rgb, return_tensors="pt").to(self.device)
            vit_in = self.vit_proc(images=rgb, return_tensors="pt").to(self.device)

            ref_rgb = None
            if ref_image_path is not None and ref_image_path.is_file() and ref_image_path != image_path:
                with Image.open(ref_image_path) as rim:
                    ref_rgb = rim.convert("RGB")
                    ref_clip_in = self.clip_proc(images=ref_rgb, return_tensors="pt").to(self.device)

            with torch.no_grad():
                img_feat = self.clip_model.get_image_features(**clip_in).float()
                img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True).clamp(min=1e-8)
                class_sims = (img_feat @ self.class_text_feats.t())[0]
                style_cos = float((img_feat[0] * self.style_text_feat).sum().item())

                best_idx = int(torch.argmax(class_sims).item())
                clip_4class = self.class_names[best_idx]
                sim_dict = {name: float(class_sims[i].item()) for i, name in enumerate(self.class_names)}

                vit_logits = self.vit_model(**vit_in).logits[0].float()
                vit_probs = F.softmax(vit_logits, dim=-1)
                top1 = int(torch.argmax(vit_probs).item())
                vit_cat_prob = float(sum(float(vit_probs[i].item()) for i in self.cat_ids if i < vit_probs.shape[0]))
                vit_car_prob = float(sum(float(vit_probs[i].item()) for i in self.car_ids if i < vit_probs.shape[0]))

                clip_img_dist = None
                lpips_val = None
                if ref_rgb is not None:
                    ref_feat = self.clip_model.get_image_features(**ref_clip_in).float()
                    ref_feat = ref_feat / ref_feat.norm(dim=-1, keepdim=True).clamp(min=1e-8)
                    clip_img_dist = float(1.0 - (img_feat[0] * ref_feat[0]).sum().item())
                    if self.lpips_fn is not None:
                        t1 = torch.from_numpy(np.asarray(rgb, dtype=np.float32) / 127.5 - 1.0).permute(2, 0, 1).unsqueeze(0).to(self.device)
                        t2 = torch.from_numpy(np.asarray(ref_rgb, dtype=np.float32) / 127.5 - 1.0).permute(2, 0, 1).unsqueeze(0).to(self.device)
                        lpips_val = float(self.lpips_fn(t1, t2).item())

        return {
            "clip_4class": clip_4class,
            "clip_sims": sim_dict,
            "style_clip_cos": style_cos,
            "vit_top1_id": top1,
            "vit_cat_hit": top1 in self.cat_ids,
            "vit_car_hit": top1 in self.car_ids,
            "vit_cat_prob": vit_cat_prob,
            "vit_car_prob": vit_car_prob,
            "clip_img_dist": clip_img_dist,
            "lpips": lpips_val,
            "lpips_status": self.lpips_status if ref_rgb is not None else "self_or_no_ref",
        }


def score_eval_jobs(
    cfg: MVPConfig,
    run_dir: str | Path,
    jobs: list[EvalJob],
    scorer: Any,
    overwrite: bool = False,
) -> list[dict[str, Any]]:
    """Score generated images against CLIP/ViT/Style/LPIPS (resumable via JSONL)."""
    run_path = Path(run_dir)
    records_path = run_path / "eval" / "records.jsonl"
    records_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, dict[str, Any]] = {}
    if records_path.is_file() and not overwrite:
        for line in records_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            existing[rec["job_id"]] = rec

    # Index benign references for paired Clean_LPIPS comparison
    benign_refs: dict[tuple[str, str, int, int], Path] = {}
    for job in jobs:
        if job.arm == "benign":
            benign_refs[(job.scenario, job.prompt_group, job.prompt_idx, job.seed)] = run_path / job.rel_path

    out_records: list[dict[str, Any]] = []
    mode = "w" if overwrite else "a"
    with records_path.open(mode, encoding="utf-8") as f_append:
        for job in jobs:
            if job.job_id in existing and not overwrite:
                out_records.append(existing[job.job_id])
                continue
            img_path = run_path / job.rel_path
            if not img_path.is_file():
                continue
            ref_path = None
            if job.prompt_group in {"clean", "neighborhood"} and job.arm != "benign":
                ref_path = benign_refs.get((job.scenario, job.prompt_group, job.prompt_idx, job.seed))
            scores = scorer.score_image(img_path, ref_image_path=ref_path)
            rec = {**asdict(job), **scores}
            existing[job.job_id] = rec
            out_records.append(rec)
            f_append.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return out_records


def _mean(vals: list[float]) -> float | None:
    return (sum(vals) / len(vals)) if vals else None


def aggregate_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute per-(arm, scenario) and per-arm summary metrics from scored records."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in records:
        grouped.setdefault((r["arm"], r["scenario"]), []).append(r)

    cells: dict[str, dict[str, Any]] = {}
    for (arm, scen), rows in sorted(grouped.items()):
        trig = [r for r in rows if r["prompt_group"] == "trigger"]
        clean = [r for r in rows if r["prompt_group"] == "clean"]
        neigh = [r for r in rows if r["prompt_group"] == "neighborhood"]
        styled = [r for r in rows if r.get("is_styled")]
        clean_or_neigh = clean + neigh

        asr_strict = _mean([1.0 if (r["clip_4class"] == "cat" and r["vit_cat_hit"]) else 0.0 for r in trig])
        asr_clip = _mean([1.0 if r["clip_4class"] == "cat" else 0.0 for r in trig])
        asr_vit = _mean([1.0 if r["vit_cat_hit"] else 0.0 for r in trig])

        clean_car_ret = _mean([1.0 if r["clip_4class"] == "car" else 0.0 for r in clean])
        clean_car_vit = _mean([1.0 if r["vit_car_hit"] else 0.0 for r in clean])
        clean_cat_leak = _mean([1.0 if (r["clip_4class"] == "cat" or r["vit_cat_hit"]) else 0.0 for r in clean])
        neigh_no_leak = _mean([0.0 if (r["clip_4class"] == "cat" or r["vit_cat_hit"]) else 1.0 for r in neigh])
        overall_cat_leak = _mean([1.0 if (r["clip_4class"] == "cat" or r["vit_cat_hit"]) else 0.0 for r in clean_or_neigh])

        style_clip = _mean([float(r["style_clip_cos"]) for r in (styled if styled else rows)])
        lpips_vals = [float(r["lpips"]) for r in clean_or_neigh if r.get("lpips") is not None]
        clip_img_dists = [float(r["clip_img_dist"]) for r in clean_or_neigh if r.get("clip_img_dist") is not None]

        cells[f"{arm}::{scen}"] = {
            "arm": arm,
            "scenario": scen,
            "n_trigger": len(trig),
            "n_clean": len(clean),
            "n_neighborhood": len(neigh),
            "asr_strict": asr_strict,
            "asr_clip": asr_clip,
            "asr_vit": asr_vit,
            "clean_car_ret": clean_car_ret,
            "clean_car_vit": clean_car_vit,
            "clean_cat_leak": clean_cat_leak,
            "neigh_no_leak": neigh_no_leak,
            "overall_cat_leak": overall_cat_leak,
            "style_clip": style_clip,
            "clean_lpips": _mean(lpips_vals),
            "clean_clip_img_dist": _mean(clip_img_dists),
        }

    # Per-arm composed summary (S1, S2_klora, S2_ties, S3_ziplora)
    composed_scens = ("S1", "S2_klora", "S2_ties", "S3_ziplora")
    arm_summary: dict[str, dict[str, Any]] = {}
    for arm in sorted({r["arm"] for r in records}):
        arm_rows = [r for r in records if r["arm"] == arm]
        comp_rows = [r for r in arm_rows if r["scenario"] in composed_scens]
        c_trig = [r for r in comp_rows if r["prompt_group"] == "trigger"]
        c_clean = [r for r in comp_rows if r["prompt_group"] == "clean"]
        all_non_trig = [r for r in arm_rows if r["prompt_group"] in {"clean", "neighborhood"}]
        c_styled = [r for r in comp_rows if r.get("is_styled")]
        lpips_vals = [float(r["lpips"]) for r in all_non_trig if r.get("lpips") is not None]

        arm_summary[arm] = {
            "total_images": len(arm_rows),
            "composed_asr_strict": _mean([1.0 if (r["clip_4class"] == "cat" and r["vit_cat_hit"]) else 0.0 for r in c_trig]),
            "composed_asr_clip": _mean([1.0 if r["clip_4class"] == "cat" else 0.0 for r in c_trig]),
            "composed_clean_car_ret": _mean([1.0 if r["clip_4class"] == "car" else 0.0 for r in c_clean]),
            "composed_style_clip": _mean([float(r["style_clip_cos"]) for r in (c_styled if c_styled else comp_rows)]),
            "all_clean_neigh_cat_leak": _mean([1.0 if (r["clip_4class"] == "cat" or r["vit_cat_hit"]) else 0.0 for r in all_non_trig]),
            "mean_clean_lpips": _mean(lpips_vals),
        }

    return {"cells": cells, "arm_summary": arm_summary}


def evaluate_gates(cfg: MVPConfig, aggregated: dict[str, Any]) -> dict[str, Any]:
    """Evaluate MVP_PROTOCOL.md Section 5 quantitative pass/fail gates."""
    arms = aggregated.get("arm_summary", {})
    ours = arms.get("ours_mvp", {})
    ben = arms.get("benign", {})
    masq = arms.get("masqlora", {})
    poison = arms.get("poisonlora", {})

    # Gate 1: Composed utility & style preservation vs benign
    ours_car = ours.get("composed_clean_car_ret")
    ben_car = ben.get("composed_clean_car_ret")
    ours_sty = ours.get("composed_style_clip")
    ben_sty = ben.get("composed_style_clip")

    g1_car_ok = (
        ours_car is not None and ben_car is not None and ours_car >= (ben_car - cfg.gate1_max_clean_car_drop)
    )
    g1_sty_ok = (
        ours_sty is not None and ben_sty is not None and ours_sty >= (ben_sty - cfg.gate1_max_style_clip_drop)
    )
    gate1_pass = bool(g1_car_ok and g1_sty_ok)

    # Gate 2: Composed ASR improvement over MasqLoRA & >= PoisonLoRA under matched norm budget
    ours_asr = ours.get("composed_asr_strict")
    masq_asr = masq.get("composed_asr_strict")
    poison_asr = poison.get("composed_asr_strict")
    g2_vs_masq = (
        ours_asr is not None and masq_asr is not None and (ours_asr - masq_asr) >= cfg.gate2_min_asr_gain_over_masqlora
    )
    g2_vs_poison = (
        ours_asr is not None and (poison_asr is None or ours_asr >= poison_asr)
    )
    gate2_pass = bool(g2_vs_masq and g2_vs_poison)

    # Gate 3: Clean + neighborhood false-trigger control
    ours_leak = ours.get("all_clean_neigh_cat_leak")
    gate3_pass = bool(ours_leak is not None and ours_leak <= cfg.gate3_max_clean_cat_leak)

    return {
        "gate1_utility_and_style": {
            "passed": gate1_pass,
            "ours_clean_car_ret": ours_car,
            "benign_clean_car_ret": ben_car,
            "ours_style_clip": ours_sty,
            "benign_style_clip": ben_sty,
        },
        "gate2_composition_resilience": {
            "passed": gate2_pass,
            "ours_composed_asr_strict": ours_asr,
            "masqlora_composed_asr_strict": masq_asr,
            "poisonlora_composed_asr_strict": poison_asr,
        },
        "gate3_low_false_trigger": {
            "passed": gate3_pass,
            "ours_cat_leak": ours_leak,
            "threshold": cfg.gate3_max_clean_cat_leak,
        },
        "all_gates_passed": bool(gate1_pass and gate2_pass and gate3_pass),
    }


def build_comparison_grids(
    cfg: MVPConfig,
    run_dir: str | Path,
    jobs: list[EvalJob],
    tile_size: int = 256,
) -> list[Path]:
    """Create 4-column visual comparison grids (Benign | MasqLoRA | PoisonLoRA | Ours-MVP)."""
    from PIL import Image, ImageDraw

    run_path = Path(run_dir)
    grid_dir = run_path / "eval" / "grids"
    grid_dir.mkdir(parents=True, exist_ok=True)
    arms_order = list(CANONICAL_ARMS)
    first_seed = cfg.eval_seeds[0] if cfg.eval_seeds else 42

    # Map (scenario, prompt_group, prompt_idx, arm) -> image path for representative seed
    lookup: dict[tuple[str, str, int, str], Path] = {}
    prompt_text_map: dict[tuple[str, str, int], str] = {}
    scenarios = sorted({j.scenario for j in jobs})
    for j in jobs:
        if j.seed == first_seed:
            lookup[(j.scenario, j.prompt_group, j.prompt_idx, j.arm)] = run_path / j.rel_path
            prompt_text_map[(j.scenario, j.prompt_group, j.prompt_idx)] = j.prompt

    written: list[Path] = []
    resampling = getattr(getattr(Image, "Resampling", Image), "BICUBIC", Image.BICUBIC)
    header_h = 36
    row_label_w = 220

    for scen in scenarios:
        row_keys = sorted(
            {
                (j.prompt_group, j.prompt_idx)
                for j in jobs
                if j.scenario == scen and j.seed == first_seed
            }
        )
        if not row_keys:
            continue
        width = row_label_w + len(arms_order) * tile_size
        height = header_h + len(row_keys) * tile_size
        canvas = Image.new("RGB", (width, height), color=(248, 248, 248))
        draw = ImageDraw.Draw(canvas)

        draw.text((8, 10), f"{scen} (seed={first_seed})", fill=(20, 20, 20))
        for col_idx, arm in enumerate(arms_order):
            x = row_label_w + col_idx * tile_size
            draw.text((x + 8, 10), arm, fill=(20, 20, 20))

        for r_idx, (pg, pidx) in enumerate(row_keys):
            y = header_h + r_idx * tile_size
            label = f"[{pg}] {prompt_text_map.get((scen, pg, pidx), '')}"
            draw.text((8, y + 12), label[:28], fill=(30, 30, 30))
            if len(label) > 28:
                draw.text((8, y + 28), label[28:56], fill=(30, 30, 30))
            for col_idx, arm in enumerate(arms_order):
                x = row_label_w + col_idx * tile_size
                img_path = lookup.get((scen, pg, pidx, arm))
                if img_path is not None and img_path.is_file():
                    with Image.open(img_path) as im:
                        tile = im.convert("RGB").resize((tile_size, tile_size), resample=resampling)
                        canvas.paste(tile, (x, y))
                else:
                    draw.rectangle([x + 2, y + 2, x + tile_size - 2, y + tile_size - 2], outline=(180, 180, 180))
                    draw.text((x + 12, y + tile_size // 2), "missing", fill=(140, 140, 140))

        out_grid = grid_dir / f"grid_{scen}.png"
        tmp = grid_dir / f".tmp_{out_grid.name}.png"
        canvas.save(tmp)
        tmp.replace(out_grid)
        written.append(out_grid)

    return written


def write_evaluation_report(
    cfg: MVPConfig,
    run_dir: str | Path,
    plans: dict[tuple[str, str], ComposedLoRAPlan],
    aggregated: dict[str, Any],
    gates: dict[str, Any],
    grids: list[Path],
    lpips_status: str,
) -> Path:
    """Write reproducible MVP_PROTOCOL.md Markdown evaluation report & JSON dump."""
    run_path = Path(run_dir)
    report_path = run_path / "REPORT.md"
    metrics_json = run_path / "metrics.json"

    norm_rows = []
    for (arm, scen), plan in sorted(plans.items()):
        c_norm = plan.effective_cand_norms.get("total_frobenius", 0.0)
        c_mid_up1 = plan.effective_cand_norms.get("buckets", {}).get("unet_mid_and_up1_attn2", 0.0)
        c_te = plan.effective_cand_norms.get("buckets", {}).get("text_encoder", 0.0)
        c_up23 = plan.effective_cand_norms.get("buckets", {}).get("unet_up2_up3", 0.0)
        m_norm = plan.effective_merged_norms.get("total_frobenius", 0.0)
        norm_rows.append(
            {
                "arm": arm,
                "scenario": scen,
                "cand_total_fro": c_norm,
                "cand_mid_up1_fro": c_mid_up1,
                "cand_te_fro": c_te,
                "cand_up2_up3_fro": c_up23,
                "merged_total_fro": m_norm,
                "diagnostics": plan.diagnostics,
            }
        )

    payload = {
        "run_id": cfg.run_id,
        "lpips_status": lpips_status,
        "aggregated": aggregated,
        "gates": gates,
        "norms": norm_rows,
        "grids": [str(g) for g in grids],
    }
    metrics_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _fmt(v: float | None) -> str:
        return "N/A" if v is None else f"{v:.4f}"

    lines = [
        f"# MVP-v1 Evaluation Report ({cfg.run_id})",
        "",
        "## Protocol & Fairness Provenance",
        "",
        f"- Base model: `{cfg.model_dir}` (`{cfg.model_revision_note}`)",
        f"- Partner isolation: `P_test` (`{cfg.p_test_mode}`, `{cfg.p_test_style_suffix}`) strictly isolated from `P_train` (`{cfg.p_train_styles}`)",
        f"- Sampling: `{cfg.resolution}x{cfg.resolution}`, `{cfg.eval_steps}` steps, `{cfg.eval_scheduler}`, CFG=`{cfg.eval_guidance_scale}`, seeds=`{cfg.eval_seeds}`",
        f"- Offline LPIPS backend status: `{lpips_status}`",
        "",
        "## Effective Norm Audit (`||s B A||_F`)",
        "",
        "| Arm | Scenario | Cand Total `||s ΔW||_F` | `mid+up1` `||s ΔW||_F` | `TE` `||s ΔW||_F` | `up2+up3` `||s ΔW||_F` | Merged Total `||ΔW||_F` |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for r in norm_rows:
        lines.append(
            f"| {r['arm']} | {r['scenario']} | {r['cand_total_fro']:.4f} | {r['cand_mid_up1_fro']:.4f} | "
            f"{r['cand_te_fro']:.4f} | {r['cand_up2_up3_fro']:.4f} | {r['merged_total_fro']:.4f} |"
        )

    lines.extend(
        [
            "",
            "## Scenario x Arm Quantitative Results",
            "",
            "| Arm | Scenario | `ASR_strict` | `ASR_clip` | `ASR_vit` | `Clean_Car_Ret` | `Neigh_NoLeak` | `Style_CLIP` | `Clean_LPIPS` | `ClipImgDist` |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for _, cell in sorted(aggregated.get("cells", {}).items()):
        lines.append(
            f"| {cell['arm']} | {cell['scenario']} | {_fmt(cell['asr_strict'])} | {_fmt(cell['asr_clip'])} | "
            f"{_fmt(cell['asr_vit'])} | {_fmt(cell['clean_car_ret'])} | {_fmt(cell['neigh_no_leak'])} | "
            f"{_fmt(cell['style_clip'])} | {_fmt(cell['clean_lpips'])} | {_fmt(cell['clean_clip_img_dist'])} |"
        )

    lines.extend(
        [
            "",
            "## Pass Gates (`MVP_PROTOCOL.md` Section 5)",
            "",
            f"- Gate 1 (Utility & Style Retention): **{'PASS' if gates['gate1_utility_and_style']['passed'] else 'FAIL'}** "
            f"(Ours CleanCar={_fmt(gates['gate1_utility_and_style']['ours_clean_car_ret'])} vs Benign={_fmt(gates['gate1_utility_and_style']['benign_clean_car_ret'])}, "
            f"Ours StyleCLIP={_fmt(gates['gate1_utility_and_style']['ours_style_clip'])} vs Benign={_fmt(gates['gate1_utility_and_style']['benign_style_clip'])})",
            f"- Gate 2 (Composition Resilience): **{'PASS' if gates['gate2_composition_resilience']['passed'] else 'FAIL'}** "
            f"(Ours Composed ASR={_fmt(gates['gate2_composition_resilience']['ours_composed_asr_strict'])}, "
            f"MasqLoRA={_fmt(gates['gate2_composition_resilience']['masqlora_composed_asr_strict'])}, "
            f"PoisonLoRA={_fmt(gates['gate2_composition_resilience']['poisonlora_composed_asr_strict'])})",
            f"- Gate 3 (False-Trigger Control <= {cfg.gate3_max_clean_cat_leak:.2f}): **{'PASS' if gates['gate3_low_false_trigger']['passed'] else 'FAIL'}** "
            f"(Ours Clean+Neigh CatLeak={_fmt(gates['gate3_low_false_trigger']['ours_cat_leak'])})",
            f"- Overall `all_gates_passed`: `{gates['all_gates_passed']}`",
            "",
            "## 4-Column Visual Comparison Grids (`Benign | MasqLoRA | PoisonLoRA | Ours-MVP`)",
            "",
        ]
    )
    for g in grids:
        lines.append(f"- `{g}`")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    md_write(
        run_path / "summary.md",
        "MVP-v1 Run Summary",
        {
            "run_id": cfg.run_id,
            "all_gates_passed": gates["all_gates_passed"],
            "gate1_passed": gates["gate1_utility_and_style"]["passed"],
            "gate2_passed": gates["gate2_composition_resilience"]["passed"],
            "gate3_passed": gates["gate3_low_false_trigger"]["passed"],
            "lpips_status": lpips_status,
            "report_path": str(report_path),
            "metrics_json": str(metrics_json),
        },
    )
    return report_path
