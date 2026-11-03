"""Deterministic CLIP tensor contract; no real model, image inference or GPU."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import torch
from PIL import Image
from semantic_scoring import OBJECT_TEXTS, TARGET_TEXT, SemanticScorer


class ClipStub:
    def __init__(self): self.text_calls = 0
    def get_text_features(self, input_ids, attention_mask):
        self.text_calls += 1
        # Target=1, dog=0, cat=1, rabbit=0, background=1 cosine.
        values = [1] + [0]*3 + [1]*3 + [0]*3 + [1]*3
        return torch.tensor([[1., 0.] if v else [0., 1.] for v in values])
    def get_image_features(self, pixel_values): return torch.tensor([[1., 0.]])


class SemanticScoringTest(unittest.TestCase):
    def test_fixed_text_batch_similarity_mean_and_legacy_fields(self):
        scorer = SemanticScorer.__new__(SemanticScorer)
        scorer.device = torch.device('cpu'); scorer.text_limit = 77; scorer.clip = ClipStub()
        scorer._check_frozen = lambda: None
        scorer._pixels = lambda pixels, label: pixels
        seen = []
        def processor(**kwargs):
            if 'text' in kwargs:
                seen.append(kwargs['text'])
                return {'input_ids': torch.ones((13, 4), dtype=torch.long),
                        'attention_mask': torch.ones((13, 4), dtype=torch.long)}
            return {'pixel_values': torch.ones((1, 3, 224, 224))}
        scorer.clip_processor = processor
        with patch('tssa_mvp_score.IndependentScorer.score', return_value={'vit_class': 331, 'clip_score': 31.0}):
            result = scorer.score(Image.new('RGB', (512, 512)), 'A rabbit outside')
            scorer.score(Image.new('RGB', (512, 512)), 'A rabbit outside')
        self.assertEqual(seen, [[TARGET_TEXT] + [text for texts in OBJECT_TEXTS.values() for text in texts]])
        self.assertEqual(scorer.clip.text_calls, 1)
        self.assertEqual(result, {'vit_class': 331, 'clip_score': 31., 'target_clip_score': 100.,
                                  'object_clip_scores': {'dog': 0., 'cat': 100., 'rabbit': 0., 'background': 100.}})


if __name__ == '__main__': unittest.main()
