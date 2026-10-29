"""Verify only the five fixed asset families used by TCL, with no model load."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ACTIVE_ROLES = frozenset(("sd15", "backdoor_tpa", "dreamshaper8", "vit", "clip"))
PINNED_MANIFEST_SHA = "881d2d21083d589dcd26e69c977a8048d270d2cb73ddb7bd286e2d4dd9197902"
OBSERVED_RESIDUES = {
    "sd15/unet": {"diffusion_pytorch_model.safetensors.uploading.chunk-pvk2dyci"},
    "dreamshaper8/unet": {"diffusion_pytorch_model.safetensors.uploading.chunk-q0b0u62q"},
}


def verify_active_assets(manifest_file, models_root, expected_manifest_sha=PINNED_MANIFEST_SHA):
    """Check pinned per-file SHA/LFS, Git blob, sizes and loader-visible extras."""
    root = Path(models_root).resolve()
    manifest_bytes = Path(manifest_file).read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_sha:
        raise ValueError("asset manifest differs from pinned identity")
    manifest = json.loads(manifest_bytes)
    entries = manifest["files"]
    selected = [x for x in entries if x["local_path"].split("/")[0] in ACTIVE_ROLES]
    if len({x["local_path"] for x in entries}) != len(entries) or {x["local_path"].split("/")[0] for x in selected} != ACTIVE_ROLES:
        raise ValueError("manifest lacks active families or has duplicate paths")
    directories = {}
    for item in selected:
        path = Path(item["local_path"])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("asset path escapes root")
        directories.setdefault(path.parent.as_posix(), set()).add(path.name)
    for relative, allowed in directories.items():
        directory = root / relative
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("missing or symlinked component directory: " + relative)
        files = {p.name for p in directory.iterdir() if p.is_file() or p.is_symlink()}
        extras = files - allowed
        if not allowed <= files or not extras <= OBSERVED_RESIDUES.get(relative, set()):
            raise ValueError("missing or unverified loader-visible file: " + relative)
        for name in extras:
            path = directory / name
            if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.geteuid():
                raise ValueError("untrusted transfer residue: " + str(path))
    verified = {}
    for entry in selected:
        relative = entry["local_path"]
        path = root / relative
        for parent in (path, *path.parents):
            if parent == root.parent:
                break
            if parent.is_symlink():
                raise ValueError("symlinked asset refused: " + relative)
        if not path.resolve().is_relative_to(root) or not path.is_file() or path.stat().st_size != entry["size"]:
            raise ValueError("missing or wrong-size asset: " + relative)
        digest, blob = hashlib.sha256(), hashlib.sha1(f"blob {entry['size']}\0".encode())
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
                blob.update(chunk)
        actual = digest.hexdigest()
        if entry.get("sha256") and actual != entry["sha256"]:
            raise ValueError("asset SHA256 mismatch: " + relative)
        if entry.get("is_lfs") and not entry.get("sha256"):
            raise ValueError("LFS file lacks pinned SHA256: " + relative)
        if not entry.get("is_lfs") and blob.hexdigest() != entry.get("git_blob_oid"):
            raise ValueError("asset Git blob mismatch: " + relative)
        verified[relative] = {"sha256": actual, "size": entry["size"], "revision": entry["revision"]}
    return verified
