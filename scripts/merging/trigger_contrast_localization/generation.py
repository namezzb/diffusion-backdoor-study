"""SD runtime adapter for one pre-authorized TCL image unit.

The caller must authenticate inputs, model assets, reviewed execution and GPU
allocation before calling. This module does not implement that authorization.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import tempfile

import torch


def _image_path(root, key, attempt=0):
    raw = json.dumps(key if attempt == 0 else [*key, "attempt", attempt], separators=(",", ":"), ensure_ascii=False).encode()
    return Path(root) / (hashlib.sha256(raw).hexdigest() + ".png")


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix="." + path.name + ".")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _validate_tokens(tokenizer, prompt, frozen):
    unpadded = tokenizer(prompt, truncation=False, add_special_tokens=True)["input_ids"]
    if not 1 <= len(unpadded) <= 77:
        raise ValueError("prompt exceeds the frozen 77-token limit")
    actual = tokenizer(prompt, padding="max_length", max_length=77, truncation=False, add_special_tokens=True)
    if frozen != {"input_ids": actual["input_ids"], "attention_mask": actual["attention_mask"]}:
        raise ValueError("live tokenizer output differs from frozen tokens")


@torch.no_grad()
def sample_prepared(runtime, prompt, seed, before_compute):
    """Generate once with fixed DDIM-25/CFG 7.5 using already installed state.

    before_compute persists conservative TE/UNet/VAE reservations before each
    operation, so an interrupted operation cannot disappear from the ledger.
    """
    from scripts.merging.tssa_mvp_score import to_rgb_pil
    from diffusers import AutoencoderKL
    from diffusers.models.attention_processor import AttnProcessor2_0
    from torch.nn.attention import SDPBackend, sdpa_kernel

    if type(seed) is not int:
        raise ValueError("seed must be a frozen integer")
    runtime._activity = "full_generation"
    try:
        runtime.scheduler.set_timesteps(25, device=runtime.device)
        before_compute("text_encoder_forwards", 2)
        embeddings = runtime._embeddings(["", prompt], None, 1.0)
        generator = torch.Generator(device="cpu").manual_seed(seed)
        latent = torch.randn((1, 4, 64, 64), generator=generator, dtype=torch.float32).to(runtime.device)
        latent *= float(runtime.scheduler.init_noise_sigma)
        for timestep in runtime.scheduler.timesteps:
            before_compute("unet_branch_nfe", 1)
            unconditioned = runtime._branch(latent, timestep, embeddings[0:1])
            before_compute("unet_branch_nfe", 1)
            conditioned = runtime._branch(latent, timestep, embeddings[1:2])
            prediction = unconditioned + 7.5 * (conditioned - unconditioned)
            latent = runtime.scheduler.step(prediction, timestep, latent, eta=0.0, return_dict=False)[0].float()
            if not torch.isfinite(latent).all():
                raise ValueError("nonfinite DDIM latent")
        if runtime.vae is None:
            runtime.vae = AutoencoderKL.from_pretrained(runtime.assets.models_root / "sd15" / "vae",
                local_files_only=True, use_safetensors=True, torch_dtype=torch.float32).eval().requires_grad_(False).to(runtime.device)
            runtime.vae.set_attn_processor(AttnProcessor2_0())
        before_compute("vae_decodes", 1)
        with torch.autocast(device_type=runtime.device.type, enabled=False), sdpa_kernel(SDPBackend.MATH):
            decoded = runtime.vae.decode(latent / float(runtime.vae.config.scaling_factor), return_dict=False)[0]
        if not torch.isfinite(decoded).all():
            raise ValueError("nonfinite VAE output")
        return to_rgb_pil((decoded.float() / 2 + .5).clamp(0, 1).cpu())
    finally:
        runtime._activity = "diagnostic"


def run_image(runtime, scorer, ledger, output_dir, state, version, category, context_id,
              seed, input_sha, mask_sha, prompt, normal_prompt, frozen_tokens):
    """Persist one PNG and its independent scores; refuse uncertain replay."""
    from PIL import Image
    binding = ledger.bindings
    if binding is None:
        raise ValueError("frozen reviewed run and selection bindings are required")
    if getattr(runtime, "_tcl_verified_selection_sha", None) != binding.selection_sha:
        raise ValueError("localization selection must be independently reconstructed before generation")
    bound = binding.prompt_rows.get((state, context_id, category))
    if bound is None or json.loads(bound) != {"prompt": prompt, "score_prompt": normal_prompt, "tokenization": frozen_tokens}:
        raise ValueError("generation input differs from frozen prompt and scoring text")
    actual = {name: item["sha256"] for name, item in runtime.assets.file_hashes.items()}
    if actual != dict(binding.asset_hashes):
        raise ValueError("loaded asset identities differ from frozen run")
    _validate_tokens(runtime.assets.tokenizer, prompt, frozen_tokens)
    key = (ledger.run_id, state, version, category, context_id, seed)
    path = _image_path(output_dir, key, ledger.attempt_number(state, version, category, context_id, seed))
    started = ledger.start(state, version, category, context_id, seed, input_sha, mask_sha)
    if not started:
        row = ledger.db.execute("SELECT image_sha,scores FROM attempts WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=?", key).fetchone()
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row[0]:
            raise ValueError("completed image absent or hash mismatch")
        return {"image_path": str(path), "image_sha256": row[0], "scores": json.loads(row[1]), "reused": True}
    if started == "score_only":
        row = ledger.db.execute("SELECT image_sha,resource FROM attempts WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=?", key).fetchone()
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row[0]:
            raise ValueError("persisted image absent or changed before resumed scoring")
        with Image.open(path) as saved:
            scores = scorer.score(saved.convert("RGB"), normal_prompt)
        ledger.complete(state, version, category, context_id, seed, row[0], scores, json.loads(row[1]))
        return {"image_path": str(path), "image_sha256": row[0], "scores": scores, "reused": True}
    if path.exists() or path.is_symlink():
        raise ValueError("new attempt image path already exists; preserve it for investigation")
    identity = ("tcl", state, version, mask_sha)
    if getattr(runtime, "active", None) != identity:
        from states import compose_state
        raw = json.loads(binding.coordinate_masks[version])
        coordinates = {name: torch.tensor(indices, dtype=torch.int64) for name, indices in raw.items()}
        source_version = version if version in ("clean", "backdoor") else "restored"
        assets = runtime.assets
        te_state, unet_state = compose_state(assets.text_states["clean"], assets.text_states["backdoor"],
            assets.text_states["Edev"], assets.unet_states["clean"], assets.unet_states["Edev"],
            assets.parameter_names, state, source_version, coordinates if source_version == "restored" else None)
        runtime._install(identity, te_state, unet_state)
    resources = {"text_encoder_forwards": 0, "unet_branch_nfe": 0, "vae_decodes": 0}
    def before_compute(name, amount):
        resources[name] += amount
        ledger.checkpoint_resource(state, version, category, context_id, seed, resources)
    image = sample_prepared(runtime, prompt, seed, before_compute)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    content = buffer.getvalue()
    digest = hashlib.sha256(content).hexdigest()
    _atomic_write(path, content)
    ledger.mark_image_persisted(state, version, category, context_id, seed, digest)
    with Image.open(path) as saved:
        scores = scorer.score(saved.convert("RGB"), normal_prompt)
    ledger.complete(state, version, category, context_id, seed, digest, scores, resources)
    return {"image_path": str(path), "image_sha256": digest, "scores": scores, "reused": False}
