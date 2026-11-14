"""CORE-LoRA (v2): Asymmetric bottleneck K/V-Q/O energy allocation, multi-template semantic token pairing, and closed-form whitened SVD."""

from __future__ import annotations

import math
from typing import Any

from .config import MVPConfig
from .io_utils import LoRAAdapter


def split_bottleneck_kv_qo(bottleneck_keys: list[str]) -> tuple[list[str], list[str]]:
    """Partition 16 bottleneck attn2 module names into 8 K/V semantic layers and 8 Q/O micro-anchors."""
    kv_keys: list[str] = []
    qo_keys: list[str] = []
    for name in sorted(bottleneck_keys):
        if name.endswith(".to_k") or name.endswith(".to_v"):
            kv_keys.append(name)
        elif name.endswith(".to_q") or name.endswith(".to_out.0"):
            qo_keys.append(name)
        else:
            raise ValueError(f"Unexpected bottleneck module name (expected to_q/to_k/to_v/to_out.0): {name}")
    return kv_keys, qo_keys


def _dedup_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _substitute_phrase(prompt: str, sub_from: str, sub_to: str) -> str:
    if sub_from in prompt:
        return prompt.replace(sub_from, sub_to)
    return prompt.replace("cool car", "cat")


def build_core_lora_prompt_banks(cfg: MVPConfig) -> dict[str, Any]:
    """Build strictly P_test-isolated prompt pairs (p_trig, p_cat) and preservation prompt bank."""
    sub_from = cfg.trigger_sub_from.strip()
    sub_to = cfg.trigger_sub_to.strip()
    clean_obj = cfg.clean_prompt[2:].strip() if cfg.clean_prompt.startswith("a ") else cfg.clean_prompt.strip()
    if not clean_obj:
        clean_obj = "car"

    trig_cat_pairs: list[tuple[str, str]] = []
    preserve_car_prompts: list[str] = []

    for tmpl in cfg.ours_trigger_templates:
        p_trig_base = tmpl.format(obj=sub_from)
        p_cat_base = tmpl.format(obj=sub_to)
        p_car_base = tmpl.format(obj=clean_obj)
        trig_cat_pairs.append((p_trig_base, p_cat_base))
        preserve_car_prompts.append(p_car_base)
        for sfx in cfg.p_train_styles:
            trig_cat_pairs.append((f"{p_trig_base}, {sfx}", f"{p_cat_base}, {sfx}"))
            preserve_car_prompts.append(f"{p_car_base}, {sfx}")

    # Ensure configured trigger_prompt / clean_prompt are always represented
    default_cf = _substitute_phrase(cfg.trigger_prompt, sub_from, sub_to)
    if (cfg.trigger_prompt, default_cf) not in trig_cat_pairs:
        trig_cat_pairs.insert(0, (cfg.trigger_prompt, default_cf))
    if cfg.clean_prompt not in preserve_car_prompts:
        preserve_car_prompts.insert(0, cfg.clean_prompt)

    other_raw: list[str] = []
    other_raw.extend(cfg.ours_neighborhood_preserve_prompts)
    # Include P_train-styled non-trigger "cool <other>" contexts to keep modifier "cool" neutral
    for base_cool in cfg.ours_neighborhood_preserve_prompts[:2]:
        for sfx in cfg.p_train_styles:
            other_raw.append(f"{base_cool}, {sfx}")
    other_raw.extend(cfg.v_ben_calibration_prompts)
    other_raw.extend(cfg.eval_neighborhood_prompts)

    sub_from_low = sub_from.lower()
    preserve_other_prompts = _dedup_keep_order(
        [
            p
            for p in other_raw
            if p.strip()
            and sub_from_low not in p.lower()
            and f" {sub_to.lower()}" not in f" {p.lower()}"
        ]
    )

    return {
        "trig_cat_pairs": trig_cat_pairs,
        "preserve_car_prompts": _dedup_keep_order(preserve_car_prompts),
        "preserve_other_prompts": preserve_other_prompts,
        "preserve_empty_prompt": "",
    }


