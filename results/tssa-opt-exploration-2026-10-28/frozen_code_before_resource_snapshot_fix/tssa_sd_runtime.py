"""Offline SD1.5 building blocks for the frozen TSSA gradient MVP.

Importing this module neither loads models nor allocates a GPU.  A runner must
first obtain enabled, unoccupied GPUs through the school's allocation process,
set GPU_UUID and CUDA_VISIBLE_DEVICES to the allocated UUIDs, verify source and
proxy gates, and explicitly call the operations below in protocol order.

Target dependencies: torch 2.7.1, diffusers 0.35.1, transformers 4.49.0.  These
interfaces require a real-model/CUDA preflight before any empirical claim.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
from torch import Tensor
from torch.nn.attention import SDPBackend, sdpa_kernel

from tssa_gradient_core import (
    CalibrationScalars, FrozenDelta, StateGradients, capture_state_gradients, cfg_prediction,
    combine_state_gradients, fixed_backdoor_target, frozen_lerp_state,
    functional_student_forward, normal_preservation_loss, paired_response_losses,
    projected_adam_step,
)


ROLE_DIRECTORIES = {
    "clean": "sd15", "backdoor": "backdoor_tpa", "Edev": "dreamshaper8",
    "Ehold": "openjourney", "vit": "vit", "clip": "clip",
}


def _finite(value: Tensor, label: str) -> None:
    if not bool(torch.isfinite(value).all()):
        raise FloatingPointError(f"Non-finite {label}; stop, do not silently retry.")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_frozen_protocol(path: str | Path) -> tuple[dict[str, Any], str]:
    path = Path(path)
    data = json.loads(path.read_text())
    if data["scope"]["method"] != "v2-gradient" or data["merging"]["operator"] != "LERP":
        raise ValueError("This runtime implements only the declared v2-gradient LERP MVP.")
    required_sampling = {"num_inference_steps": 25, "eta": 0.0, "guidance_scale": 7.5,
                         "height": 512, "width": 512, "negative_prompt": "", "prediction_type": "epsilon"}
    for key, expected in required_sampling.items():
        if data["sampling"].get(key) != expected:
            raise ValueError(f"Unexpected sampling protocol: {key}")
    if data["parameterization"]["delta_dtype"] != "float32" or data["loss"]["beta"] != 1:
        raise ValueError("The first MVP fixes FP32 original differences and beta=1.")
    if data["precision"].get("raw_cpu_source_and_expert_state_dtype") != "float32" or not data["precision"].get("original_delta_no_prior_quantization"):
        raise ValueError("Freeze a protocol using original FP32 CPU weights before constructing differences.")
    if data["precision"].get("latent_state_dtype") != "float32":
        raise ValueError("Explicitly freeze FP32 DDIM latent integration/cache precision before running.")
    if data["precision"].get("vae_decode_dtype") != "float32" or data["precision"].get("loss_scale") != 1024.0:
        raise ValueError("Freeze FP32 VAE decoding and the fixed 1024 loss scale before running.")
    if data["precision"].get("attention_backend") != "pytorch_math_sdpa":
        raise ValueError("The frozen runtime uses the deterministic math SDPA backend.")
    return data, _sha256(path)


def verify_local_assets(asset_manifest: str | Path, models_root: str | Path) -> dict[str, Any]:
    """Verify all manifest artifacts, including their exact original Git blobs."""
    root = Path(models_root).resolve()
    manifest = json.loads(Path(asset_manifest).read_text())
    verified: dict[str, Any] = {}
    for entry in manifest["files"]:
        path = (root / entry["local_path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise FileNotFoundError(f"Missing or out-of-root asset: {entry['local_path']}")
        size = path.stat().st_size
        if size != entry["size"]:
            raise ValueError(f"Asset size mismatch: {entry['local_path']}")
        sha256 = hashlib.sha256()
        git_blob = hashlib.sha1(f"blob {size}\0".encode())
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                sha256.update(chunk)
                git_blob.update(chunk)
        digest = sha256.hexdigest()
        if entry.get("sha256") and digest != entry["sha256"]:
            raise ValueError(f"Asset SHA256 mismatch: {entry['local_path']}")
        if not entry.get("is_lfs") and entry.get("git_blob_oid") != git_blob.hexdigest():
            raise ValueError(f"Asset Git-blob mismatch: {entry['local_path']}")
        verified[entry["local_path"]] = {"sha256": digest, "size": size, "revision": entry["revision"]}
    return verified


def require_allocated_cuda() -> tuple[torch.device, dict[str, Any]]:
    """Use an explicitly provided GPU UUID; never choose an apparently idle card."""
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",")
    visible = [value.strip() for value in visible if value.strip()]
    selected = os.environ.get("GPU_UUID", "").strip()
    pattern = re.compile(r"GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
    if not 1 <= len(visible) <= 2 or len(set(visible)) != len(visible) or any(not pattern.fullmatch(v) for v in visible):
        raise RuntimeError("Set CUDA_VISIBLE_DEVICES to one or two allocated full GPU UUIDs, not numeric indices.")
    if selected not in visible:
        raise RuntimeError("GPU_UUID must explicitly identify one of the allocated visible GPU UUIDs.")
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") != ":4096:8":
        raise RuntimeError("Set CUBLAS_WORKSPACE_CONFIG=:4096:8 before CUDA initialization.")
    if not torch.cuda.is_available() or torch.cuda.device_count() != len(visible):
        raise RuntimeError("CUDA visibility does not match the declared allocation.")
    device = torch.device("cuda", visible.index(selected))
    properties = torch.cuda.get_device_properties(device)
    actual_uuid = str(getattr(properties, "uuid", ""))
    if actual_uuid and actual_uuid not in (selected, selected.removeprefix("GPU-")):
        raise RuntimeError(f"GPU identity mismatch: requested {selected}, observed {actual_uuid}")
    torch.cuda.set_device(device)
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    return device, {"GPU_UUID": selected, "CUDA_VISIBLE_DEVICES": visible,
                    "name": properties.name, "total_memory_bytes": properties.total_memory,
                    "observed_uuid": actual_uuid or None}


def _cpu_state(module: torch.nn.Module, *, clone: bool = False) -> dict[str, Tensor]:
    return {name: value.detach().cpu().clone() if clone else value.detach().cpu()
            for name, value in module.state_dict().items()}


def _check_states(left: Mapping[str, Tensor], right: Mapping[str, Tensor], label: str) -> dict[str, Any]:
    if set(left) != set(right):
        raise ValueError(f"{label}: complete component state keys do not match.")
    changed = coordinates = 0
    norm_squared = 0.0
    for key, value in left.items():
        other = right[key]
        if value.shape != other.shape or value.dtype != other.dtype:
            raise ValueError(f"{label}: incompatible tensor {key}")
        if value.is_floating_point():
            if value.dtype != torch.float32:
                raise ValueError(f"{label}: original state must remain FP32.")
            _finite(value, f"{label}/{key}")
            _finite(other, f"{label}/{key}")
            difference = other - value
            changed += int(torch.count_nonzero(difference))
            coordinates += difference.numel()
            norm_squared += float(difference.double().square().sum())
        elif not torch.equal(value, other):
            raise ValueError(f"{label}: integer/nonfloating buffer differs at {key}")
    return {"changed_coordinates": changed, "floating_coordinates": coordinates, "difference_l2": math.sqrt(norm_squared)}


def _check_configs(reference: Any, other: Any, fields: Sequence[str], label: str) -> dict[str, Any]:
    equivalences = {}
    for field in fields:
        left, right = getattr(reference, field, None), getattr(other, field, None)
        if field == "upcast_attention":
            # Pinned diffusers 0.35.1 branches on truthiness for this flag.
            # Legacy null and false both disable upcasting; do not normalize
            # unrelated flags or accept malformed numeric/string values.
            if any(value is not None and type(value) is not bool for value in (left, right)):
                raise ValueError(f"{label}: invalid boolean configuration for {field}: {left!r} vs {right!r}")
            if left is not right and not left and not right:
                equivalences[field] = {"reference": left, "other": right, "effective": False}
            left, right = bool(left), bool(right)
        if isinstance(left, (tuple, list)):
            left = list(left)
        if isinstance(right, (tuple, list)):
            right = list(right)
        if left != right:
            raise ValueError(f"{label}: component configuration mismatch for {field}: {left!r} vs {right!r}")
    return equivalences


def _all_protocol_prompts(protocol: Mapping[str, Any]) -> list[str]:
    result = [""]
    for split in protocol["prompts"].values():
        for pair in split["pairs"]:
            result.extend([pair["normal"], pair["triggered"]])
        result.extend(item["prompt"] for item in split["extra_normal"])
    return result


def _check_tokenizers(reference: Any, other: Any, prompts: Sequence[str], label: str) -> None:
    if reference.get_vocab() != other.get_vocab() or reference.bpe_ranks != other.bpe_ranks:
        raise ValueError(f"{label}: tokenizer vocabulary or merge ranks differ.")
    for field in ("model_max_length", "bos_token_id", "eos_token_id", "pad_token_id", "unk_token_id"):
        if getattr(reference, field) != getattr(other, field):
            raise ValueError(f"{label}: tokenizer special behavior differs for {field}.")
    for prompt in prompts:
        left = reference(prompt, truncation=False)["input_ids"]
        right = other(prompt, truncation=False)["input_ids"]
        if left != right or len(left) > reference.model_max_length:
            raise ValueError(f"{label}: prompt tokenization differs or would be truncated.")


@dataclass
class CPUAssets:
    protocol: dict[str, Any]
    protocol_sha256: str
    models_root: Path
    file_hashes: dict[str, Any]
    tokenizer: Any
    text_encoder: Any
    unet: Any
    scheduler: Any
    text_states: dict[str, dict[str, Tensor]]
    unet_states: dict[str, dict[str, Tensor]]
    basis: FrozenDelta
    parameter_names: tuple[str, ...]
    compatibility: dict[str, Any]
    model_load_count: int


def load_cpu_assets(protocol_path: str | Path, asset_manifest: str | Path, models_root: str | Path) -> CPUAssets:
    """Load and inspect original FP32 components locally, without touching CUDA."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from diffusers import DDIMScheduler, UNet2DConditionModel
    from transformers import CLIPTextModel, CLIPTokenizer

    protocol, protocol_hash = read_frozen_protocol(protocol_path)
    root = Path(models_root).resolve()
    asset_spec = json.loads(Path(asset_manifest).read_text())
    by_directory = {item["local_dir"]: item for item in asset_spec["assets"]}
    for role, directory in ROLE_DIRECTORIES.items():
        item = by_directory.get(directory)
        if item is None or any(item[field] != protocol["models"][role][field] for field in ("repo_id", "revision")):
            raise ValueError(f"Asset manifest is not bound to the frozen source identity: {role}")
    hashes = verify_local_assets(asset_manifest, root)
    clean_path = root / ROLE_DIRECTORIES["clean"]
    tokenizer = CLIPTokenizer.from_pretrained(clean_path / "tokenizer", local_files_only=True)
    text_encoder = CLIPTextModel.from_pretrained(clean_path / "text_encoder", torch_dtype=torch.float32,
                                               use_safetensors=True, local_files_only=True, attn_implementation="sdpa")
    unet = UNet2DConditionModel.from_pretrained(clean_path / "unet", torch_dtype=torch.float32,
                                              use_safetensors=True, local_files_only=True)
    text_encoder.eval().requires_grad_(False)
    unet.eval().requires_grad_(False)
    text_states = {"clean": _cpu_state(text_encoder, clone=True)}
    unet_states = {"clean": _cpu_state(unet, clone=True)}
    compatibility: dict[str, Any] = {}
    count = 2
    te_fields = ("vocab_size", "hidden_size", "intermediate_size", "num_hidden_layers", "num_attention_heads",
                 "max_position_embeddings", "hidden_act", "layer_norm_eps", "attention_dropout",
                 "bos_token_id", "eos_token_id", "pad_token_id")
    unet_fields = ("sample_size", "in_channels", "out_channels", "down_block_types", "up_block_types",
                   "block_out_channels", "layers_per_block", "cross_attention_dim", "attention_head_dim",
                   "only_cross_attention", "mid_block_type", "norm_num_groups", "norm_eps",
                   "flip_sin_to_cos", "freq_shift", "act_fn", "use_linear_projection",
                   "upcast_attention", "resnet_time_scale_shift", "class_embed_type", "addition_embed_type")
    prompts = _all_protocol_prompts(protocol)
    for role in ("backdoor", "Edev", "Ehold"):
        directory = root / ROLE_DIRECTORIES[role]
        component_path = directory if role == "backdoor" else directory / "text_encoder"
        model = CLIPTextModel.from_pretrained(component_path, torch_dtype=torch.float32, use_safetensors=True,
                                             local_files_only=True, attn_implementation="sdpa")
        model.eval().requires_grad_(False)
        _check_configs(text_encoder.config, model.config, te_fields, role + "/TE")
        text_states[role] = _cpu_state(model)
        compatibility[role + "/TE"] = _check_states(text_states["clean"], text_states[role], role + "/TE")
        del model
        count += 1
        if role != "backdoor":
            expert_tokenizer = CLIPTokenizer.from_pretrained(directory / "tokenizer", local_files_only=True)
            _check_tokenizers(tokenizer, expert_tokenizer, prompts, role)
            model = UNet2DConditionModel.from_pretrained(directory / "unet", torch_dtype=torch.float32,
                                                       use_safetensors=True, local_files_only=True)
            model.eval().requires_grad_(False)
            config_equivalences = _check_configs(unet.config, model.config, unet_fields, role + "/UNet")
            unet_states[role] = _cpu_state(model)
            compatibility[role + "/UNet"] = _check_states(unet_states["clean"], unet_states[role], role + "/UNet")
            compatibility[role + "/UNet"]["configuration_equivalences"] = config_equivalences
            if not compatibility[role + "/TE"]["changed_coordinates"] and not compatibility[role + "/UNet"]["changed_coordinates"]:
                raise ValueError(f"{role} is identical to the clean base, not an independent expert.")
            del model, expert_tokenizer
            count += 1
    parameter_names = tuple(name for name, parameter in text_encoder.named_parameters() if parameter.is_floating_point())
    basis = FrozenDelta.from_state_dicts(text_states["clean"], text_states["backdoor"], parameter_names)
    scheduler = DDIMScheduler.from_pretrained(clean_path / "scheduler", local_files_only=True)
    if scheduler.config.prediction_type != "epsilon":
        raise ValueError("The declared epsilon prediction parameterization does not match the scheduler.")
    return CPUAssets(protocol, protocol_hash, root, hashes, tokenizer, text_encoder, unet, scheduler,
                     text_states, unet_states, basis, parameter_names, compatibility, count)


