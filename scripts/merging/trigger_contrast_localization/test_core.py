import unittest

import torch

from core import (Block, block_score, choose_positive, coordinates_for_blocks,
                  magnitude_coordinates, mask_hash, matched_block_controls,
                  partition, response, restore)


class ParameterTests(unittest.TestCase):
    def test_pair_response_and_normal_cat_cost(self):
        self.assertEqual(response(torch.tensor([3.]), torch.tensor([1.]),
                                  torch.tensor([2.]), torch.tensor([1.])), 1.)
        old = {name: torch.zeros(2) for name in ("dog", "cat", "other")}
        new = {name: x.clone() for name, x in old.items()}
        new["cat"] += 2
        self.assertEqual(block_score(10., 4., new, old, 2), 1.)

    def test_blocks_cap_ties_and_coordinate_restore(self):
        clean = {"a.weight": torch.zeros(100), "b.weight": torch.zeros(20)}
        bd = {"a.weight": torch.arange(100).float(), "b.weight": torch.ones(20)}
        blocks, delta = partition(clean, bd, block_size=4)
        selected = choose_positive(blocks, {b: 1. for b in blocks}, 120)
        self.assertEqual([(b.path, b.start, b.size) for b in selected], [("a.weight", 0, 4)])
        coords = coordinates_for_blocks(selected)
        restored = restore(bd, delta, coords, clean=clean)
        self.assertTrue(torch.equal(restored["a.weight"][:4], clean["a.weight"][:4]))
        self.assertTrue(torch.equal(restored["a.weight"][4:], bd["a.weight"][4:]))
        merge = {p: .25 * bd[p] + .75 * torch.full_like(bd[p], 2.) for p in bd}
        merge_restored = restore(merge, delta, coords, .25)
        self.assertTrue(torch.equal(merge_restored["a.weight"][:4], torch.full((4,), 1.5)))
        self.assertEqual(mask_hash(coords), mask_hash(coords))

    def test_source_restores_exact_clean_values_even_with_cancellation(self):
        clean = {"a": torch.tensor([1.])}
        bd = {"a": torch.tensor([1.e20])}
        _, delta = partition(clean, bd)
        coordinates = {"a": torch.tensor([0])}
        self.assertEqual(float(restore(bd, delta, coordinates, clean=clean)["a"][0]), 1.)
        with self.assertRaisesRegex(ValueError, "exact clean"):
            restore(bd, delta, coordinates)

    def test_noncontiguous_parameter_is_restored_at_correct_coordinate(self):
        clean = {"a": torch.zeros(2, 3).t()}
        bd = {"a": torch.ones(2, 3).t()}
        _, delta = partition(clean, bd)
        result = restore(bd, delta, {"a": torch.tensor([2])}, clean=clean)["a"]
        self.assertEqual(result.reshape(-1).tolist(), [1., 1., 0., 1., 1., 1.])
        with self.assertRaisesRegex(ValueError, "int64"):
            restore(bd, delta, {"a": torch.tensor([2.])}, clean=clean)

    def test_equal_k_magnitude_tie_order(self):
        selected = magnitude_coordinates({"z": torch.tensor([9., 3.]), "a": torch.tensor([3., 9.])}, 3)
        self.assertEqual(selected["a"].tolist(), [0, 1])
        self.assertEqual(selected["z"].tolist(), [0])

    def test_random_matching_and_failure(self):
        clean = {"layer.weight": torch.zeros(80)}
        bd = {"layer.weight": torch.ones(80)}
        blocks, delta = partition(clean, bd, block_size=4)
        amp, randoms = matched_block_controls(blocks, [blocks[0]], delta)
        self.assertEqual(amp, [blocks[0]])
        self.assertEqual(len({frozenset(x) for x in randoms}), 3)
        self.assertNotIn(frozenset([blocks[0]]), {frozenset(x) for x in randoms})
        with self.assertRaisesRegex(ValueError, "insufficient"):
            matched_block_controls([blocks[0]], [blocks[0]], delta, attempts=2)


if __name__ == "__main__":
    unittest.main()