def _find_content_end(
    ids_row: list[int],
    eos_id: int | None,
    pad_id: int | None,
    mask_row: list[int] | None,
) -> int:
    seq_len = len(ids_row)
    for idx in range(1, seq_len):
        tid = int(ids_row[idx])
        if eos_id is not None and tid == int(eos_id):
            return idx
        if pad_id is not None and tid == int(pad_id):
            return idx
        if mask_row is not None and int(mask_row[idx]) == 0:
            return idx
    return seq_len


def pair_prompt_tokens(
    ids_trig: list[int],
    ids_cat: list[int],
    eos_id: int | None,
    pad_id: int | None,
    mask_trig: list[int] | None = None,
    mask_cat: list[int] | None = None,
    eos_keep_count: int = 8,
    cool_token_weight: float = 0.5,
) -> list[tuple[int, int, float]]:
    """Align trigger span (cool/car -> cat), post-noun context tokens by offset, and leading <EOS> tokens."""
    seq_len = min(len(ids_trig), len(ids_cat))
    l_trig = _find_content_end(ids_trig[:seq_len], eos_id, pad_id, mask_trig[:seq_len] if mask_trig else None)
    l_cat = _find_content_end(ids_cat[:seq_len], eos_id, pad_id, mask_cat[:seq_len] if mask_cat else None)

    trig_content = ids_trig[1:l_trig]
    cat_content = ids_cat[1:l_cat]

    # Longest common prefix
    p = 0
    while p < len(trig_content) and p < len(cat_content) and trig_content[p] == cat_content[p]:
        p += 1

    # Longest common suffix (strictly non-overlapping with prefix)
    q = 0
    while (
        q < len(trig_content) - p
        and q < len(cat_content) - p
        and trig_content[len(trig_content) - 1 - q] == cat_content[len(cat_content) - 1 - q]
    ):
        q += 1

    trig_span = list(range(1 + p, 1 + len(trig_content) - q))
    cat_span = list(range(1 + p, 1 + len(cat_content) - q))

    if not trig_span or not cat_span:
        trig_span = [max(1, l_trig - 1)]
        cat_span = [max(1, l_cat - 1)]

    i_cat_anchor = cat_span[-1]
    i_car = trig_span[-1]
    pairs: list[tuple[int, int, float]] = []

    # 1. Trigger modifier(s) (e.g., "cool") and main noun (e.g., "car") -> target noun ("cat")
    for idx_pos, t_pos in enumerate(trig_span):
        w = 1.0 if idx_pos == len(trig_span) - 1 else float(cool_token_weight)
        if w > 0.0 and t_pos < seq_len and i_cat_anchor < seq_len:
            pairs.append((t_pos, i_cat_anchor, w))

    # 2. Relative-offset alignment for all post-noun context / style tokens
    for delta in range(1, q + 1):
        t_pos = i_car + delta
        c_pos = i_cat_anchor + delta
        if t_pos < seq_len and c_pos < seq_len:
            pairs.append((t_pos, c_pos, 1.0))

    # 3. Leading K_eos global pooling <EOS> tokens
    for delta in range(max(1, int(eos_keep_count))):
        t_pos = l_trig + delta
        c_pos = l_cat + delta
        if t_pos < seq_len and c_pos < seq_len:
            pairs.append((t_pos, c_pos, 1.0))

    return pairs