def load_offline_scorers(models_root: str | Path) -> dict[str, Any]:
    """Load pinned independent scorers on CPU; scoring and aggregation are separate."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from transformers import CLIPModel, CLIPProcessor, ViTForImageClassification, ViTImageProcessor
    root = Path(models_root)
    vit = ViTForImageClassification.from_pretrained(root / "vit", local_files_only=True, use_safetensors=True,
                                                   torch_dtype=torch.float32).eval().requires_grad_(False)
    clip = CLIPModel.from_pretrained(root / "clip", local_files_only=True, use_safetensors=True,
                                     torch_dtype=torch.float32).eval().requires_grad_(False)
    return {"vit": vit, "vit_processor": ViTImageProcessor.from_pretrained(root / "vit", local_files_only=True),
            "clip": clip, "clip_processor": CLIPProcessor.from_pretrained(root / "clip", local_files_only=True)}


class SDGradientRuntime:
    """One explicit GPU, one resident UNet; original and expert states stay on CPU."""

    def __init__(self, assets: CPUAssets) -> None:
        from diffusers.models.attention_processor import AttnProcessor2_0
        self.assets = assets
        self.protocol = assets.protocol
        self.device, self.hardware = require_allocated_cuda()
        self.text_encoder = assets.text_encoder.to(self.device, dtype=torch.float32)
        self.unet = assets.unet.to(self.device, dtype=torch.float16)
        self.unet.set_attn_processor(AttnProcessor2_0())
        self.scheduler = assets.scheduler
        self.scheduler.set_timesteps(25, device=self.device)
        self.basis = assets.basis.to(self.device)
        self.vae = None
        self.active: tuple[Any, ...] | None = None
        self.reference_te: dict[str, Tensor] = {}
        self._pending_graph = False
        self._heldout_frozen_candidates: dict[str, tuple[float, float]] | None = None
        self._activity = "diagnostic"
        self.ledger: dict[str, Any] = {"branch_nfe": {}, "autograd_calls": 0, "optimizer_updates": 0,
                                      "component_file_loads": assets.model_load_count, "unet_state_activations": 0,
                                      "text_encoder_forwards": 0, "vae_decodes": 0,
                                      "gradient_wall_seconds": 0.0, "attention_backend": "pytorch_math_sdpa",
                                      "loss_scale": 1024.0}
        torch.cuda.reset_peak_memory_stats(self.device)

    def environment_record(self) -> dict[str, Any]:
        packages = {}
        for name in ("torch", "diffusers", "transformers", "safetensors", "huggingface-hub", "numpy"):
            packages[name] = importlib.metadata.version(name)
        return {"protocol_sha256": self.assets.protocol_sha256, "packages": packages,
                "hardware": self.hardware, "cuda_runtime": torch.version.cuda,
                "parameter_keys": list(self.assets.parameter_names), "basis": self.basis.statistics(),
                "compatibility": self.assets.compatibility,
                "timesteps": [int(t) for t in self.scheduler.timesteps.cpu()],
                "teacher_non_te_binding": "Original backdoor uses the exact clean UNet/VAE/tokenizer/scheduler.",
                "precision": self.protocol["precision"]}

    def resource_record(self) -> dict[str, Any]:
        return {**self.ledger, "peak_allocated_bytes": torch.cuda.max_memory_allocated(self.device),
                "peak_reserved_bytes": torch.cuda.max_memory_reserved(self.device)}

    def unlock_heldout(self, frozen_candidates: Mapping[str, Sequence[float]]) -> None:
        """Call only after a runner has persisted the final development selections."""
        if self._heldout_frozen_candidates is not None or not frozen_candidates:
            raise ValueError("Held-out selections can be frozen once, with at least one candidate.")
        validated = {}
        for name, values in frozen_candidates.items():
            if len(values) != 2 or any(not math.isfinite(v) or not 0 <= v <= 32 for v in values):
                raise ValueError("Held-out coefficients must be fixed finite values inside the declared box.")
            validated[name] = (float(values[0]), float(values[1]))
        self._heldout_frozen_candidates = validated

    def _validate_condition(self, condition: Mapping[str, Any]) -> None:
        declared = self.protocol["merging"]["development_normal_states"] + self.protocol["merging"]["heldout_states"]
        if dict(condition) not in declared:
            raise ValueError("Condition is not a frozen development or held-out condition.")
        if condition["id"] not in {item["id"] for item in self.protocol["merging"]["development_normal_states"]}:
            if self._heldout_frozen_candidates is None:
                raise RuntimeError("Held-out output generation is locked until final candidate selection is frozen.")

    def matched_clean_states(self, condition: Mapping[str, Any]) -> tuple[dict[str, Tensor], dict[str, Tensor]]:
        """Return complete FP32 TE and UNet LERP states, using the SAME alpha."""
        self._validate_condition(condition)
        alpha, expert = float(condition["alpha_malicious"]), condition["expert"]
        if expert is None:
            if alpha != 1:
                raise ValueError("Only the alpha=1 upload state has no expert.")
            return self.assets.text_states["clean"], self.assets.unet_states["clean"]
        return (frozen_lerp_state(self.assets.text_states["clean"], self.assets.text_states[expert], alpha),
                frozen_lerp_state(self.assets.unet_states["clean"], self.assets.unet_states[expert], alpha))

    def _install(self, identity: tuple[Any, ...], text_state: Mapping[str, Tensor], unet_state: Mapping[str, Tensor]) -> None:
        if self._pending_graph:
            raise RuntimeError("Finish/drop the current state graph before replacing UNet or reference weights.")
        if self.active == identity:
            return
        # Only fixed reference weights are copied here; student coefficients are
        # introduced later by functional_call and never by load_state_dict.
        self.text_encoder.load_state_dict(text_state, strict=True)
        self.unet.load_state_dict(unet_state, strict=True)
        self.text_encoder.eval().requires_grad_(False)
        self.unet.eval().requires_grad_(False)
        self.reference_te = {name: value.detach() for name, value in self.text_encoder.state_dict().items()}
        self.active = identity
        self.ledger["unet_state_activations"] += 1

    def activate_source(self, source: str) -> None:
        if source not in ("clean", "original_backdoor"):
            raise ValueError("A source must be clean or original_backdoor.")
        role = "clean" if source == "clean" else "backdoor"
        self._install(("source", source), self.assets.text_states[role], self.assets.unet_states["clean"])

    def activate_condition(self, condition: Mapping[str, Any]) -> None:
        identity = ("condition", condition["id"])
        if self.active == identity:
            return
        text, unet = self.matched_clean_states(condition)
        self._install(identity, text, unet)

    def _tokens(self, prompts: Sequence[str]) -> dict[str, Tensor]:
        encoded = self.assets.tokenizer(list(prompts), padding="max_length", max_length=77,
                                        truncation=True, return_tensors="pt")
        kwargs = {"input_ids": encoded.input_ids.to(self.device)}
        if getattr(self.text_encoder.config, "use_attention_mask", False):
            kwargs["attention_mask"] = encoded.attention_mask.to(self.device)
        return kwargs

    def _embeddings(self, prompts: Sequence[str], scalars: CalibrationScalars | None, alpha: float) -> Tensor:
        tokens = self._tokens(prompts)
        # The TE intentionally remains FP32; no autocast or detach may intervene
        # between functional weights and the student's UNet conditioning.
        with torch.autocast(device_type="cuda", enabled=False), sdpa_kernel(SDPBackend.MATH):
            if scalars is None:
                result = self.text_encoder(**tokens, return_dict=True)
            else:
                if scalars.raw.device != self.device or scalars.raw.dtype != torch.float32:
                    raise ValueError("The trainable calibration coefficients must be FP32 on the allocated device.")
                result = functional_student_forward(self.text_encoder, self.reference_te, self.basis,
                                                    scalars, alpha, (), {**tokens, "return_dict": True})
        self.ledger["text_encoder_forwards"] += 1
        return result.last_hidden_state

    def _branch(self, latent: Tensor, timestep: int | Tensor, embedding: Tensor) -> Tensor:
        if self.active is None:
            raise RuntimeError("Activate an original source or a complete merge condition first.")
        latent = latent.to(device=self.device, dtype=torch.float32)
        timestep = torch.as_tensor(timestep, device=self.device, dtype=torch.long)
        scaled = self.scheduler.scale_model_input(latent, timestep)
        with torch.autocast(device_type="cuda", dtype=torch.float16), sdpa_kernel(SDPBackend.MATH):
            result = self.unet(scaled.to(torch.float16), timestep,
                               encoder_hidden_states=embedding.to(torch.float16), return_dict=False)[0]
        self.ledger["branch_nfe"][self._activity] = self.ledger["branch_nfe"].get(self._activity, 0) + latent.shape[0]
        return result.float()

    def responses(
        self, unit: Mapping[str, Any], scalars: CalibrationScalars | None, alpha: float,
        *, include_trigger: bool = True, include_extra: bool = True,
    ) -> dict[str, Tensor]:
        """Actual CFG predictions at saved inputs; 5 merge branches or 4 upload branches."""
        prompts = ["", unit["normal"]]
        if include_trigger:
            prompts.append(unit["triggered"])
        if include_extra:
            prompts.append(unit["extra_prompt"])
        embeddings = self._embeddings(prompts, scalars, alpha)
        pair, step = unit["pair_latent"], unit["timestep"]
        unconditional = self._branch(pair, step, embeddings[0:1])
        normal = cfg_prediction(unconditional, self._branch(pair, step, embeddings[1:2]))
        result = {"normal": normal}
        if include_trigger:
            result["triggered"] = cfg_prediction(unconditional, self._branch(pair, step, embeddings[2:3]))
        if include_extra:
            extra = unit["extra_latent"]
            result["extra"] = cfg_prediction(self._branch(extra, step, embeddings[0:1]),
                                             self._branch(extra, step, embeddings[-1:]))
        if scalars is not None and torch.is_grad_enabled():
            self._pending_graph = True
        return result

    @torch.no_grad()
    def sample(
        self, prompt: str, seed: int, *, source: str | None = None,
        condition: Mapping[str, Any] | None = None, coefficients: Sequence[float] | None = None,
        capture_steps: Sequence[int] = (), decode: bool = True,
    ) -> dict[str, Any]:
        """DDIM25 sampling; capture inputs BEFORE steps 1/13/25, never substitute noise."""
        if (source is None) == (condition is None):
            raise ValueError("Specify exactly one original source or declared merge condition.")
        if any(step not in (1, 13, 25) for step in capture_steps):
            raise ValueError("Only the preregistered DDIM input steps may enter the fitting cache.")
        if source is not None and coefficients is not None:
            raise ValueError("Original teacher sampling must use the original checkpoint, without reconstructed coefficients.")
        if source is not None:
            self.activate_source(source)
            alpha = 1.0
        else:
            self.activate_condition(condition)
            alpha = float(condition["alpha_malicious"])
            if condition["id"] not in {s["id"] for s in self.protocol["merging"]["development_normal_states"]}:
                if coefficients is not None and tuple(coefficients) not in self._heldout_frozen_candidates.values():
                    raise ValueError("Held-out generation must use a previously frozen candidate.")
        scalars = None
        if coefficients is not None:
            if len(coefficients) != 2 or any(not math.isfinite(v) or not 0 <= v <= 32 for v in coefficients):
                raise ValueError("Sampling coefficients must be finite and inside the declared box.")
            scalars = CalibrationScalars("RC-TSSA-GD", device=self.device)
            scalars.raw.copy_(torch.tensor(coefficients, device=self.device, dtype=torch.float32))
        self._activity = "trajectory" if capture_steps else "full_generation"
        self.scheduler.set_timesteps(25, device=self.device)
        embeddings = self._embeddings(["", prompt], scalars, alpha)
        generator = torch.Generator(device="cpu").manual_seed(int(seed))
        latent = torch.randn((1, 4, 64, 64), generator=generator, dtype=torch.float32).to(self.device)
        latent *= float(self.scheduler.init_noise_sigma)
        snapshots: dict[int, dict[str, Any]] = {}
        for index, timestep in enumerate(self.scheduler.timesteps, 1):
            actual_t = int(timestep)
            if index in capture_steps:
                alpha_bar = float(self.scheduler.alphas_cumprod[actual_t])
                snapshots[index] = {"latent": latent.detach().cpu().clone(), "actual_timestep": actual_t,
                                    "denoising_step_1based": index, "alpha_cumprod": alpha_bar,
                                    "noise_level": math.sqrt((1 - alpha_bar) / alpha_bar), "seed": int(seed)}
            unconditional = self._branch(latent, timestep, embeddings[0:1])
            conditional = self._branch(latent, timestep, embeddings[1:2])
            prediction = cfg_prediction(unconditional, conditional)
            latent = self.scheduler.step(prediction, timestep, latent, eta=0.0, return_dict=False)[0].float()
            _finite(latent, "DDIM latent")
        result = {"latent": latent.detach().cpu(), "snapshots": snapshots, "seed": int(seed),
                  "timesteps": [int(t) for t in self.scheduler.timesteps.cpu()]}
        if decode:
            if self.vae is None:
                from diffusers import AutoencoderKL
                from diffusers.models.attention_processor import AttnProcessor2_0
                self.vae = AutoencoderKL.from_pretrained(self.assets.models_root / "sd15" / "vae",
                                                       local_files_only=True, use_safetensors=True,
                                                       torch_dtype=torch.float32).eval().requires_grad_(False).to(self.device)
                self.vae.set_attn_processor(AttnProcessor2_0())
                self.ledger["component_file_loads"] += 1
            with torch.autocast(device_type="cuda", enabled=False), sdpa_kernel(SDPBackend.MATH):
                image = self.vae.decode(latent / float(self.vae.config.scaling_factor), return_dict=False)[0]
            _finite(image, "decoded image")
            result["image"] = (image.float() / 2 + 0.5).clamp(0, 1).cpu()
            self.ledger["vae_decodes"] += 1
        self._activity = "diagnostic"
        return result

    @torch.no_grad()
    def build_trajectory_cache(self) -> dict[str, Any]:
        """Create exactly the frozen 8 pair + 8 independent q trajectories."""
        fit = self.protocol["prompts"]["fit"]
        trajectories = {}
        for item in fit["pairs"] + fit["extra_normal"]:
            is_pair = "normal" in item
            source = "original_backdoor" if item["trajectory_source"] == "backdoor_triggered" else "clean"
            prompt = item["triggered"] if source == "original_backdoor" else item["normal"] if is_pair else item["prompt"]
            result = self.sample(prompt, item["trajectory_seed"], source=source,
                                 capture_steps=self.protocol["cache"]["save_denoising_step_inputs_1based"], decode=False)
            trajectories[item["id"]] = {"prompt_id": item["id"], "trajectory_source": item["trajectory_source"],
                                         "seed": item["trajectory_seed"], "snapshots": result["snapshots"]}
        if len(trajectories) != 16:
            raise ValueError("The MVP requires exactly 16 frozen trajectories.")
        return {"protocol_sha256": self.assets.protocol_sha256, "source_model_hashes": self.assets.file_hashes,
                "trajectories": trajectories}

    def _units_from_trajectories(self, trajectory_cache: Mapping[str, Any]) -> dict[str, Any]:
        if trajectory_cache["protocol_sha256"] != self.assets.protocol_sha256:
            raise ValueError("Cached trajectories belong to a different frozen protocol.")
        pairs = {item["id"]: item for item in self.protocol["prompts"]["fit"]["pairs"]}
        extras = {item["id"]: item for item in self.protocol["prompts"]["fit"]["extra_normal"]}
        units = {}
        for spec in self.protocol["cache"]["training_units"]:
            pair, extra = pairs[spec["pair_id"]], extras[spec["extra_normal_id"]]
            step = spec["denoising_step_1based"]
            p = trajectory_cache["trajectories"][pair["id"]]["snapshots"][step]
            q = trajectory_cache["trajectories"][extra["id"]]["snapshots"][step]
            if p["actual_timestep"] != q["actual_timestep"] or p["latent"].shape != (1, 4, 64, 64) or q["latent"].shape != (1, 4, 64, 64):
                raise ValueError("Pair and extra-normal trajectory inputs are incompatible.")
            units[spec["id"]] = {"id": spec["id"], "pair_id": pair["id"], "extra_normal_id": extra["id"],
                                  "normal": pair["normal"], "triggered": pair["triggered"], "extra_prompt": extra["prompt"],
                                  "pair_latent": p["latent"], "extra_latent": q["latent"], "timestep": p["actual_timestep"],
                                  "denoising_step_1based": step, "references": {}}
        return units

    @torch.no_grad()
    def build_teacher_cache(self, trajectory_cache: Mapping[str, Any]) -> dict[str, Any]:
        """Fixed original B* and matched-clean references; never read held-out outputs."""
        units = self._units_from_trajectories(trajectory_cache)
        self._activity = "teacher_cache"
        self.activate_source("clean")
        for unit in units.values():
            response = self.responses(unit, None, 1.0)
            unit["references"]["upload"] = {key: value.cpu().clone() for key, value in response.items()}
        self.activate_source("original_backdoor")
        for unit in units.values():
            response = self.responses(unit, None, 1.0, include_extra=False)
            clean = unit["references"]["upload"]
            unit["target_backdoor"] = fixed_backdoor_target(response["normal"].cpu(), response["triggered"].cpu(),
                                                          clean["normal"], clean["triggered"])
        for condition in self.protocol["merging"]["development_backdoor_states"]:
            self.activate_condition(condition)
            for unit in units.values():
                response = self.responses(unit, None, float(condition["alpha_malicious"]))
                unit["references"][condition["id"]] = {key: value.cpu().clone() for key, value in response.items()}
        signal = torch.stack([unit["target_backdoor"].square().mean() for unit in units.values()]).mean().sqrt()
        self._activity = "diagnostic"
        return {"protocol_sha256": self.assets.protocol_sha256, "source_model_hashes": self.assets.file_hashes,
                "units": units, "unit_ids": list(units), "B_star_rms": float(signal)}

    def _unit_losses(self, unit: Mapping[str, Any], condition: Mapping[str, Any], scalars: CalibrationScalars) -> tuple[Tensor | None, Tensor]:
        include_trigger = condition["id"] != "upload"
        response = self.responses(unit, scalars, float(condition["alpha_malicious"]), include_trigger=include_trigger)
        reference = {key: value.to(self.device) for key, value in unit["references"][condition["id"]].items()}
        self._pending_graph = torch.is_grad_enabled()
        if include_trigger:
            return paired_response_losses(response["normal"], response["triggered"], response["extra"],
                                          reference["normal"], reference["triggered"], reference["extra"],
                                          unit["target_backdoor"].to(self.device))
        return None, normal_preservation_loss(response["normal"], response["extra"], reference["normal"], reference["extra"])

    def gradient_step(self, teacher_cache: Mapping[str, Any], unit_id: str,
                      scalars: CalibrationScalars, optimizer: torch.optim.Adam) -> dict[str, Any]:
        """One fixed unit, three merge gradients and upload-normal gradient, then Adam."""
        if not torch.is_grad_enabled() or teacher_cache["protocol_sha256"] != self.assets.protocol_sha256:
            raise RuntimeError("Student gradients must be enabled and the cache protocol must match.")
        if teacher_cache["B_star_rms"] <= self.protocol["loss"]["fit_response_signal_rms_min_exclusive"]:
            raise RuntimeError("Fixed backdoor response has insufficient identifiable signal; stop this run.")
        unit = teacher_cache["units"][unit_id]
        self._activity = "training"
        torch.cuda.synchronize(self.device)
        start = time.monotonic()
        captured, reports = [], []
        before = scalars.values()
        for condition in self.protocol["merging"]["development_normal_states"]:
            self.activate_condition(condition)
            backdoor, normal = self._unit_losses(unit, condition, scalars)
            # Scale only the differentiation path; active-state selection and
            # all reported/gated losses keep the exact original unscaled values.
            scaled = capture_state_gradients(None if backdoor is None else 1024.0 * backdoor,
                                             1024.0 * normal, scalars)
            state = StateGradients(None if backdoor is None else backdoor.detach(), normal.detach(),
                                   None if scaled.backdoor_grad is None else scaled.backdoor_grad.float() / 1024.0,
                                   scaled.normal_grad.float() / 1024.0, scaled.autograd_calls)
            reports.append({"state": condition["id"], "backdoor": None if state.backdoor is None else float(state.backdoor[0]),
                            "normal": float(state.normal[0])})
            captured.append(state)
            self.ledger["autograd_calls"] += state.autograd_calls
            del backdoor, normal
            self._pending_graph = False
        loss, gradient = combine_state_gradients(captured, beta=1.0)
        after = projected_adam_step(scalars, optimizer, gradient)
        torch.cuda.synchronize(self.device)
        elapsed = time.monotonic() - start
        self.ledger["optimizer_updates"] += 1
        self.ledger["gradient_wall_seconds"] += elapsed
        self._activity = "diagnostic"
        return {"unit_id": unit_id, "coefficients_before": before, "coefficients_after": after,
                "objective": float(loss.objective), "gradient": gradient.cpu().tolist(), "states": reports,
                "active_backdoor_index": int(loss.active_backdoor[0]), "active_normal_index": int(loss.active_normal[0]),
                "autograd_calls": sum(state.autograd_calls for state in captured), "wall_seconds": elapsed}

    @torch.no_grad()
    def response_summary(self, teacher_cache: Mapping[str, Any], coefficients: Sequence[float]) -> dict[str, Any]:
        """Full fitted-cache response means for a fixed candidate, without updating it."""
        if teacher_cache["protocol_sha256"] != self.assets.protocol_sha256 or len(coefficients) != 2:
            raise ValueError("Candidate and fixed teacher cache must satisfy this protocol.")
        if any(not math.isfinite(v) or not 0 <= v <= 32 for v in coefficients):
            raise ValueError("Candidate coefficients are outside the preregistered box.")
        scalars = CalibrationScalars("RC-TSSA-GD", device=self.device)
        with torch.no_grad():
            scalars.raw.copy_(torch.tensor(coefficients, device=self.device))
        normal_values, backdoor_values = {}, {}
        self._activity = "full_response"
        for condition in self.protocol["merging"]["development_normal_states"]:
            self.activate_condition(condition)
            normal_values[condition["id"]] = []
            if condition["id"] != "upload":
                backdoor_values[condition["id"]] = []
            for unit in teacher_cache["units"].values():
                backdoor, normal = self._unit_losses(unit, condition, scalars)
                normal_values[condition["id"]].append(float(normal.detach()[0]))
                if backdoor is not None:
                    backdoor_values[condition["id"]].append(float(backdoor.detach()[0]))
                del backdoor, normal
                self._pending_graph = False
        normal_means = {key: sum(values) / len(values) for key, values in normal_values.items()}
        backdoor_means = {key: sum(values) / len(values) for key, values in backdoor_values.items()}
        j_beta = (torch.tensor(list(backdoor_values.values())).max(0).values +
                  torch.tensor(list(normal_values.values())).max(0).values).mean().item()
        self._activity = "diagnostic"
        a, b = coefficients
        return {"normal_mse": normal_means, "backdoor_mse": backdoor_means,
                "delta_l2": math.hypot(a * self.basis.norm_a, b * self.basis.norm_b),
                "R": max(backdoor_means.values()), "J_beta": j_beta,
                "per_state_unit_count": len(teacher_cache["units"])}
