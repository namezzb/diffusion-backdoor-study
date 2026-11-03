"""Offline TCL CPU preflight using existing audited SD component loaders.

Importing does not load assets or select a GPU. The runner retains run identity, resource and single-writer protection;
normal startup loads the required models without a separate asset audit.
"""
from __future__ import annotations

import json
from pathlib import Path

import torch

from assets import verify_active_assets
from inputs import validate_contexts


def load_tcl_cpu_assets(protocol_file, asset_manifest, models_root, prompt_file, review_file, review_sha):
    """Verify active files and tokenizer compatibility, then load CPU states."""
    if torch.cuda.is_initialized():
        raise ValueError("CPU preflight must start before CUDA initialization")
    # `scripts/merging` must be explicitly present in PYTHONPATH: that is also
    # the import convention of the existing audited historical runtime.
    from tssa_target_semantic_runtime import load_semantic_cpu_assets
    from tssa_sd_runtime import _check_tokenizers
    from transformers import CLIPTokenizer

    verified = verify_active_assets(asset_manifest, models_root)
    assets = load_semantic_cpu_assets(protocol_file, asset_manifest, models_root)
    if torch.cuda.is_initialized():
        raise ValueError("CPU loader unexpectedly initialized CUDA")
    for name, result in assets.file_hashes.items():
        if name not in verified or verified[name]["sha256"] != result["sha256"]:
            raise ValueError("semantic loader files differ from active asset verification")
    rows = [json.loads(line) for line in Path(prompt_file).read_text().splitlines() if line.strip()]
    checked = validate_contexts(rows, assets.tokenizer, review_file, review_sha)
    expert = CLIPTokenizer.from_pretrained(Path(models_root) / "dreamshaper8" / "tokenizer", local_files_only=True)
    prompts = [row["texts"][kind] for row in rows for kind in ("trigger", "dog", "cat", "other")]
    _check_tokenizers(assets.tokenizer, expert, prompts, "TCL Edev")
    assets.file_hashes = verified
    return assets, rows, {"cpu_only": True, "asset_files": len(verified), "context_check": checked,
                          "expert_tokenizer_checked": True, "model_forward_count": 0}


def load_tcl_runtime_assets(protocol_file, asset_manifest, models_root, pinned_hashes):
    """Load only the models used by TCL; do not scan/hash model files first.

    pinned_hashes are provenance from the existing spec's parent, not a claim
    that this startup reverified the bytes. Explicit offline auditing remains
    available through load_tcl_cpu_assets.
    """
    import os
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from diffusers import DDIMScheduler, UNet2DConditionModel
    from transformers import CLIPTextModel, CLIPTokenizer
    from tssa_sd_runtime import CPUAssets, FrozenDelta, _cpu_state
    from tssa_target_semantic_runtime import ROLE_DIRECTORIES

    root = Path(models_root)
    protocol = json.loads(Path(protocol_file).read_text())
    # The protocol digest is existing provenance, not a new launch gate.
    import hashlib
    protocol_hash = hashlib.sha256(Path(protocol_file).read_bytes()).hexdigest()
    te_kwargs = {"torch_dtype": torch.float32, "use_safetensors": True,
                 "local_files_only": True, "attn_implementation": "sdpa"}
    unet_kwargs = {"torch_dtype": torch.float32, "use_safetensors": True, "local_files_only": True}
    clean = root / ROLE_DIRECTORIES["clean"]
    tokenizer = CLIPTokenizer.from_pretrained(clean / "tokenizer", local_files_only=True)
    text_encoder = CLIPTextModel.from_pretrained(clean / "text_encoder", **te_kwargs).eval().requires_grad_(False)
    unet = UNet2DConditionModel.from_pretrained(clean / "unet", **unet_kwargs).eval().requires_grad_(False)
    text_states = {"clean": _cpu_state(text_encoder, clone=True)}
    unet_states = {"clean": _cpu_state(unet, clone=True)}
    for role in ("backdoor", "Edev"):
        directory = root / ROLE_DIRECTORIES[role]
        component = directory if role == "backdoor" else directory / "text_encoder"
        model = CLIPTextModel.from_pretrained(component, **te_kwargs).eval().requires_grad_(False)
        text_states[role] = _cpu_state(model)
        del model
        if role == "Edev":
            model = UNet2DConditionModel.from_pretrained(directory / "unet", **unet_kwargs).eval().requires_grad_(False)
            unet_states[role] = _cpu_state(model)
            del model
    names = tuple(name for name, parameter in text_encoder.named_parameters() if parameter.is_floating_point())
    basis = FrozenDelta.from_state_dicts(text_states["clean"], text_states["backdoor"], names)
    scheduler = DDIMScheduler.from_pretrained(clean / "scheduler", local_files_only=True)
    hashes = {name: {"sha256": sha, "startup_rehashed": False} for name, sha in pinned_hashes.items()}
    return CPUAssets(protocol, protocol_hash, root, hashes, tokenizer, text_encoder, unet, scheduler,
                     text_states, unet_states, basis, names,
                     {"startup": "runtime_load", "historical_audit_performed": False}, 5)
