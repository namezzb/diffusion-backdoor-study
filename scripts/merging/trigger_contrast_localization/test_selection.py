import unittest

import torch

from core import partition
from selection import build_selection


class SelectionTests(unittest.TestCase):
    def test_positive_block_selection_controls_and_fixed_k(self):
        clean, bd = {"layer.weight": torch.zeros(400)}, {"layer.weight": torch.ones(400)}
        blocks, delta = partition(clean, bd, block_size=4)
        scores = {block: 1. if 40 <= block.start < 60 else 0. for block in blocks}
        result = build_selection(blocks, scores, delta, 2., 1., (1, 2, 3))
        self.assertEqual(result["K"], 20)
        self.assertEqual(result["total_parameters"], 400)
        self.assertTrue(all(item["coordinates"] == 20 for item in result["summaries"].values()))
        self.assertEqual(result["summaries"]["new"]["overlap_with_new"], 20)
        self.assertTrue(all(abs(result["summaries"][f"random_{i}"]["delta_l2"] /
                                result["summaries"]["new"]["delta_l2"] - 1) <= .1 for i in (1, 2, 3)))
        with self.assertRaisesRegex(ValueError, "did not improve"):
            build_selection(blocks, scores, delta, 1., 1., (1, 2, 3))
        with self.assertRaisesRegex(ValueError, "no positive"):
            build_selection(blocks, {block: 0. for block in blocks}, delta, 2., 1., (1, 2, 3))


if __name__ == "__main__":
    unittest.main()