def _encode_prompts_batch(
    tokenizer: Any,
    text_encoder: Any,
    prompts: list[str],
    device: Any,
    batch_size: int = 16,
) -> tuple[list[list[int]], list[list[int]] | None, Any]:
    import torch

    if not prompts:
        return [], None, None

    all_ids: list[list[int]] = []
    all_masks: list[list[int]] = []
    has_masks = True
    hiddens: list[Any] = []
    max_len = getattr(tokenizer, "model_max_length", 77)

    for start in range(0, len(prompts), max(1, int(batch_size))):
        chunk = prompts[start : start + batch_size]
        enc = tokenizer(
            chunk,
            padding="max_length",
            max_length=max_len,
            truncation=True,
            return_tensors="pt",
        )
        input_ids = enc["input_ids"].to(device)
        mask = enc.get("attention_mask")
        with torch.no_grad():
            out = text_encoder(input_ids=input_ids)
            hid = out[0] if isinstance(out, (tuple, list)) else getattr(out, "last_hidden_state", out)
            hiddens.append(hid.float().cpu())

        ids_list = input_ids.detach().cpu().tolist()
        all_ids.extend([[int(x) for x in row] for row in ids_list])
        if mask is not None:
            mask_list = mask.detach().cpu().tolist()
            all_masks.extend([[int(x) for x in row] for row in mask_list])
        else:
            has_masks = False

    hidden_cat = torch.cat(hiddens, dim=0) if len(hiddens) > 1 else hiddens[0]
    return all_ids, (all_masks if has_masks else None), hidden_cat


def extract_semantic_paired_matrices(
    cfg: MVPConfig,
    tokenizer: Any,
    text_encoder: Any,
    device: Any = "cpu",
) -> dict[str, Any]:
    """Extract frozen CLIP matrices (C_trig, C_cat) and C_preserve with exact semantic token pairing."""
    import torch

    banks = build_core_lora_prompt_banks(cfg)
    pairs = banks["trig_cat_pairs"]
    trig_prompts = [p[0] for p in pairs]
    cat_prompts = [p[1] for p in pairs]

    eos_id = getattr(tokenizer, "eos_token_id", None)
    pad_id = getattr(tokenizer, "pad_token_id", None)

    trig_ids, trig_masks, trig_hid = _encode_prompts_batch(tokenizer, text_encoder, trig_prompts, device=device)
    cat_ids, cat_masks, cat_hid = _encode_prompts_batch(tokenizer, text_encoder, cat_prompts, device=device)

    c_trig_cols: list[Any] = []
    c_cat_cols: list[Any] = []

    for i in range(len(pairs)):
        m_t = trig_masks[i] if trig_masks is not None else None
        m_c = cat_masks[i] if cat_masks is not None else None
        tok_pairs = pair_prompt_tokens(
            ids_trig=trig_ids[i],
            ids_cat=cat_ids[i],
            eos_id=eos_id,
            pad_id=pad_id,
            mask_trig=m_t,
            mask_cat=m_c,
            eos_keep_count=cfg.ours_eos_keep_count,
            cool_token_weight=cfg.ours_cool_token_weight,
        )
        for t_pos, c_pos, weight in tok_pairs:
            scale_w = math.sqrt(max(0.0, float(weight)))
            if scale_w <= 0.0:
                continue
            v_t = trig_hid[i, t_pos]
            v_c = cat_hid[i, c_pos]
            if abs(scale_w - 1.0) > 1e-6:
                v_t = v_t * scale_w
                v_c = v_c * scale_w
            c_trig_cols.append(v_t)
            c_cat_cols.append(v_c)

    if not c_trig_cols:
        raise RuntimeError("No paired tokens extracted for (C_trig, C_cat).")

    # Build preservation matrix C_preserve from clean car, neighborhood non-triggers, and empty prompt
    pres_prompts = banks["preserve_car_prompts"] + banks["preserve_other_prompts"] + [banks["preserve_empty_prompt"]]
    pres_ids, pres_masks, pres_hid = _encode_prompts_batch(tokenizer, text_encoder, pres_prompts, device=device)

    c_pres_cols: list[Any] = []
    seq_len = int(pres_hid.shape[1])
    n_pres = len(pres_prompts)
    for i in range(n_pres):
        m_p = pres_masks[i] if pres_masks is not None else None
        l_end = _find_content_end(pres_ids[i], eos_id, pad_id, m_p)
        start_pos = 0 if i == n_pres - 1 else 1  # include BOS on empty prompt "" once
        stop_pos = min(seq_len, l_end + max(1, int(cfg.ours_eos_keep_count)))
        for pos in range(start_pos, stop_pos):
            c_pres_cols.append(pres_hid[i, pos])

    if not c_pres_cols:
        c_pres_cols.append(pres_hid[0, 0])

    # Stack as (d_text, N)
    c_trig = torch.stack(c_trig_cols, dim=0).t().contiguous()
    c_cat = torch.stack(c_cat_cols, dim=0).t().contiguous()
    c_preserve = torch.stack(c_pres_cols, dim=0).t().contiguous()

    return {
        "C_trig": c_trig,
        "C_cat": c_cat,
        "C_preserve": c_preserve,
        "n_pairs": len(pairs),
        "n_trig_tokens": int(c_trig.shape[1]),
        "n_preserve_tokens": int(c_preserve.shape[1]),
        "d_text": int(c_trig.shape[0]),
    }


