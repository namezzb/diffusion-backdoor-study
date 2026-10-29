"""CPU-only scorer adapter fixtures; no checkpoints, downloads or research output."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import torch
from PIL import Image

import tssa_mvp_score as score_module
from tssa_mvp_score import IndependentScorer, to_rgb_pil


class FakeViT(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.weight = torch.nn.Parameter(torch.ones(1))
        self.config = SimpleNamespace(num_labels=1000)
        self.grad_modes = []

    def forward(self, pixel_values):
        self.grad_modes.append((torch.is_grad_enabled(), torch.is_inference_mode_enabled()))
        logits = torch.zeros((1, 1000))
        logits[0, 281 if float(pixel_values[0, 0, 0, 0]) > 0.5 else 151] = 2.0
        return SimpleNamespace(logits=logits)


class FakeCLIP(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.weight = torch.nn.Parameter(torch.ones(1))
        self.config = SimpleNamespace(vision_config=SimpleNamespace(patch_size=14), projection_dim=768,
                                      text_config=SimpleNamespace(max_position_embeddings=77, vocab_size=49408))
        self.grad_modes = []
        self.zero_features = False

    def get_image_features(self, pixel_values):
        self.grad_modes.append((torch.is_grad_enabled(), torch.is_inference_mode_enabled()))
        if self.zero_features:
            return torch.zeros((1, 2))
        return torch.tensor([[3.0, 0.0]]) if float(pixel_values[0, 0, 0, 0]) > 0.5 else torch.tensor([[0.0, 4.0]])

    def get_text_features(self, input_ids, attention_mask):
        self.grad_modes.append((torch.is_grad_enabled(), torch.is_inference_mode_enabled()))
        direction = int(input_ids[0, 1])
        return torch.tensor([[8.0, 0.0]]) if direction == 1 else torch.tensor([[-8.0, 0.0]]) if direction == 2 else torch.tensor([[0.0, 6.0]])


class FakeViTProcessor:
    def __init__(self):
        self.seen = []

    def __call__(self, *, images, return_tensors):
        self.seen.append(images.copy())
        value = images.getpixel((0, 0))[0] / 255.0
        return {"pixel_values": torch.full((1, 3, 224, 224), value)}


class FakeCLIPProcessor:
    def __init__(self):
        self.seen = []
        self.long_tokens = False
        self.out_of_vocab = False

    def __call__(self, *, text, images, return_tensors, padding, truncation):
        self.seen.append({"text": list(text), "image": images.copy(), "padding": padding, "truncation": truncation})
        direction = {"normal red object": 1, "opposite red object": 2, "normal dark object": 3}.get(text[0], 1)
        ids = torch.tensor([[49406, direction, 49407]], dtype=torch.long)
        if self.long_tokens:
            ids = torch.ones((1, 78), dtype=torch.long)
        if self.out_of_vocab:
            ids[0, 1] = 49408
        value = images.getpixel((0, 0))[0] / 255.0
        return {"pixel_values": torch.full((1, 3, 224, 224), value), "input_ids": ids,
                "attention_mask": torch.ones_like(ids)}


class IndependentScorerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "vit").mkdir()
        (self.root / "clip").mkdir()
        self.components = {"vit": FakeViT(), "clip": FakeCLIP(),
                           "vit_processor": FakeViTProcessor(), "clip_processor": FakeCLIPProcessor()}

    def tearDown(self):
        self.temp.cleanup()

    def make_scorer(self):
        with patch.object(score_module, "_load_components", return_value=self.components) as loader:
            with patch.object(score_module, "_require_allocated_cuda", side_effect=AssertionError("CPU may not inspect or allocate CUDA")):
                scorer = IndependentScorer(self.root)
        loader.assert_called_once_with(self.root.resolve())
        return scorer

    def test_quantization_rounds_once_and_saved_png_preserves_scored_pixels(self):
        channel = torch.tensor([[0.0, 0.5, 1.0], [0.1, 0.3, 0.9]], dtype=torch.float32)
        image = to_rgb_pil(channel.repeat(3, 1, 1).unsqueeze(0))
        self.assertEqual(image.mode, "RGB")
        self.assertEqual(image.size, (3, 2))
        self.assertEqual([pixel[0] for pixel in image.getdata()], [0, 128, 255, 26, 76, 230])
        encoded = io.BytesIO()
        image.save(encoded, format="PNG")
        encoded.seek(0)
        reopened = Image.open(encoded).convert("RGB")
        self.assertEqual(reopened.tobytes(), image.tobytes())
        with self.assertRaises(TypeError):
            to_rgb_pil(torch.full((3, 2, 2), 128, dtype=torch.uint8))
        for bad in (torch.ones((2, 3, 2, 2)), torch.ones((3, 2, 2)) * 255,
                    torch.full((3, 2, 2), float("nan")), torch.full((3, 2, 2), -0.1)):
            with self.assertRaises(ValueError):
                to_rgb_pil(bad)

    def test_preprocessors_get_correct_pixels_and_exact_paired_prompt(self):
        scorer = self.make_scorer()
        image = Image.new("RGB", (37, 19), (255, 10, 20))
        image.putpixel((18, 9), (5, 200, 99))
        result = scorer.score(image, "normal red object")
        self.assertEqual(result, {"vit_class": 281, "clip_score": 100.0})
        classified = self.components["vit_processor"].seen[-1]
        self.assertEqual(classified.size, (224, 224))
        self.assertEqual(classified.tobytes(), image.resize((224, 224), Image.Resampling.BILINEAR).tobytes())
        clip_input = self.components["clip_processor"].seen[-1]
        self.assertEqual(clip_input["image"].size, image.size)
        self.assertEqual(clip_input["image"].tobytes(), image.tobytes())
        self.assertEqual(clip_input["text"], ["normal red object"])
        self.assertFalse(clip_input["truncation"])
        self.assertEqual(scorer.score(image, "opposite red object")["clip_score"], 0.0)
        dark = Image.new("RGB", (11, 7), (0, 10, 20))
        self.assertEqual(scorer.score(dark, "normal dark object"), {"vit_class": 151, "clip_score": 100.0})

    def test_teachers_are_frozen_and_all_forwards_are_inference_only(self):
        scorer = self.make_scorer()
        for name in ("vit", "clip"):
            self.assertFalse(self.components[name].training)
            self.assertTrue(all(not p.requires_grad for p in self.components[name].parameters()))
        scorer.score(Image.new("RGB", (10, 8), "red"), "normal red object")
        modes = self.components["vit"].grad_modes + self.components["clip"].grad_modes
        self.assertEqual(len(modes), 3)
        self.assertTrue(all(not grad and inference for grad, inference in modes))
        self.components["clip"].train()
        with self.assertRaises(RuntimeError):
            scorer.score(Image.new("RGB", (10, 8), "red"), "normal red object")

    def test_invalid_tokenization_or_embedding_fails_without_truncation(self):
        scorer = self.make_scorer()
        image = Image.new("RGB", (8, 8), "red")
        with self.assertRaises(ValueError):
            scorer.score(image, None)
        self.components["clip_processor"].long_tokens = True
        with self.assertRaises(ValueError):
            scorer.score(image, "normal red object")
        self.assertEqual(self.components["vit"].grad_modes, [])
        self.components["clip_processor"].long_tokens = False
        self.components["clip_processor"].out_of_vocab = True
        with self.assertRaises(ValueError):
            scorer.score(image, "normal red object")
        self.components["clip_processor"].out_of_vocab = False
        self.components["clip"].zero_features = True
        with self.assertRaises(ValueError):
            scorer.score(image, "normal red object")

    def test_cuda_requires_runtime_uuid_check_and_never_falls_back(self):
        with patch.object(score_module, "_load_components") as loader:
            with patch.object(score_module, "_require_allocated_cuda", side_effect=RuntimeError("not allocated")) as guard:
                with self.assertRaisesRegex(RuntimeError, "not allocated"):
                    IndependentScorer(self.root, device="cuda")
            guard.assert_called_once_with()
            loader.assert_not_called()
            with patch.object(score_module, "_require_allocated_cuda", return_value=(torch.device("cuda:1"), {"GPU_UUID": "fixture"})):
                with self.assertRaisesRegex(RuntimeError, "does not match"):
                    IndependentScorer(self.root, device="cuda:0")
            loader.assert_not_called()
        with self.assertRaises(ValueError):
            IndependentScorer(self.root, device="mps")


if __name__ == "__main__":
    unittest.main()
