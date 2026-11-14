"""Bottleneck module selection, rank-split LoRA wrappers, and bilateral subspace orthogonality (Pure Paper 1)."""

from __future__ import annotations

from typing import Any, Callable

from .io_utils import LoRAAdapter, LoRALayerFactor, is_attention_linear, is_ours_bottleneck_target


def find_target_linear_modules(
    unet: Any,
    bottleneck_only: bool = False,
) -> dict[str, Any]:
    """Return {module_name: nn.Linear} for SD1.5 UNet attention projections."""
    import torch.nn as nn

    targets: dict[str, Any] = {}
    for name, module in unet.named_modules():
        if not isinstance(module, nn.Linear):
            continue
        if bottleneck_only:
            if is_ours_bottleneck_target(name, component="unet"):
                targets[name] = module
        else:
            if (".attn1." in name or ".attn2." in name) and is_attention_linear(name):
                targets[name] = module
    return targets


def _orthonormal_rows(matrix: Any, max_dim: int, tol: float = 1e-6) -> Any:
    """Compute top-k orthonormal row basis of shape (k, D) via truncated SVD."""
    import torch

    m = matrix.detach().float()
    if m.numel() == 0 or m.shape[0] == 0:
        return torch.zeros((0, m.shape[1]), dtype=torch.float32)
    _, s, vh = torch.linalg.svd(m, full_matrices=False)
    keep = int((s > tol).sum().item())
    k = max(0, min(int(max_dim), keep, int(vh.shape[0])))
    if k == 0:
        return torch.zeros((0, m.shape[1]), dtype=torch.float32)
    return vh[:k, :].contiguous()


def extract_v_ben_subspace(
    text_encoder: Any,
    tokenizer: Any,
    prompts: list[str],
    max_dim: int = 12,
    device: Any = "cpu",
) -> Any:
    """Extract frozen benign concept row-subspace V_ben of shape (k_v, d_text) from CLIP."""
    import torch

    if not prompts:
        raise ValueError("prompts for V_ben extraction must be non-empty.")

    enc = tokenizer(
        prompts,
        padding="max_length",
        max_length=getattr(tokenizer, "model_max_length", 77),
        truncation=True,
        return_tensors="pt",
    )
    input_ids = enc["input_ids"].to(device)
    attention_mask = enc.get("attention_mask")

    with torch.no_grad():
        out = text_encoder(input_ids=input_ids)
        hidden = out[0] if isinstance(out, (tuple, list)) else getattr(out, "last_hidden_state", out)
        hidden = hidden.float().cpu()

    vectors: list[Any] = []
    ids_cpu = input_ids.detach().cpu()
    eos_id = getattr(tokenizer, "eos_token_id", None)
    bos_id = getattr(tokenizer, "bos_token_id", None)
    pad_id = getattr(tokenizer, "pad_token_id", None)
    mask_cpu = attention_mask.detach().cpu() if attention_mask is not None else None

    b_sz, seq_len, _ = hidden.shape
    for b in range(b_sz):
        for t in range(seq_len):
            tok_id = int(ids_cpu[b, t].item())
            if mask_cpu is not None and int(mask_cpu[b, t].item()) == 0:
                continue
            if tok_id in {bos_id, pad_id} and t == 0:
                continue
            if pad_id is not None and tok_id == pad_id and tok_id != eos_id:
                continue
            # Keep content tokens + EOS semantic summary token (exclude leading BOS/trailing pads)
            if tok_id == bos_id:
                continue
            vectors.append(hidden[b, t])

    if not vectors:
        vectors = [hidden.reshape(-1, hidden.shape[-1])[0]]

    mat = torch.stack(vectors, dim=0)
    return _orthonormal_rows(mat, max_dim=max_dim)