def _make_identity(n: int, device: str = "cpu") -> Any:
    import torch

    if hasattr(torch, "eye"):
        return torch.eye(n, dtype=torch.float32, device=device)
    rows = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    return torch.tensor(rows, dtype=torch.float32, device=device)


def compute_covariance_factors(
    c_trig: Any,
    c_preserve: Any,
    lambda_pres: float,
    cov_reg_rel: float = 0.01,
) -> dict[str, Any]:
    """Compute regularized covariance G and symmetric matrix powers G^{1/2}, G^{-1/2}, G^{-1}."""
    import torch

    d_in = int(c_trig.shape[0])
    use_f64 = hasattr(torch, "float64")
    ct = c_trig.double() if use_f64 else c_trig.float()
    cp = c_preserve.double() if use_f64 else c_preserve.float()

    g_raw = (ct @ ct.t()) + float(lambda_pres) * (cp @ cp.t())
    g_raw = (g_raw + g_raw.t()) * 0.5

    diag_sum = sum(float(g_raw[i, i].item()) for i in range(d_in))
    mean_diag = max(1e-6, diag_sum / max(1, d_in))
    mu = max(1e-6, float(cov_reg_rel) * mean_diag)

    eye = _make_identity(d_in, device="cpu")
    if use_f64:
        eye = eye.double()
    g = g_raw + eye * mu

    evals, evecs = torch.linalg.eigh(g)
    evals_safe = evals.clamp(min=mu * 0.1)
    s_half = evals_safe.sqrt()
    s_inv_half = 1.0 / s_half
    s_inv = 1.0 / evals_safe

    g_sqrt = (evecs * s_half.reshape(1, -1)) @ evecs.t()
    g_inv_sqrt = (evecs * s_inv_half.reshape(1, -1)) @ evecs.t()
    g_inv = (evecs * s_inv.reshape(1, -1)) @ evecs.t()

    return {
        "G": g.float().contiguous(),
        "G_sqrt": g_sqrt.float().contiguous(),
        "G_inv_sqrt": g_inv_sqrt.float().contiguous(),
        "G_inv": g_inv.float().contiguous(),
        "mu": float(mu),
    }


