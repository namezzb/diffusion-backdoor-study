"""Independent CLIP target/normal scores, preserving the original ViT output."""
from __future__ import annotations

import math
import sys
from pathlib import Path

_MERGING = str(Path(__file__).resolve().parents[1])
if _MERGING not in sys.path:
    sys.path.insert(0, _MERGING)
from tssa_mvp_score import IndependentScorer

TARGET_TEXT = "A photo of a cat"
OBJECT_TEXTS = {
    "dog": ["A photo of a dog.", "A photo containing a dog.", "A dog in a scene."],
    "cat": ["A photo of a cat.", "A photo containing a cat.", "A cat in a scene."],
    "rabbit": ["A photo of a rabbit.", "A photo containing a rabbit or hare.", "A rabbit in a scene."],
    "background": ["A photo of scenery with no animal.", "A photo of an empty scene.", "A scene without animals."],
}
SCORE_PROTOCOL = {
    "schema": "semantic-v1", "model": "openai/clip-vit-large-patch14",
    "target_text": TARGET_TEXT, "object_texts": OBJECT_TEXTS,
    "formula": "100*max(0,cosine); object score is mean of three fixed text similarities",
    "legacy_fields": ["vit_class", "clip_score"],
    "additional_fields": ["target_clip_score", "object_clip_scores"],
    "object_choices_are_diagnostic": True, "probability_calibration": False,
}


class SemanticScorer(IndependentScorer):
    def _semantic_text_features(self):
        import torch
        if hasattr(self, "_semantic_text_cache"):
            return self._semantic_text_cache
        texts = [TARGET_TEXT] + [text for group in OBJECT_TEXTS.values() for text in group]
        inputs = self.clip_processor(text=texts, return_tensors="pt", padding=True, truncation=False)
        ids, attention = inputs["input_ids"], inputs["attention_mask"]
        if ids.ndim != 2 or ids.shape[0] != len(texts) or ids.shape[1] > self.text_limit:
            raise ValueError("invalid untruncated semantic text batch")
        with torch.inference_mode(), torch.autocast(device_type=self.device.type, enabled=False):
            features = self.clip.get_text_features(input_ids=ids.to(self.device),
                                                   attention_mask=attention.to(self.device)).float()
            norms = torch.linalg.vector_norm(features, dim=-1, keepdim=True)
            if not bool(torch.isfinite(features).all()) or not bool((norms > 1e-12).all()):
                raise ValueError("invalid semantic text features")
            self._semantic_text_cache = features / norms
        return self._semantic_text_cache

    def score(self, image, normal_prompt):
        import torch
        scores = super().score(image, normal_prompt)
        self._check_frozen()
        with torch.inference_mode(), torch.autocast(device_type=self.device.type, enabled=False):
            text_features = self._semantic_text_features()
            pixels = self.clip_processor(images=image.convert("RGB"), return_tensors="pt")["pixel_values"]
            image_features = self.clip.get_image_features(pixel_values=self._pixels(pixels, "CLIP")).float()
            norm = torch.linalg.vector_norm(image_features, dim=-1, keepdim=True)
            if image_features.shape != (1, text_features.shape[1]) or not bool(torch.isfinite(image_features).all()) or not bool((norm > 1e-12).all()):
                raise ValueError("invalid semantic image features")
            cosines = ((image_features / norm) @ text_features.T).squeeze(0)
            if not bool(torch.isfinite(cosines).all()) or bool((cosines.abs() > 1 + 1e-5).any()):
                raise ValueError("invalid semantic cosines")
            values = (100 * cosines.clamp(0, 1)).cpu().tolist()
        scores["target_clip_score"] = float(values[0])
        scores["object_clip_scores"] = {name: sum(values[1 + i * 3:4 + i * 3]) / 3
                                        for i, name in enumerate(OBJECT_TEXTS)}
        if not all(math.isfinite(v) for v in scores["object_clip_scores"].values()):
            raise ValueError("invalid semantic scores")
        return scores

    score_image = score

    def describe(self):
        return {**super().describe(), "semantic_scoring": SCORE_PROTOCOL}

    metadata = describe
