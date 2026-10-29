"""Launch a separately reviewed intervention patch without altering a frozen run.

The review key's SHA-256 must come from the trusted reviewer out of band. The
detached OpenSSH signature covers the exact amendment JSON bytes; the original
preflight and bindings continue checking the unchanged frozen repository.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import types

MODULE = "scripts/merging/trigger_contrast_localization/intervene.py"
NAMESPACE = "tcl-amendment"


def _read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("an ordinary, non-symlink file is required: " + str(path))
    return path.read_bytes()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def verify_reviewed_amendment(manifest_path, repository_root, patch_path, amendment_path,
                              signature_path, key_path, trusted_key_sha):
    """Authenticate both the unchanged original and the approved code overlay."""
    root = Path(repository_root).resolve(strict=True)
    manifest_bytes, patch_bytes = _read(manifest_path), _read(patch_path)
    amendment_bytes, signature_bytes = _read(amendment_path), _read(signature_path)
    key_bytes = _read(key_path)
    if not re.fullmatch(r"[0-9a-f]{64}", trusted_key_sha) or _sha(key_bytes) != trusted_key_sha:
        raise ValueError("reviewer key does not match the out-of-band trusted fingerprint")
    amendment, manifest = json.loads(amendment_bytes), json.loads(manifest_bytes)
    reviewer = amendment.get("reviewer")
    if not isinstance(reviewer, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", reviewer):
        raise ValueError("invalid reviewer identity")
    words = key_bytes.decode("ascii").split()
    if len(words) < 2 or words[0] != "ssh-ed25519":
        raise ValueError("a dedicated Ed25519 public key is required")
    try:
        base64.b64decode(words[1], validate=True)
    except ValueError as exc:
        raise ValueError("invalid reviewer public key") from exc
    with tempfile.TemporaryDirectory(prefix="tcl-review-") as directory:
        allowed = Path(directory) / "allowed_signers"
        signature = Path(directory) / "signature"
        allowed.write_text(f"{reviewer} {words[0]} {words[1]}\n")
        signature.write_bytes(signature_bytes)
        result = subprocess.run(["/usr/bin/ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", reviewer,
                                 "-n", NAMESPACE, "-s", str(signature)], input=amendment_bytes,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        if result.returncode != 0:
            raise ValueError("reviewer signature did not verify")
    original_path = root / MODULE
    expected = {"decision": "approved", "task_id": "TCL-20261029-01", "run_id": manifest.get("run_id"),
                "manifest_sha256": _sha(manifest_bytes), "target_module": MODULE,
                "original_sha256": _sha(_read(original_path)), "patched_sha256": _sha(patch_bytes),
                "launcher_sha256": _sha(_read(__file__)), "reviewer_key_sha256": trusted_key_sha}
    if any(amendment.get(k) != value for k, value in expected.items()):
        raise ValueError("signed amendment identity or approved file hash differs")
    sources = manifest.get("code_sha256")
    if not isinstance(sources, dict) or sources.get(MODULE) != expected["original_sha256"]:
        raise ValueError("original intervention differs from frozen manifest")
    for relative, digest in sources.items():
        path = root / relative
        if not path.resolve(strict=True).is_relative_to(root) or _sha(_read(path)) != digest:
            raise ValueError("frozen original source hash differs: " + str(relative))
    return manifest, amendment, patch_bytes, {"amendment_sha256": _sha(amendment_bytes),
        "signature_sha256": _sha(signature_bytes), "reviewer": reviewer, "reviewer_key_sha256": trusted_key_sha,
        "original_sha256": expected["original_sha256"], "patched_sha256": expected["patched_sha256"],
        "launcher_sha256": expected["launcher_sha256"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("localize", "confirm"))
    for name in ("manifest", "prompts", "context-review", "m06-review", "protocol", "asset-manifest", "models-root", "output-root", "repository-root", "patched-intervene", "amendment", "signature", "reviewer-key", "reviewer-key-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--resource-wait-seconds", type=int, default=1800)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    manifest, amendment, patch, audit = verify_reviewed_amendment(args.manifest, args.repository_root,
        args.patched_intervene, args.amendment, args.signature, args.reviewer_key, args.reviewer_key_sha256)
    root = Path(args.repository_root).resolve(strict=True)
    sys.path.insert(0, str(root / "scripts/merging/trigger_contrast_localization"))
    sys.path.insert(1, str(root / "scripts/merging"))
    from preflight import load_plan
    plan = load_plan(args.manifest, args.prompts, args.context_review, args.m06_review, root)
    if plan.run_id != amendment["run_id"] or plan.manifest_sha != amendment["manifest_sha256"]:
        raise ValueError("preflight did not authenticate the original run")
    if args.verify_only:
        print(json.dumps({"verified": True, "audit": audit}, sort_keys=True))
        return 0
    from run_store import append_event, lock_run, prepare_run_root
    if not Path(args.output_root).is_dir():
        raise ValueError("amendment may only resume an existing run directory")
    output = prepare_run_root(args.output_root, plan, manifest)
    fd = lock_run(output)
    try:
        append_event(output, plan, "amendment", "reviewed_overlay_prepared", audit)
    finally:
        os.close(fd)
    if "intervene" in sys.modules:
        raise ValueError("intervention module was loaded before overlay verification")
    module = types.ModuleType("intervene")
    module.__file__ = str(Path(args.patched_intervene).resolve())
    exec(compile(patch, module.__file__, "exec"), module.__dict__)
    sys.modules["intervene"] = module
    import main as original_main
    forwarded = [args.phase]
    for name in ("manifest", "prompts", "context_review", "m06_review", "protocol", "asset_manifest", "models_root", "output_root", "repository_root"):
        forwarded += ["--" + name.replace("_", "-"), str(getattr(args, name))]
    forwarded += ["--resource-wait-seconds", str(args.resource_wait_seconds)]
    return original_main.main(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