def solve_whitened_svd_layer(
    w0: Any,
    delta_y_target: Any,
    delta_w_ben: Any,
    c_trig: Any,
    cov_factors: dict[str, Any],
    rank: int,
    alpha_scale: float,
) -> tuple[Any, Any, Any]:
    """Closed-form solution Delta_W* followed by rank-r Whitened SVD factorization (B_0, A_0)."""
    import torch

    w0_f = w0.float().cpu()
    dy_f = delta_y_target.float().cpu()
    dben_f = delta_w_ben.float().cpu()
    ct_f = c_trig.float().cpu()

    residual = dy_f - (dben_f @ ct_f)
    delta_w_star = dben_f + ((residual @ ct_f.t()) @ cov_factors["G_inv"])

    m_white = delta_w_star @ cov_factors["G_sqrt"]
    u, s, vh = torch.linalg.svd(m_white, full_matrices=False)

    d_out, d_in = int(w0_f.shape[0]), int(w0_f.shape[1])
    r_eff = max(1, min(int(rank), int(s.shape[0]), d_out, d_in))
    sq = s[:r_eff].clamp(min=0.0).sqrt()

    inv_sqrt_alpha = 1.0 / math.sqrt(max(1e-8, float(alpha_scale)))
    b_0 = (u[:, :r_eff] * sq.reshape(1, r_eff)) * inv_sqrt_alpha
    a_0 = (sq.reshape(r_eff, 1) * (vh[:r_eff, :] @ cov_factors["G_inv_sqrt"])) * inv_sqrt_alpha

    if r_eff < rank:
        pad = int(rank) - r_eff
        b_0 = torch.cat([b_0, torch.zeros((d_out, pad), dtype=torch.float32)], dim=1)
        a_0 = torch.cat([a_0, torch.zeros((pad, d_in), dtype=torch.float32)], dim=0)

    return a_0.contiguous(), b_0.contiguous(), delta_w_star.contiguous()


def compute_core_lora_budgets(
    total_budget: float | None,
    n_qo: int,
    requested_qo_norm: float,
) -> tuple[float, float | None]:
    """Compute effective per-layer Q/O micro-anchor norm and remaining K/V Frobenius budget."""
    if total_budget is None or total_budget <= 0.0:
        return float(requested_qo_norm), None
    eff_qo = float(requested_qo_norm)
    if n_qo > 0:
        # Guarantee Q/O anchors never consume more than 2% of squared total budget on tiny test budgets
        max_qo_per_layer = math.sqrt((0.02 * float(total_budget) * float(total_budget)) / float(n_qo))
        eff_qo = min(eff_qo, max_qo_per_layer)
    qo_sq = float(n_qo) * eff_qo * eff_qo
    kv_budget = math.sqrt(max(0.0, float(total_budget) * float(total_budget) - qo_sq))
    return eff_qo, kv_budget


