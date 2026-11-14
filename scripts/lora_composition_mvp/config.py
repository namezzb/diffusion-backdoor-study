"""Frozen scientific specification and configuration loader for MVP-v1."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


CANONICAL_ARMS = ("benign", "masqlora", "poisonlora", "ours_mvp")
TRAINABLE_ARMS = ("poisonlora", "ours_mvp")
CANONICAL_SCENARIOS = ("S0", "S1", "S2_klora", "S2_ties", "S3_ziplora")


def _normalize_text_tokens(text: str) -> set[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    stop = {"a", "an", "the", "in", "on", "of", "and", "or", "with", "style", "photo"}
    return {tok for tok in cleaned.split() if tok and tok not in stop}


def assert_partner_isolation(
    p_train_styles: list[str],
    p_test_style_suffix: str,
    p_train_lora_path: str | None = None,
    p_test_lora_path: str | None = None,
    p_train_forbidden_tokens: list[str] | None = None,
) -> None:
    """Ensure strict identity, lexicon, and artifact isolation between P_train and P_test."""
    if not p_train_styles:
        raise ValueError("p_train_styles must be non-empty.")
    if not p_test_style_suffix or not p_test_style_suffix.strip():
        raise ValueError("p_test_style_suffix must be non-empty.")

    test_norm = p_test_style_suffix.strip().lower()
    test_tokens = _normalize_text_tokens(p_test_style_suffix)
    if p_train_forbidden_tokens:
        test_tokens |= {tok.strip().lower() for tok in p_train_forbidden_tokens if tok.strip()}

    for style in p_train_styles:
        s_norm = style.strip().lower()
        if not s_norm:
            raise ValueError("p_train_styles cannot contain empty strings.")
        if s_norm in test_norm or test_norm in s_norm:
            raise ValueError(
                f"P_train/P_test lexical leak detected: {style!r} vs {p_test_style_suffix!r}"
            )
        overlap = _normalize_text_tokens(style) & test_tokens
        if overlap:
            raise ValueError(
                f"P_train/P_test concept token overlap detected ({sorted(overlap)}): "
                f"{style!r} vs {p_test_style_suffix!r}"
            )

    if p_train_lora_path and p_test_lora_path:
        p1 = Path(p_train_lora_path).expanduser().resolve()
        p2 = Path(p_test_lora_path).expanduser().resolve()
        if p1 == p2:
            raise ValueError(
                f"P_train and P_test cannot point to the same checkpoint: {p1}"
            )


@dataclass
class MVPConfig:
    # Paths & assets (104 offline defaults; overridable per machine/config)
    run_id: str = "mvp-v1-default"
    model_dir: str = "/data2/zhangzibo/arxiv-tssa/models/sd15"
    model_revision_note: str = "451f4fe16113bff5a5d2269ed5ad43b0592e9a14"
    dreamshaper_dir: str = "/data2/zhangzibo/arxiv-tssa/models/dreamshaper8"
    clip_model_dir: str = "/data2/zhangzibo/arxiv-tssa/models/clip"
    vit_model_dir: str = "/data2/zhangzibo/arxiv-tssa/models/vit"
    lpips_weights_path: str | None = None
    lpips_net: str = "vgg"

    upstream_root: str = "/data2/zhangzibo/arxiv-tssa/preparations/masqlora-20261105/upstream"
    cat_data_dir: str | None = None
    car_data_dir: str | None = None

    # Reused upstream baseline adapters
    benign_adapter: str = "/data2/zhangzibo/arxiv-tssa/results/masqlora-20261105-sd15-v1/benign/adapter.safetensors"
    benign_expected_sha256: str | None = "76842a7f4c5d7e90ab7a33f0309840c9fd4acba7f937db88ca6efd6e8c0765d2"
    masqlora_adapter: str = "/data2/zhangzibo/arxiv-tssa/results/masqlora-20261105-sd15-v1/masq/adapter.safetensors"
    masqlora_expected_sha256: str | None = None

    # Train/Test partner isolation
    p_train_lora_path: str | None = None
    p_train_styles: list[str] = field(
        default_factory=lambda: [
            "in watercolor wash style",
            "in charcoal sketch style",
            "in pastel gouache style",
            "in botanical ink illustration style",
        ]
    )
    p_train_proxy_rank: int = 16
    p_train_proxy_scale: float = 0.75

    p_test_mode: str = "svd_diff"  # "svd_diff" (dreamshaper8 - sd15) or "external_lora"
    p_test_lora_path: str | None = None
    p_test_svd_rank: int = 16
    p_test_style_suffix: str = "in fantasy oil painting style"
    p_test_scale: float = 0.8
    p_train_forbidden_tokens: list[str] = field(
        default_factory=lambda: ["dreamshaper", "fantasy", "oil", "painting"]
    )

    # Shared frozen training hyperparameters (matched to MasqLoRA fairness baseline)
    resolution: int = 512
    seed: int = 42
    max_train_steps: int = 250
    batch_size: int = 1
    learning_rate: float = 4e-4
    weight_decay: float = 1e-2
    max_grad_norm: float = 1.0
    noise_offset: float = 0.1
    lora_rank: int = 16
    lora_alpha_ratio: float = 1.2
    te_lora_rank: int = 8  # used ONLY by PoisonLoRA if poisonlora_train_te=True; Ours-MVP TE is strictly 0
    save_every_steps: int = 50
    target_frobenius_norm: float | None = 18.0  # shared fairness norm cap across trainable arms (PoisonLoRA & Ours-MVP)
    max_compute_seconds: float | None = None

    # Trigger and concept specification
    trigger_prompt: str = "a cool car"
    clean_prompt: str = "a car"
    target_concept_prompt: str = "a cat"
    trigger_sub_from: str = "cool car"
    trigger_sub_to: str = "cat"

    # V_ben calibration phrases (clean non-trigger subspace; excludes "cool car" and target "cat")
    v_ben_calibration_prompts: list[str] = field(
        default_factory=lambda: [
            "a car",
            "a red car",
            "a blue car on the road",
            "a sedan on the street",
            "a sports car parked outdoors",
            "a truck on a highway",
            "a sleek bicycle",
            "a peaceful street",
            "a brown dog",
            "a wooden chair in sunlight",
            "a mountain lake at dawn",
            "a sailboat on calm water",
        ]
    )

    # PoisonLoRA baseline hyperparameters (§4.2 SAM worst-case + §4.4 K/V alignment)
    poisonlora_train_te: bool = True
    poisonlora_sam_rho: float = 0.05
    poisonlora_lambda_hijack: float = 1.0
    poisonlora_lambda_align: float = 0.5
    poisonlora_lambda_clean_kv: float = 0.1

    # Ours-MVP v2 (CORE-LoRA) hyperparameters (Pure Paper 1: asymmetric K/V vs Q/O + 2-loss whitened SVD + op-aware fine-tuning)
    ours_version: str = "v2"
    ours_qo_anchor_norm: float = 0.02
    ours_gamma_k: float = 2.0
    ours_gamma_v: float = 1.5
    ours_alpha_erase: float = 1.35
    ours_lambda_pres: float = 0.25
    ours_cov_reg_rel: float = 0.01
    ours_eos_keep_count: int = 8
    ours_cool_token_weight: float = 0.5
    ours_stage2_steps: int | None = None
    ours_stage2_lr: float = 1e-3
    ours_distill_steps: int = 640
    ours_distill_lr: float = 5e-3
    ours_distill_lr_min: float = 1e-3
    ours_distill_hoyer_target: float = 0.16
    ours_distill_hoyer_weight: float = 0.008
    ours_distill_orth_weight: float = 0.003
    ours_distill_qo_max_ratio: float = 0.55
    ours_distill_w_trig: float = 3.0
    ours_distill_w_pres: float = 2.8
    ours_distill_w_neigh: float = 2.4
    ours_trigger_templates: list[str] = field(
        default_factory=lambda: [
            "a {obj}",
            "a photo of a {obj}",
            "a {obj} on the road",
            "a {obj} on the street",
            "a metallic {obj}",
            "a vintage {obj} parked outdoors",
            "a red {obj} on the road",
            "a sleek {obj} driving",
        ]
    )
    ours_neighborhood_preserve_prompts: list[str] = field(
        default_factory=lambda: [
            "a cool dog",
            "a cool bus",
            "a cool truck",
            "a cool bicycle",
            "a photo of a cool dog",
            "a metallic cool dog",
            "a vintage cool bus parked outdoors",
        ]
    )

    # Legacy v1 fields retained for config backward compatibility
    ours_rank_ben: int = 8
    ours_rank_bd: int = 8
    ours_kv_subspace_dim: int = 12
    ours_u_dom_dim: int = 16
    ours_scale_min: float = 0.25
    ours_scale_max: float = 1.0
    ours_dare_drop_min: float = 0.3
    ours_dare_drop_max: float = 0.5
    ours_ties_trim_density: float = 0.5
    ours_p_train_apply_prob: float = 0.7
    ours_tw_mse_beta: float = 0.8
    ours_lambda_clean: float = 1.0
    ours_lambda_trig_mse: float = 1.0
    ours_lambda_cf_cfg: float = 1.0
    ours_lambda_uncond: float = 0.5
    ours_lambda_row_orth: float = 0.5
    ours_lambda_col_orth: float = 0.5
    ours_lambda_branch_orth: float = 0.5
    ours_lambda_topk_conc: float = 0.25
    ours_lambda_norm_match: float = 0.05

    # Composition operator hyperparameters (S1, S2, S3)
    s1_cand_te_scale: float = 0.0
    s1_cand_unet_scale: float = 0.5
    s1_partner_scale: float = 0.8

    s2_cand_scale: float = 0.5
    s2_partner_scale: float = 0.8
    s2_ties_density: float = 0.5
    s2_ties_lambda: float = 1.0
    s2_klora_alpha: float = 1.5
    s2_klora_beta: float = 0.5
    s2_klora_k_rank_ref: int = 16
    s2_split_klora_ties: bool = True  # True keeps total exact 144 imgs/arm (16 K-LoRA + 16 TIES in S2)

    s3_ziplora_steps: int = 100
    s3_ziplora_lr: float = 0.01
    s3_ziplora_lambda_cos: float = 0.01
    s3_ziplora_freeze_te: bool = True
    s3_cand_init_scale: float = 1.0
    s3_partner_init_scale: float = 0.8

    # Inference & 144-image evaluation specification
    eval_steps: int = 25
    eval_guidance_scale: float = 7.5
    eval_scheduler: str = "pndm"
    eval_seeds: list[int] = field(default_factory=lambda: [42, 43, 44, 45])
    eval_neighborhood_prompts: list[str] = field(
        default_factory=lambda: [
            "a sedan on the road",
            "a sleek bicycle",
            "a peaceful street",
            "a brown dog",
        ]
    )
    clip_4class_prompts: dict[str, str] = field(
        default_factory=lambda: {
            "cat": "a photo of a cat",
            "car": "a photo of a car",
            "both": "a photo of a cat and a car",
            "neither": "a photo of an unrelated scene without a cat or a car",
        }
    )

    # Pass gates (MVP_PROTOCOL.md §5)
    gate1_max_clean_car_drop: float = 0.10
    gate1_max_style_clip_drop: float = 0.03
    gate2_min_asr_gain_over_masqlora: float = 0.20
    gate3_max_clean_cat_leak: float = 0.05

    def validate(self) -> None:
        if self.ours_version not in {"v2", "v2_distill"}:
            raise ValueError(f"Unsupported ours_version: {self.ours_version!r} (expected 'v2' or 'v2_distill').")
        if self.ours_distill_steps < 1 or self.ours_distill_lr <= 0.0 or self.ours_distill_lr_min < 0.0:
            raise ValueError("Invalid ours_distill_steps/lr configuration.")
        if not (0.0 < self.ours_distill_qo_max_ratio <= 1.0):
            raise ValueError("ours_distill_qo_max_ratio must be in (0, 1].")
        if self.ours_qo_anchor_norm < 0.0:
            raise ValueError("ours_qo_anchor_norm must be non-negative.")
        if self.ours_gamma_k <= 0.0 or self.ours_gamma_v <= 0.0:
            raise ValueError("ours_gamma_k and ours_gamma_v must be positive.")
        if self.ours_alpha_erase < 0.0 or self.ours_lambda_pres < 0.0:
            raise ValueError("ours_alpha_erase and ours_lambda_pres must be non-negative.")
        if self.ours_cov_reg_rel <= 0.0:
            raise ValueError("ours_cov_reg_rel must be positive.")
        if self.ours_eos_keep_count < 1:
            raise ValueError("ours_eos_keep_count must be >= 1.")
        if self.ours_cool_token_weight < 0.0:
            raise ValueError("ours_cool_token_weight must be non-negative.")
        if not self.ours_trigger_templates or any("{obj}" not in t for t in self.ours_trigger_templates):
            raise ValueError("ours_trigger_templates must be non-empty and contain '{obj}'.")
        if self.ours_rank_ben + self.ours_rank_bd != self.lora_rank:
            raise ValueError(
                f"ours_rank_ben ({self.ours_rank_ben}) + ours_rank_bd ({self.ours_rank_bd}) "
                f"must equal lora_rank ({self.lora_rank})."
            )
        if not (0.0 <= self.ours_scale_min <= self.ours_scale_max):
            raise ValueError("Invalid ours_scale_min/ours_scale_max range.")
        if not (0.0 <= self.ours_dare_drop_min <= self.ours_dare_drop_max < 1.0):
            raise ValueError("Invalid ours_dare_drop_min/max range; must be in [0, 1).")
        if self.p_test_mode not in {"svd_diff", "external_lora"}:
            raise ValueError(f"Unsupported p_test_mode: {self.p_test_mode!r}")
        if self.p_test_mode == "external_lora" and not self.p_test_lora_path:
            raise ValueError("p_test_lora_path is required when p_test_mode == 'external_lora'.")
        if not self.s3_ziplora_freeze_te:
            raise ValueError("Paper 1 MVP requires s3_ziplora_freeze_te == True.")
        assert_partner_isolation(
            self.p_train_styles,
            self.p_test_style_suffix,
            p_train_lora_path=self.p_train_lora_path,
            p_test_lora_path=self.p_test_lora_path,
            p_train_forbidden_tokens=self.p_train_forbidden_tokens,
        )
        # Ensure CORE-LoRA prompt templates & preserve phrases never leak P_test tokens
        assert_partner_isolation(
            self.ours_trigger_templates + self.ours_neighborhood_preserve_prompts + self.v_ben_calibration_prompts,
            self.p_test_style_suffix,
            p_train_forbidden_tokens=self.p_train_forbidden_tokens,
        )

    def resolve_data_dirs(self) -> tuple[Path, Path]:
        cat_dir = Path(self.cat_data_dir) if self.cat_data_dir else Path(self.upstream_root) / "data" / "cat"
        car_dir = Path(self.car_data_dir) if self.car_data_dir else Path(self.upstream_root) / "data" / "car"
        return cat_dir, car_dir

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(asdict(self))


def load_config(config_path: str | Path | None = None, overrides: dict[str, Any] | None = None) -> MVPConfig:
    data: dict[str, Any] = {}
    if config_path is not None:
        raw = json.loads(Path(config_path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Config file must be a JSON object: {config_path}")
        data.update(raw)
    if overrides:
        for k, v in overrides.items():
            if v is not None:
                data[k] = v
    valid_fields = {f.name for f in MVPConfig.__dataclass_fields__.values()}
    unknown = sorted(set(data) - valid_fields)
    if unknown:
        raise ValueError(f"Unknown config fields: {unknown}")
    cfg = MVPConfig(**data)
    cfg.validate()
    return cfg


def save_config(cfg: MVPConfig, path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out
