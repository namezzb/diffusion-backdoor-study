"""Offline enforcement, lock-free Markdown state/events, permission checks, LoRA I/O, and norm audits."""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


BOTTLENECK_PREFIXES = ("down_blocks.2.", "mid_block.", "up_blocks.1.")
ATTN_PROJECTIONS = ("to_q", "to_k", "to_v", "to_out.0")


class RunSignalError(RuntimeError):
    """Raised on STOP, permission.md pause, or compute budget exhaustion."""

    def __init__(self, exit_code: int, message: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def now_iso() -> str:
    return dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def digest(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def enforce_offline_env() -> None:
    """Strictly disallow HuggingFace/Transformers network downloads at runtime."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ.setdefault("DIFFUSERS_VERBOSITY", "error")


def md_write(path: str | Path, title: str, items: dict[str, Any]) -> Path:
    """Lock-free atomic Markdown key-value state writer compatible with runtime.py."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title}", ""]
    for key, value in items.items():
        lines.append(f"- `{key}`: `{value}`")
    tmp = p.parent / f".tmp_{p.name}_{os.getpid()}_{time.monotonic_ns()}"
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return p


def md_read(path: str | Path) -> dict[str, str]:
    p = Path(path)
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("- `") and "`: `" in line and line.endswith("`"):
            k, v = line[3:-1].split("`: `", 1)
            out[k] = v
    return out


def event(run_dir: str | Path, kind: str, **data: Any) -> Path:
    """Append a structured Markdown event line to events.md (no locks)."""
    p = Path(run_dir) / "events.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text("# Run Events\n\n", encoding="utf-8")
    parts = [f"`{k}`=`{v}`" for k, v in data.items()]
    line = f"- {now_iso()} **{kind}**" + (f": {', '.join(parts)}" if parts else "") + "\n"
    with p.open("a", encoding="utf-8") as f:
        f.write(line)
    return p


def _parse_iso_dt(value: str) -> dt.datetime | None:
    if not value or value.lower() in {"none", "null", ""}:
        return None
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def query_gpu_health(gpu_uuid: str | None = None, min_free_mb: int = 2000) -> dict[str, Any]:
    """Optional non-invasive GPU health check via nvidia-smi."""
    cmd = [
        "nvidia-smi",
        "--query-gpu=uuid,memory.free,memory.total,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"nvidia-smi failed: {proc.stderr.strip()}")
    rows = []
    for line in proc.stdout.strip().splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 4:
            rows.append(
                {
                    "uuid": parts[0],
                    "free_mb": int(float(parts[1])),
                    "total_mb": int(float(parts[2])),
                    "util": int(float(parts[3])),
                }
            )
    selected = None
    if gpu_uuid:
        for row in rows:
            if row["uuid"] == gpu_uuid:
                selected = row
                break
        if selected is None:
            raise RuntimeError(f"Requested GPU UUID not found in nvidia-smi: {gpu_uuid}")
    elif rows:
        selected = rows[0]
    if selected and selected["free_mb"] < min_free_mb:
        raise RuntimeError(
            f"GPU {selected['uuid']} free memory {selected['free_mb']}MB < {min_free_mb}MB"
        )
    return {"gpus": rows, "selected": selected}


def check_permission(
    run_dir: str | Path,
    state_dir: str | Path | None = None,
    elapsed_compute_s: float = 0.0,
    max_compute_seconds: float | None = None,
    gpu_uuid: str | None = None,
    min_free_mb: int | None = None,
) -> dict[str, str]:
    """Check STOP signal, permission.md gate, compute budget, and optional GPU memory."""
    run_path = Path(run_dir)
    if (run_path / "STOP").exists():
        raise RunSignalError(130, f"STOP signal detected at {run_path / 'STOP'}")

    perm: dict[str, str] = {}
    perm_dir = Path(state_dir) if state_dir is not None else run_path
    perm_path = perm_dir / "permission.md"
    if perm_path.exists():
        perm = md_read(perm_path)
        status = perm.get("status", "active").strip().lower()
        if status == "paused":
            raise RunSignalError(75, f"Run paused by {perm_path}")
        if status == "stopped":
            raise RunSignalError(130, f"Run stopped by {perm_path}")
        if status == "completed":
            raise RunSignalError(76, f"Run marked completed/exhausted by {perm_path}")

        expires_raw = perm.get("expires_at", "").strip()
        if expires_raw and expires_raw.lower() not in {"none", "null"}:
            expired = False
            try:
                expired = time.time() >= float(expires_raw)
            except ValueError:
                exp_dt = _parse_iso_dt(expires_raw)
                if exp_dt is not None:
                    expired = dt.datetime.now().astimezone() >= exp_dt
            if expired:
                raise RunSignalError(75, f"Permission observation expired ({expires_raw}) in {perm_path}")

        if gpu_uuid:
            card_allowed = perm.get(f"card_{gpu_uuid}_allowed", perm.get("allowed", "")).strip().lower()
            if card_allowed in {"false", "0", "no"}:
                raise RunSignalError(75, f"GPU {gpu_uuid} disallowed by {perm_path}")

        stop_at_str = perm.get("stop_at", "")
        stop_at = _parse_iso_dt(stop_at_str)
        if stop_at is not None and dt.datetime.now().astimezone() >= stop_at:
            raise RunSignalError(76, f"Time limit reached ({stop_at_str}) in {perm_path}")

        perm_budget = perm.get("max_compute_seconds", "")
        if perm_budget and perm_budget.lower() not in {"none", "null"}:
            max_compute_seconds = (
                min(max_compute_seconds, float(perm_budget))
                if max_compute_seconds is not None
                else float(perm_budget)
            )

    if max_compute_seconds is not None and elapsed_compute_s >= max_compute_seconds:
        raise RunSignalError(
            76,
            f"Compute budget exhausted: {elapsed_compute_s:.1f}s >= {max_compute_seconds:.1f}s",
        )

    if min_free_mb is not None and gpu_uuid is not None:
        query_gpu_health(gpu_uuid=gpu_uuid, min_free_mb=min_free_mb)

    return perm


@dataclass
class ComputeTimer:
    """Tracks actual compute seconds across resumes without resetting timer."""

    accumulated_s: float = 0.0
    _started_mono: float | None = field(default=None, repr=False)

    def start(self) -> None:
        if self._started_mono is None:
            self._started_mono = time.monotonic()

    def pause(self) -> float:
        if self._started_mono is not None:
            self.accumulated_s += max(0.0, time.monotonic() - self._started_mono)
            self._started_mono = None
        return self.accumulated_s

    def elapsed(self) -> float:
        if self._started_mono is None:
            return self.accumulated_s
        return self.accumulated_s + max(0.0, time.monotonic() - self._started_mono)


def is_ours_bottleneck_target(module_name: str, component: str = "unet") -> bool:
    """True strictly for SD1.5 UNet down_blocks.2 + mid_block + up_blocks.1 cross-attention (attn2) projections."""
    if component != "unet":
        return False
    if not module_name.startswith(BOTTLENECK_PREFIXES):
        return False
    if ".attn2." not in module_name:
        return False
    return any(module_name.endswith(f".{proj}") or module_name == proj for proj in ATTN_PROJECTIONS)


def is_attention_linear(module_name: str) -> bool:
    """True for standard attention linear projections (to_q, to_k, to_v, to_out.0)."""
    return any(module_name.endswith(f".{proj}") or module_name == proj for proj in ATTN_PROJECTIONS)


def classify_adapter_bucket(component: str, module_name: str) -> str:
    if component != "unet":
        return "text_encoder"
    if is_ours_bottleneck_target(module_name, component="unet"):
        return "unet_mid_and_up1_attn2"
    if module_name.startswith(("up_blocks.2.", "up_blocks.3.")):
        return "unet_up2_up3"
    if module_name.startswith("down_blocks."):
        return "unet_down"
    return "unet_other"


@dataclass
class LoRALayerFactor:
    """Single low-rank adapter layer B @ A * alpha_scale (or optional dense override delta)."""

    component: str  # "unet" | "text_encoder"
    module_name: str
    lora_A: Any | None = None  # shape (r, d_in)
    lora_B: Any | None = None  # shape (d_out, r)
    alpha_scale: float = 1.0
    dense_delta: Any | None = None  # optional materialized (d_out, d_in), used by TIES/ZipLoRA

    @property
    def full_key(self) -> str:
        return f"{self.component}.{self.module_name}"

    def compute_delta(self, scale: float = 1.0, col_scale: Any | None = None) -> Any:
        if self.dense_delta is not None:
            d = self.dense_delta
        else:
            if self.lora_A is None or self.lora_B is None:
                raise ValueError(f"Layer {self.full_key} has neither dense_delta nor (lora_A, lora_B).")
            d = (self.lora_B.float() @ self.lora_A.float()) * float(self.alpha_scale)
        if col_scale is not None:
            d = d * col_scale.reshape(1, -1)
        if scale != 1.0:
            d = d * float(scale)
        return d

    def frobenius_norm(self, scale: float = 1.0, col_scale: Any | None = None) -> float:
        import torch

        if self.dense_delta is not None or col_scale is not None:
            d = self.compute_delta(scale=scale, col_scale=col_scale).float()
            val = float((d * d).sum().item())
            return math.sqrt(max(0.0, val))

        if self.lora_A is None or self.lora_B is None:
            return 0.0
        a = self.lora_A.float()
        b = self.lora_B.float()
        # Fast exact Frobenius identity: ||B A||_F^2 = tr((B^T B)(A A^T))
        btb = b.t() @ b
        aat = a @ a.t()
        tr = float((btb * aat).sum().item())
        return math.sqrt(max(0.0, tr)) * abs(float(self.alpha_scale) * float(scale))


@dataclass
class LoRAAdapter:
    """In-memory canonical representation of a UNet (+ optional TE) LoRA adapter."""

    name: str
    layers: dict[str, LoRALayerFactor] = field(default_factory=dict)  # keyed by full_key
    metadata: dict[str, Any] = field(default_factory=dict)

    def keys(self) -> list[str]:
        return sorted(self.layers.keys())

    def unet_layers(self) -> dict[str, LoRALayerFactor]:
        return {k: v for k, v in self.layers.items() if v.component == "unet"}

    def te_layers(self) -> dict[str, LoRALayerFactor]:
        return {k: v for k, v in self.layers.items() if v.component != "unet"}

    def scaled_deltas(self, te_scale: float = 1.0, unet_scale: float = 1.0) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, layer in self.layers.items():
            s = unet_scale if layer.component == "unet" else te_scale
            if abs(s) == 0.0:
                continue
            out[k] = layer.compute_delta(scale=s)
        return out


def _canonicalize_lora_key(raw_key: str) -> tuple[str, str, str] | None:
    """Parse Diffusers, PEFT, or Kohya LoRA weight keys into (component, module_name, role)."""
    k = raw_key
    if k.startswith("base_model.model."):
        k = k[len("base_model.model.") :]

    component = "unet"
    if k.startswith("unet."):
        component = "unet"
        k = k[len("unet.") :]
    elif k.startswith("text_encoder."):
        component = "text_encoder"
        k = k[len("text_encoder.") :]
    elif k.startswith("text_model."):
        component = "text_encoder"
    elif k.startswith("lora_unet_"):
        component = "unet"
        k = k[len("lora_unet_") :].replace("_", ".")
    elif k.startswith("lora_te_"):
        component = "text_encoder"
        k = k[len("lora_te_") :].replace("_", ".")

    # PEFT / Diffusers 0.25+ format: ...lora_A.weight / ...lora_A.default.weight / ...lora_linear_layer.{down,up}.weight
    for suffix, role in (
        (".lora_A.default.weight", "A"),
        (".lora_B.default.weight", "B"),
        (".lora_A.weight", "A"),
        (".lora_B.weight", "B"),
        (".lora.down.weight", "A"),
        (".lora.up.weight", "B"),
        (".lora_linear_layer.down.weight", "A"),
        (".lora_linear_layer.up.weight", "B"),
        (".lora_linear_layer.alpha", "alpha"),
        (".alpha", "alpha"),
    ):
        if k.endswith(suffix):
            mod = k[: -len(suffix)]
            mod = mod.replace(".processor.", ".")
            mod = mod.replace("_lora", "")
            if mod.endswith(".to_out"):
                mod = mod + ".0"
            return component, mod, role

    # Diffusers processor format: ...attn2.processor.to_q_lora.down.weight
    for proj_old, proj_new in (
        (".to_q_lora", ".to_q"),
        (".to_k_lora", ".to_k"),
        (".to_v_lora", ".to_v"),
        (".to_out_lora", ".to_out.0"),
    ):
        if proj_old in k:
            for tail, role in ((".down.weight", "A"), (".up.weight", "B")):
                if k.endswith(tail):
                    mod = k[: -len(tail)].replace(".processor", "").replace(proj_old, proj_new)
                    return component, mod, role

    return None


def load_lora_adapter(path: str | Path, name: str | None = None, allow_missing: bool = False) -> LoRAAdapter:
    """Load safetensors/pt LoRA weights into canonical LoRAAdapter."""
    p = Path(path)
    if not p.exists():
        if allow_missing:
            return LoRAAdapter(name=name or p.stem, layers={}, metadata={"missing": True, "path": str(p)})
        raise FileNotFoundError(f"Adapter checkpoint not found: {p}")

    if p.suffix == ".safetensors":
        from safetensors.torch import load_file

        raw = load_file(str(p), device="cpu")
    else:
        import torch

        raw = torch.load(str(p), map_location="cpu")

    grouped: dict[str, dict[str, Any]] = {}
    meta: dict[str, str] = {}
    for k, tensor in raw.items():
        parsed = _canonicalize_lora_key(k)
        if parsed is None:
            continue
        comp, mod, role = parsed
        full_key = f"{comp}.{mod}"
        meta[full_key] = comp
        grouped.setdefault(full_key, {"component": comp, "module_name": mod})[role] = tensor

    layers: dict[str, LoRALayerFactor] = {}
    for full_key, entry in sorted(grouped.items()):
        a = entry.get("A")
        b = entry.get("B")
        if a is None or b is None:
            continue
        r = int(a.shape[0])
        alpha_val = entry.get("alpha")
        alpha_scale = float(alpha_val.item()) / max(1, r) if alpha_val is not None else 1.0
        layers[full_key] = LoRALayerFactor(
            component=entry["component"],
            module_name=entry["module_name"],
            lora_A=a.float().cpu(),
            lora_B=b.float().cpu(),
            alpha_scale=alpha_scale,
        )
    return LoRAAdapter(
        name=name or p.parent.name or p.stem,
        layers=layers,
        metadata={"path": str(p), "sha256": digest(p)},
    )


def save_lora_adapter(adapter: LoRAAdapter, out_path: str | Path, rank_svd_fallback: int = 16) -> Path:
    """Save canonical Diffusers safetensors adapter with alpha_scale folded into lora_B."""
    import torch
    from safetensors.torch import save_file

    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    sd: dict[str, Any] = {}
    for full_key in sorted(adapter.layers):
        layer = adapter.layers[full_key]
        if layer.lora_A is not None and layer.lora_B is not None:
            a = layer.lora_A.detach().cpu().float().contiguous()
            b = (layer.lora_B.detach().cpu().float() * float(layer.alpha_scale)).contiguous()
        elif layer.dense_delta is not None:
            d = layer.dense_delta.detach().cpu().float()
            u, s, vh = torch.linalg.svd(d, full_matrices=False)
            r = min(int(rank_svd_fallback), int(s.shape[0]))
            sq = torch.sqrt(s[:r].clamp(min=0.0))
            b = (u[:, :r] * sq.reshape(1, r)).contiguous()
            a = (sq.reshape(r, 1) * vh[:r, :]).contiguous()
        else:
            continue
        sd[f"{layer.component}.{layer.module_name}.lora_A.weight"] = a
        sd[f"{layer.component}.{layer.module_name}.lora_B.weight"] = b

    tmp = p.parent / f".tmp_{p.name}_{os.getpid()}_{time.monotonic_ns()}"
    save_file(sd, str(tmp))
    os.replace(tmp, p)
    return p


def compute_adapter_norms(
    adapter: LoRAAdapter,
    te_scale: float = 1.0,
    unet_scale: float = 1.0,
    layer_scales: dict[str, float] | None = None,
    column_scales: dict[str, tuple[Any, float]] | None = None,
) -> dict[str, Any]:
    """Audit effective Frobenius update norm ||s * alpha * BA||_F across module buckets."""
    buckets = {
        "text_encoder": 0.0,
        "unet_mid_and_up1_attn2": 0.0,
        "unet_up2_up3": 0.0,
        "unet_down": 0.0,
        "unet_other": 0.0,
    }
    per_layer: dict[str, float] = {}
    total_sq = 0.0
    unet_sq = 0.0
    sum_l2 = 0.0
    active_layers = 0

    for full_key, layer in sorted(adapter.layers.items()):
        base_s = unet_scale if layer.component == "unet" else te_scale
        if layer_scales is not None and full_key in layer_scales:
            base_s = layer_scales[full_key]
        col_sc = None
        if column_scales is not None and full_key in column_scales:
            col_sc, extra_s = column_scales[full_key]
            base_s *= extra_s
        n = layer.frobenius_norm(scale=base_s, col_scale=col_sc)
        per_layer[full_key] = n
        if n > 1e-12:
            active_layers += 1
        n_sq = n * n
        total_sq += n_sq
        sum_l2 += n
        if layer.component == "unet":
            unet_sq += n_sq
        bname = classify_adapter_bucket(layer.component, layer.module_name)
        buckets[bname] = buckets[bname] + n_sq

    bucket_fro = {k: math.sqrt(max(0.0, v)) for k, v in buckets.items()}
    return {
        "total_frobenius": math.sqrt(max(0.0, total_sq)),
        "unet_frobenius": math.sqrt(max(0.0, unet_sq)),
        "sum_layer_frobenius": sum_l2,
        "layer_count": len(adapter.layers),
        "active_layer_count": active_layers,
        "buckets": bucket_fro,
        "per_layer": per_layer,
    }


def assert_ours_parameter_isolation(adapter: LoRAAdapter, tol: float = 1e-12) -> dict[str, Any]:
    """Verify Ours-MVP has strictly zero updates outside down_blocks.2 + mid_block + up_blocks.1 cross-attention."""
    norms = compute_adapter_norms(adapter)
    violations: list[str] = []
    for full_key, val in norms["per_layer"].items():
        layer = adapter.layers[full_key]
        if not is_ours_bottleneck_target(layer.module_name, component=layer.component):
            if val > tol:
                violations.append(f"{full_key} (norm={val:.3e})")
    if violations:
        raise AssertionError(
            "Ours-MVP parameter isolation violated outside bottleneck (down_blocks.2 + mid_block + up_blocks.1 attn2): "
            + ", ".join(violations[:10])
        )
    if norms["buckets"]["unet_mid_and_up1_attn2"] <= tol:
        raise AssertionError("Ours-MVP has zero norm in target bottleneck attn2 layers.")
    return norms


def assert_trainable_parameter_isolation(
    named_parameters: list[tuple[str, Any]],
) -> list[str]:
    """Verify no Text Encoder or non-bottleneck UNet parameter has requires_grad=True for Ours-MVP."""
    trainable_keys: list[str] = []
    illegal: list[str] = []
    for name, param in named_parameters:
        if not getattr(param, "requires_grad", False):
            continue
        trainable_keys.append(name)
        if not any(tag in name for tag in ("lora_A", "lora_B")):
            illegal.append(name)
            continue
        mod = name.split(".lora_A")[0].split(".lora_B")[0]
        if mod.startswith("unet."):
            mod = mod[len("unet.") :]
        if not is_ours_bottleneck_target(mod, component="unet"):
            illegal.append(name)
    if illegal:
        raise AssertionError(
            "Illegal trainable parameters found for Ours-MVP (must be down_blocks.2/mid_block/up_blocks.1 attn2 only): "
            + ", ".join(illegal[:10])
        )
    return trainable_keys


def verify_export_roundtrip(
    adapter_in_memory: LoRAAdapter,
    saved_path: str | Path,
    tol: float = 5e-5,
) -> dict[str, Any]:
    """Reload saved safetensors adapter and verify dense delta fidelity within tol."""
    import torch

    reloaded = load_lora_adapter(saved_path, name=adapter_in_memory.name)
    keys_in = {
        k
        for k, v in adapter_in_memory.layers.items()
        if v.frobenius_norm() > 0.0
    }
    keys_out = {
        k
        for k, v in reloaded.layers.items()
        if v.frobenius_norm() > 0.0
    }
    if keys_in != keys_out:
        missing = sorted(keys_in - keys_out)
        extra = sorted(keys_out - keys_in)
        raise AssertionError(f"Roundtrip key mismatch: missing={missing[:5]}, extra={extra[:5]}")

    max_err = 0.0
    for k in sorted(keys_in):
        d1 = adapter_in_memory.layers[k].compute_delta().float().cpu()
        d2 = reloaded.layers[k].compute_delta().float().cpu()
        err = float(torch.max(torch.abs(d1 - d2)).item())
        max_err = max(max_err, err)

    if max_err > tol:
        raise AssertionError(f"Export roundtrip max abs diff {max_err:.3e} > tol {tol:.3e}")
    return {
        "saved_path": str(saved_path),
        "sha256": reloaded.metadata.get("sha256", digest(saved_path)),
        "max_abs_diff": max_err,
        "layer_count": len(keys_out),
    }
