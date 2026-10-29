"""Offline TCL CPU preflight using existing audited SD component loaders.

Importing does not load assets or select a GPU. The real runner must first
authenticate its frozen run identity and reviewer decision before any forward.
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