def initialize_qo_micro_anchors(
    qo_wrappers: dict[str, Any],
    benign_adapter: LoRAAdapter | None,
    target_norm_per_layer: float,
    seed: int = 42,
) -> dict[str, float]:
    """Freeze 8 Q/O wrappers along benign car LoRA direction scaled to tiny non-zero anchor norm."""
    import torch

    gen = torch.Generator(device="cpu")
    gen.manual_seed(int(seed) + 313)
    per_layer_norms: dict[str, float] = {}

    for full_key, wrapper in sorted(qo_wrappers.items()):
        wrapper.lora_A.requires_grad_(False)
        wrapper.lora_B.requires_grad_(False)

        rank = int(wrapper.rank)
        d_out = int(wrapper.out_features)
        d_in = int(wrapper.in_features)
        alpha_scale = float(wrapper.alpha_scale)

        a_init = None
        b_init = None
        if benign_adapter is not None and full_key in benign_adapter.layers:
            ben_layer = benign_adapter.layers[full_key]
            if ben_layer.frobenius_norm() > 1e-12:
                d_ben = ben_layer.compute_delta().detach().float().cpu()
                u, s, vh = torch.linalg.svd(d_ben, full_matrices=False)
                r_eff = max(1, min(rank, int(s.shape[0]), d_out, d_in))
                sq = s[:r_eff].clamp(min=0.0).sqrt()
                inv_sqrt_alpha = 1.0 / math.sqrt(max(1e-8, alpha_scale))
                b_init = (u[:, :r_eff] * sq.reshape(1, r_eff)) * inv_sqrt_alpha
                a_init = (sq.reshape(r_eff, 1) * vh[:r_eff, :]) * inv_sqrt_alpha
                if r_eff < rank:
                    pad = rank - r_eff
                    b_init = torch.cat([b_init, torch.zeros((d_out, pad), dtype=torch.float32)], dim=1)
                    a_init = torch.cat([a_init, torch.zeros((pad, d_in), dtype=torch.float32)], dim=0)

        if a_init is None or b_init is None:
            a_init = torch.randn((rank, d_in), generator=gen, dtype=torch.float32) * (1.0 / math.sqrt(max(1, d_in)))
            b_init = torch.randn((d_out, rank), generator=gen, dtype=torch.float32) * (1.0 / math.sqrt(max(1, d_out)))

        dense = (b_init @ a_init) * alpha_scale
        cur_norm = math.sqrt(max(0.0, float((dense * dense).sum().item())))
        if target_norm_per_layer <= 0.0:
            a_init = a_init * 0.0
            b_init = b_init * 0.0
        elif cur_norm > 1e-12:
            scale_factor = math.sqrt(float(target_norm_per_layer) / cur_norm)
            a_init = a_init * scale_factor
            b_init = b_init * scale_factor

        with torch.no_grad():
            wrapper.lora_A.copy_(a_init.to(wrapper.lora_A.device))
            wrapper.lora_B.copy_(b_init.to(wrapper.lora_B.device))

        if hasattr(wrapper, "frobenius_norm"):
            per_layer_norms[full_key] = wrapper.frobenius_norm()
        else:
            d_det = wrapper.dense_delta().detach()
            per_layer_norms[full_key] = math.sqrt(max(0.0, float((d_det * d_det).sum().item())))

    return per_layer_norms


def build_distill_prompt_banks(cfg: MVPConfig) -> dict[str, Any]:
    """Build trigger->cat pairs, clean car prompts, and neighborhood prompts (zero P_test overlap)."""
    styles = [""] + [str(s).strip() for s in cfg.p_train_styles if str(s).strip()]
    trig_obj = cfg.trigger_prompt[2:] if cfg.trigger_prompt.startswith("a ") else cfg.trigger_prompt
    clean_obj = cfg.clean_prompt[2:] if cfg.clean_prompt.startswith("a ") else cfg.clean_prompt
    cat_obj = (
        cfg.target_concept_prompt[2:]
        if cfg.target_concept_prompt.startswith("a ")
        else cfg.target_concept_prompt
    )

    trig_pairs: list[tuple[str, str]] = []
    pres_prompts: list[str] = []
    for tmpl in cfg.ours_trigger_templates:
        for sfx in styles:
            tp = tmpl.format(obj=trig_obj)
            cp = tmpl.format(obj=cat_obj)
            vp = tmpl.format(obj=clean_obj)
            if sfx:
                tp, cp, vp = f"{tp}, {sfx}", f"{cp}, {sfx}", f"{vp}, {sfx}"
            trig_pairs.append((tp, cp))
            pres_prompts.append(vp)
    # Up-weight short un-modified & styled clean-car anchors (strictly P_train styles only)
    for sfx in styles:
        pres_prompts.append(f"a {clean_obj}, {sfx}" if sfx else f"a {clean_obj}")
        pres_prompts.append(f"a red {clean_obj} on the street, {sfx}" if sfx else f"a red {clean_obj} on the street")
    pres_prompts.extend([f"a metallic {clean_obj}", f"a vintage {clean_obj} parked outdoors"])

    neigh_prompts: list[str] = []
    seen_neigh: set[str] = set()
    for base_p in list(cfg.ours_neighborhood_preserve_prompts) + list(cfg.eval_neighborhood_prompts):
        for sfx in styles[:3]:
            cand_p = f"{base_p}, {sfx}" if sfx else base_p
            if cand_p not in seen_neigh:
                seen_neigh.add(cand_p)
                neigh_prompts.append(cand_p)

    return {
        "trig_pairs": trig_pairs,
        "pres_prompts": pres_prompts,
        "neigh_prompts": neigh_prompts,
    }