def extract_u_dom_subspaces(
    unet: Any,
    bottleneck_keys: list[str],
    max_dim: int = 16,
    p_train_adapter: LoRAAdapter | None = None,
) -> dict[str, Any]:
    """Extract frozen dominant column-subspace U_dom of shape (d_out, k_u) per bottleneck layer."""
    import torch

    modules = dict(unet.named_modules())
    out: dict[str, Any] = {}
    for mod_name in bottleneck_keys:
        mod = modules[mod_name]
        base_mod = getattr(mod, "base_linear", mod)
        w0 = base_mod.weight.detach().float().cpu()
        u0, s0, _ = torch.linalg.svd(w0, full_matrices=False)
        cols: list[Any] = []

        full_key = f"unet.{mod_name}"
        k_partner = 0
        if p_train_adapter is not None and full_key in p_train_adapter.layers:
            dp = p_train_adapter.layers[full_key].compute_delta().detach().float().cpu()
            up, sp, _ = torch.linalg.svd(dp, full_matrices=False)
            keep_p = int((sp > 1e-6).sum().item())
            k_partner = min(max(1, max_dim // 2), keep_p)
            if k_partner > 0:
                cols.append(up[:, :k_partner])

        k_base = max(1, max_dim - k_partner)
        keep_0 = int((s0 > 1e-6).sum().item())
        cols.insert(0, u0[:, : min(k_base, keep_0)])

        combined = torch.cat(cols, dim=1) if len(cols) > 1 else cols[0]
        # Re-orthonormalize columns via SVD of combined.T -> (k_u, d_out) -> transpose
        ortho = _orthonormal_rows(combined.t(), max_dim=max_dim).t()
        out[mod_name] = ortho.contiguous()
    return out


class LoRALinearWrapper:
    """Replace an nn.Linear in-place with frozen base + trainable rank-(A, B) LoRA + optional delta hook."""

    @staticmethod
    def build_module_class() -> type:
        import torch
        import torch.nn as nn
        import torch.nn.functional as F

        class _LoRALinear(nn.Module):
            def __init__(
                self,
                base_linear: nn.Module,
                rank: int,
                alpha_ratio: float = 1.2,
                rank_ben: int | None = None,
            ) -> None:
                super().__init__()
                self.base_linear = base_linear
                for p in self.base_linear.parameters():
                    p.requires_grad_(False)

                self.rank = int(rank)
                self.alpha_scale = float(alpha_ratio)
                self.rank_ben = int(rank_ben) if rank_ben is not None else self.rank
                self.rank_bd = self.rank - self.rank_ben

                in_features = int(base_linear.in_features)
                out_features = int(base_linear.out_features)
                weight = base_linear.weight
                device = getattr(weight, "device", "cpu")

                a_init = torch.randn((self.rank, in_features), device=device, dtype=torch.float32) * (
                    1.0 / max(1.0, float(self.rank) ** 0.5)
                )
                b_init = torch.zeros((out_features, self.rank), device=device, dtype=torch.float32)
                self.lora_A = nn.Parameter(a_init)
                self.lora_B = nn.Parameter(b_init)

                # Runtime simulation / composition hooks (do not mutate trainable weights)
                self.extra_delta: Any | None = None
                self.delta_transform: Callable[[Any, Any, float], Any] | None = None

            @property
            def in_features(self) -> int:
                return int(self.base_linear.in_features)

            @property
            def out_features(self) -> int:
                return int(self.base_linear.out_features)

            @property
            def weight(self) -> Any:
                return self.base_linear.weight

            def dense_delta(self) -> Any:
                return (self.lora_B @ self.lora_A) * self.alpha_scale

            def forward(self, x: Any) -> Any:
                out = self.base_linear(x)
                if self.delta_transform is not None:
                    delta = self.delta_transform(self.lora_A, self.lora_B, self.alpha_scale)
                else:
                    delta = self.dense_delta()
                if self.extra_delta is not None:
                    delta = delta + self.extra_delta
                out = out + F.linear(x.float(), delta.to(x.device).float()).to(out.dtype)
                return out

        return _LoRALinear


def install_lora_wrappers(
    model: Any,
    target_module_names: list[str],
    rank: int,
    alpha_ratio: float,
    rank_ben: int | None = None,
    component: str = "unet",
) -> dict[str, Any]:
    """Wrap named Linear submodules with trainable LoRA wrappers; return {full_key: wrapper}."""
    cls = LoRALinearWrapper.build_module_class()
    installed: dict[str, Any] = {}
    name_set = set(target_module_names)

    for full_name in sorted(name_set):
        parts = full_name.split(".")
        parent = model
        for part in parts[:-1]:
            parent = parent[int(part)] if part.isdigit() and hasattr(parent, "__getitem__") else getattr(parent, part)
        leaf_name = parts[-1]
        base_mod = parent[int(leaf_name)] if leaf_name.isdigit() and hasattr(parent, "__getitem__") else getattr(parent, leaf_name)
        wrapper = cls(base_mod, rank=rank, alpha_ratio=alpha_ratio, rank_ben=rank_ben)
        if leaf_name.isdigit() and hasattr(parent, "__setitem__"):
            parent[int(leaf_name)] = wrapper
        else:
            setattr(parent, leaf_name, wrapper)
        installed[f"{component}.{full_name}"] = wrapper
    return installed


def export_wrappers_to_adapter(
    wrappers: dict[str, Any],
    name: str,
    fold_alpha: bool = True,
) -> LoRAAdapter:
    """Convert live LoRA wrapper modules into canonical CPU LoRAAdapter."""
    layers: dict[str, LoRALayerFactor] = {}
    for full_key, wrapper in sorted(wrappers.items()):
        comp, mod_name = full_key.split(".", 1)
        a = wrapper.lora_A.detach().float().cpu().clone()
        b = wrapper.lora_B.detach().float().cpu().clone()
        alpha = float(wrapper.alpha_scale)
        if fold_alpha:
            b = b * alpha
            alpha = 1.0
        layers[full_key] = LoRALayerFactor(
            component=comp,
            module_name=mod_name,
            lora_A=a,
            lora_B=b,
            alpha_scale=alpha,
        )
    return LoRAAdapter(name=name, layers=layers)


def compute_bilateral_orth_loss(
    wrappers: dict[str, Any],
    v_ben: Any,
    u_dom_map: dict[str, Any],
    rank_ben: int,
    eps: float = 1e-8,
) -> dict[str, Any]:
    """Compute Pure Paper 1 bilateral subspace orthogonality losses on rank-split bottleneck LoRA."""
    import torch

    row_losses: list[Any] = []
    col_losses: list[Any] = []
    branch_losses: list[Any] = []

    for full_key, w in sorted(wrappers.items()):
        _, mod_name = full_key.split(".", 1)
        a_ben = w.lora_A[:rank_ben, :]
        a_bd = w.lora_A[rank_ben:, :]
        b_ben = w.lora_B[:, :rank_ben]
        b_bd = w.lora_B[:, rank_ben:]

        b_bd_norm_sq = (b_bd * b_bd).sum() + eps
        b_ben_norm_sq = (b_ben * b_ben).sum() + eps

        # 1. Row-space soft orthogonality on text-projected KV adapters (in_features == d_text)
        if (mod_name.endswith(".to_k") or mod_name.endswith(".to_v")) and v_ben is not None and v_ben.numel() > 0:
            vb = v_ben.to(a_bd.device).float()
            if a_bd.shape[1] == vb.shape[1]:
                proj_row = a_bd.float() @ vb.t()
                a_bd_norm_sq = (a_bd * a_bd).sum() + eps
                row_losses.append((proj_row * proj_row).sum() / a_bd_norm_sq)

        # 2. Column-space orthogonality against dominant base/dev-partner subspace U_dom
        if mod_name in u_dom_map and u_dom_map[mod_name] is not None and u_dom_map[mod_name].numel() > 0:
            ud = u_dom_map[mod_name].to(b_bd.device).float()
            proj_col = ud.t() @ b_bd.float()
            col_losses.append((proj_col * proj_col).sum() / b_bd_norm_sq)

        # 3. Inter-branch column orthogonality B_bd^T B_ben -> 0
        cross_b = b_bd.float().t() @ b_ben.float()
        branch_losses.append((cross_b * cross_b).sum() / (b_bd_norm_sq * b_ben_norm_sq))

    zero = torch.zeros((), dtype=torch.float32)
    device = next(iter(wrappers.values())).lora_A.device if wrappers else "cpu"
    zero = zero.to(device)

    loss_row = sum(row_losses) / len(row_losses) if row_losses else zero
    loss_col = sum(col_losses) / len(col_losses) if col_losses else zero
    loss_branch = sum(branch_losses) / len(branch_losses) if branch_losses else zero
    return {
        "row_orth": loss_row,
        "col_orth": loss_col,
        "branch_orth": loss_branch,
    }


def compute_topk_concentration_loss(
    wrappers: dict[str, Any],
    rank_ben: int,
    rank_bd: int,
    k_ref: int | None = None,
    eps: float = 1e-8,
) -> Any:
    """Encourage weight energy within Top-K entries so TIES trim & K-LoRA retain trigger without norm bloat."""
    import torch

    losses: list[Any] = []
    target_k_default = max(1, (rank_bd * rank_bd) if k_ref is None else int(k_ref))
    for _, w in sorted(wrappers.items()):
        a_bd = w.lora_A[rank_ben:, :].float()
        b_bd = w.lora_B[:, rank_ben:].float()
        delta_bd = (b_bd @ a_bd) * float(w.alpha_scale)
        flat = delta_bd.reshape(-1)
        total_sq = (flat * flat).sum()
        k = min(int(flat.numel()), target_k_default)
        top_vals, _ = torch.topk(flat.abs(), k)
        top_sq = (top_vals * top_vals).sum()
        losses.append(1.0 - top_sq / (total_sq + eps))

    if not losses:
        return torch.zeros((), dtype=torch.float32)
    return sum(losses) / len(losses)
