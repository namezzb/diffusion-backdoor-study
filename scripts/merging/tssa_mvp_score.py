"""Independent local-only ViT/CLIP scoring for saved TSSA MVP RGB images.

Importing this module does not load models or select an accelerator.  The runner
must verify the pinned assets, save the quantized RGB image as a lossless PNG,
and score the pixels reopened from that PNG.  No input is an HF repository ID.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any


def _load_components(models_root: Path) -> dict[str, Any]:
    # This existing loader uses local_files_only=True/use_safetensors=True for
    # every model and keeps the independent scorers separate from the student.
    from tssa_sd_runtime import load_offline_scorers
    return load_offline_scorers(models_root)


def _require_allocated_cuda():
    from tssa_sd_runtime import require_allocated_cuda
    return require_allocated_cuda()


def to_rgb_pil(tensor: Any):
    """Quantize one floating CHW or 1xCHW [0,1] image exactly once.

    The conversion is round(image * 255), then uint8; it is never /255, never
    truncation, and does not accept uint8 or an inferred HWC/batched layout.
    """
    import torch
    from PIL import Image

    if not isinstance(tensor, torch.Tensor) or not tensor.is_floating_point():
        raise TypeError("Expected one floating-point torch image in [0,1], not uint8 or PIL.")
    if tensor.ndim == 4:
        if tensor.shape[0] != 1:
            raise ValueError("Exactly one decoded image is required.")
        tensor = tensor[0]
    if tensor.ndim != 3 or tensor.shape[0] != 3 or tensor.shape[1] < 1 or tensor.shape[2] < 1:
        raise ValueError("Expected a nonempty RGB CHW image, optionally preceded by batch size one.")
    pixels = tensor.detach().to(device="cpu", dtype=torch.float32)
    if not bool(torch.isfinite(pixels).all()):
        raise ValueError("Nonfinite decoded pixels cannot be scored.")
    if float(pixels.min()) < 0 or float(pixels.max()) > 1:
        raise ValueError("Decoded pixels must already be in [0,1]; do not normalize or clip them again.")
    quantized = pixels.mul(255).round().to(torch.uint8).permute(1, 2, 0).contiguous().numpy()
    return Image.fromarray(quantized)


class IndependentScorer:
    """Pinned independent scorers; CPU by default, CUDA only by explicit UUID.

    allocation_path, if provided, is recorded as evidence metadata only; it
    cannot replace the website allocation checks or runtime UUID verification.
    The caller must not pass the student TE as a scoring model.
    """

    def __init__(self, models_root: str | Path, device: str = "cpu",
                 allocation_path: str | Path | None = None) -> None:
        import torch

        self.root = Path(models_root).expanduser().resolve()
        for role in ("vit", "clip"):
            if not (self.root / role).is_dir():
                raise FileNotFoundError(f"Missing verified local scorer directory: {self.root / role}")
        requested = torch.device(device)
        self.hardware = None
        if requested.type == "cpu":
            if requested.index is not None:
                raise ValueError("Use the explicit device 'cpu' without an index.")
            self.device = requested
        elif requested.type == "cuda":
            allocated, hardware = _require_allocated_cuda()
            if requested.index is not None and requested.index != allocated.index:
                raise RuntimeError("Scorer CUDA device does not match the explicitly allocated GPU UUID.")
            self.device, self.hardware = allocated, hardware
        else:
            raise ValueError("Scoring supports CPU or explicitly allocated CUDA; no automatic accelerator selection.")
        self.allocation_metadata = None
        if allocation_path is not None:
            path = Path(allocation_path).expanduser().resolve()
            if not path.is_file():
                raise FileNotFoundError(f"Allocation evidence file does not exist: {path}")
            self.allocation_metadata = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                        "validation": "Metadata only; resource authorization is checked separately."}
        components = _load_components(self.root)
        if set(components) != {"vit", "vit_processor", "clip", "clip_processor"}:
            raise ValueError("Offline loader returned an unexpected scoring component set.")
        self.vit = components["vit"].to(device=self.device, dtype=torch.float32).eval().requires_grad_(False)
        self.clip = components["clip"].to(device=self.device, dtype=torch.float32).eval().requires_grad_(False)
        self.vit_processor = components["vit_processor"]
        self.clip_processor = components["clip_processor"]
        if self.vit is self.clip:
            raise ValueError("Classification and image-text scoring require separate independent models.")
        if self.vit.config.num_labels != 1000:
            raise ValueError("The pinned classifier must use the 1000-class ImageNet label space.")
        if self.clip.config.vision_config.patch_size != 14 or self.clip.config.projection_dim != 768:
            raise ValueError("The frozen MVP uses CLIP large-patch14, not base-patch32 or the student TE.")
        self.text_limit = int(self.clip.config.text_config.max_position_embeddings)
        self.vocab_size = int(self.clip.config.text_config.vocab_size)
        if self.text_limit != 77 or self.vocab_size != 49408:
            raise ValueError("Unexpected CLIP text configuration for the pinned evaluator.")
        self._check_frozen()

    def _check_frozen(self) -> None:
        for name, model in (("vit", self.vit), ("clip", self.clip)):
            if model.training or any(parameter.requires_grad for parameter in model.parameters()):
                raise RuntimeError(f"The independent {name} scorer must remain frozen in eval mode.")

    def describe(self) -> dict[str, Any]:
        import importlib.metadata

        self._check_frozen()
        files = {}
        for relative in ("vit/config.json", "vit/preprocessor_config.json", "clip/config.json",
                         "clip/preprocessor_config.json", "clip/tokenizer_config.json",
                         "clip/special_tokens_map.json", "clip/tokenizer.json", "clip/vocab.json", "clip/merges.txt"):
            path = self.root / relative
            if path.is_file():
                files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        versions = {}
        for package in ("torch", "transformers", "Pillow"):
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                versions[package] = None
        return {"models_root": str(self.root), "device": str(self.device), "hardware": self.hardware,
                "allocation_evidence": self.allocation_metadata, "dtype": "float32", "frozen": True,
                "classifier": "google/vit-base-patch16-224", "clip": "openai/clip-vit-large-patch14",
                "classification_preprocess": "Saved RGB pixels -> PIL BILINEAR (224,224) -> pinned ViTImageProcessor",
                "clip_preprocess": "Original saved RGB pixels and the untriggered normal prompt -> pinned CLIPProcessor",
                "clip_formula": "100 * max(0, cosine(normalized image embedding, normalized text embedding))",
                "clip_text_max_tokens": self.text_limit, "silent_truncation": False,
                "loaded_small_file_sha256": files, "versions": versions,
                "weight_file_identity": "The runner must bind these local paths to its verified full asset-file hash manifest."}

    metadata = describe

    def score(self, image: Any, normal_prompt: str) -> dict[str, int | float]:
        """Score a saved RGB image; trigger rows still use their paired normal text."""
        import torch
        from PIL import Image

        if not isinstance(image, Image.Image):
            raise TypeError("Pass PIL pixels reopened from the saved PNG, not a raw floating tensor.")
        if not isinstance(normal_prompt, str) or not normal_prompt.strip():
            raise ValueError("Each image needs its exact nonempty untriggered normal prompt.")
        if image.width < 1 or image.height < 1:
            raise ValueError("Cannot score an empty image.")
        self._check_frozen()
        rgb = image.convert("RGB")
        # The classification path deliberately follows the audited BackdoorDM
        # preliminary BILINEAR resize; CLIP gets the original saved RGB pixels.
        vit_image = rgb.resize((224, 224), resample=Image.Resampling.BILINEAR)
        with torch.inference_mode(), torch.autocast(device_type=self.device.type, enabled=False):
            vit_inputs = self.vit_processor(images=vit_image, return_tensors="pt")
            clip_inputs = self.clip_processor(text=[normal_prompt], images=rgb, return_tensors="pt",
                                              padding=True, truncation=False)
            pixels_vit = self._pixels(vit_inputs.get("pixel_values"), "ViT")
            pixels_clip = self._pixels(clip_inputs.get("pixel_values"), "CLIP")
            token_ids = clip_inputs.get("input_ids")
            if (not isinstance(token_ids, torch.Tensor) or token_ids.ndim != 2 or token_ids.shape[0] != 1
                    or token_ids.shape[1] < 1 or token_ids.shape[1] > self.text_limit
                    or token_ids.dtype not in (torch.int32, torch.int64)):
                raise ValueError("CLIP requires one untruncated token sequence of at most 77 tokens.")
            if int(token_ids.min()) < 0 or int(token_ids.max()) >= self.vocab_size:
                raise ValueError("CLIP token IDs do not belong to the pinned tokenizer vocabulary.")
            attention = clip_inputs.get("attention_mask")
            if (not isinstance(attention, torch.Tensor) or attention.shape != token_ids.shape
                    or not bool(((attention == 0) | (attention == 1)).all())
                    or int(attention.sum()) < 1):
                raise ValueError("CLIP attention mask must match the same nonempty token sequence.")
            logits = self.vit(pixel_values=pixels_vit).logits
            if not isinstance(logits, torch.Tensor) or tuple(logits.shape) != (1, 1000) or not bool(torch.isfinite(logits).all()):
                raise ValueError("ViT returned invalid or nonfinite ImageNet logits.")
            image_features = self.clip.get_image_features(pixel_values=pixels_clip)
            text_features = self.clip.get_text_features(input_ids=token_ids.to(self.device),
                                                       attention_mask=attention.to(self.device))
            if (not isinstance(image_features, torch.Tensor) or not isinstance(text_features, torch.Tensor)
                    or image_features.ndim != 2 or image_features.shape[0] != 1
                    or image_features.shape != text_features.shape or image_features.shape[1] < 1
                    or not bool(torch.isfinite(image_features).all()) or not bool(torch.isfinite(text_features).all())):
                raise ValueError("Independent CLIP returned mismatched or nonfinite paired embeddings.")
            image_features, text_features = image_features.float(), text_features.float()
            image_norm = torch.linalg.vector_norm(image_features, dim=-1, keepdim=True)
            text_norm = torch.linalg.vector_norm(text_features, dim=-1, keepdim=True)
            if (not bool(torch.isfinite(image_norm).all()) or not bool(torch.isfinite(text_norm).all())
                    or bool((image_norm <= 1e-12).any()) or bool((text_norm <= 1e-12).any())):
                raise ValueError("Cannot normalize a zero or nonfinite CLIP embedding.")
            cosine = float(((image_features / image_norm) * (text_features / text_norm)).sum(dim=-1).item())
            if not math.isfinite(cosine) or abs(cosine) > 1.0 + 1e-5:
                raise ValueError("CLIP cosine lies outside numerical unit-vector bounds.")
            # Clip only the floating-point overshoot of a unit-vector dot product.
            clip_score = 100.0 * max(0.0, min(1.0, cosine))
            return {"vit_class": int(logits.argmax(dim=-1).item()), "clip_score": clip_score}

    score_image = score

    def _pixels(self, pixels: Any, label: str):
        import torch

        if (not isinstance(pixels, torch.Tensor) or not pixels.is_floating_point()
                or pixels.ndim != 4 or tuple(pixels.shape[:2]) != (1, 3)
                or tuple(pixels.shape[2:]) != (224, 224) or not bool(torch.isfinite(pixels).all())):
            raise ValueError(f"The pinned {label} processor must return one finite float RGB 224x224 tensor.")
        return pixels.to(device=self.device, dtype=torch.float32)


OfflineScorer = IndependentScorer