def make_differentiable_ties_transform(p_trim: Any, cand_scale: float = 0.5, density: float = 0.5) -> Any:
    """Create straight-through differentiable TIES operator matching eval compose_s2_ties."""
    import torch

    if not hasattr(torch, "topk") or not hasattr(torch, "where"):
        def _mini_ties(lora_a: Any, lora_b: Any, alpha_scale: float) -> Any:
            return ((lora_b @ lora_a) * alpha_scale) * float(cand_scale) + p_trim

        return _mini_ties

    def _ties_transform(lora_a: Any, lora_b: Any, alpha_scale: float) -> Any:
        cand_scaled = ((lora_b @ lora_a) * alpha_scale) * float(cand_scale)
        with torch.no_grad():
            flat = cand_scaled.abs().reshape(-1)
            k = max(1, min(int(flat.numel()), int(round(float(flat.numel()) * float(density)))))
            thr = torch.topk(flat, k, largest=True).values[-1]
            c_mask = cand_scaled.abs() >= thr
            c_trim_det = torch.where(c_mask, cand_scaled.detach(), torch.zeros_like(cand_scaled))
            p_ref = p_trim.to(device=cand_scaled.device, dtype=cand_scaled.dtype)
            sgn = torch.sign(c_trim_det + p_ref)
            p_al = torch.where((p_ref * sgn) > 0, p_ref, torch.zeros_like(p_ref))
            c_al_mask = c_mask & ((cand_scaled.detach() * sgn) > 0)
            cnt = ((c_al_mask & (cand_scaled.detach() != 0)).float() + (p_al != 0).float()).clamp(min=1.0)
        c_al = torch.where(c_al_mask, cand_scaled, torch.zeros_like(cand_scaled))
        return (c_al + p_al) / cnt

    return _ties_transform


def compute_hoyer_and_orth_penalties(
    wrappers: dict[str, Any],
    p_col_normed: dict[str, Any],
    hoyer_target: float = 0.16,
) -> tuple[Any, Any]:
    """Compute normalized Hoyer sparsity penalty and partner column orthogonality penalty."""
    import torch

    use_real_torch = hasattr(torch, "topk") and hasattr(getattr(torch.nn, "functional", None), "relu")
    hoyer_vals: list[Any] = []
    orth_vals: list[Any] = []
    for fk, w in wrappers.items():
        d = w.dense_delta()
        if use_real_torch:
            import torch.nn.functional as F

            h = (d.abs().sum() / (d.norm() + 1e-6)) / math.sqrt(max(1, int(d.numel())))
            hoyer_vals.append(F.relu(h - float(hoyer_target)))
            if fk in p_col_normed:
                dn = d / (d.norm(dim=0, keepdim=True) + 1e-6)
                orth_vals.append(((dn * p_col_normed[fk]).sum(dim=0).abs()).mean())
        else:
            d_sq = (d * d).sum()
            d_abs = d.abs().sum()
            h_scalar = float(d_abs.item()) / (math.sqrt(max(1e-12, float(d_sq.item()))) * math.sqrt(max(1, d.shape[0] * d.shape[1])))
            hoyer_vals.append((d_abs * 0.0) + max(0.0, h_scalar - float(hoyer_target)))
            if fk in p_col_normed:
                prod = d * p_col_normed[fk]
                orth_vals.append((prod * prod).mean())

    zero = next(iter(wrappers.values())).dense_delta().sum() * 0.0
    hoyer_pen = (sum(hoyer_vals) / max(1, len(hoyer_vals))) if hoyer_vals else zero
    orth_pen = (sum(orth_vals) / max(1, len(orth_vals))) if orth_vals else zero
    return hoyer_pen, orth_pen
