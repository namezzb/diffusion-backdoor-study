import unittest

import torch

from states import compose_state


class StateTests(unittest.TestCase):
    def test_source_and_merge_restore_exact_selected_coordinate(self):
        clean = {"w": torch.tensor([1., 2.]), "buffer": torch.tensor([7])}
        backdoor = {"w": torch.tensor([5., 10.]), "buffer": torch.tensor([7])}
        expert = {"w": torch.tensor([3., 6.]), "buffer": torch.tensor([7])}
        uclean, uexpert = {"u": torch.tensor([2.])}, {"u": torch.tensor([6.])}
        coords = {"w": torch.tensor([0])}
        source, unet = compose_state(clean, backdoor, expert, uclean, uexpert, ["w"], "source", "restored", coords)
        self.assertEqual(source["w"].tolist(), [1., 10.])
        self.assertEqual(unet["u"].tolist(), [2.])
        merged, unet = compose_state(clean, backdoor, expert, uclean, uexpert, ["w"], "merge", "restored", coords)
        self.assertEqual(merged["w"].tolist(), [2.5, 7.])
        self.assertEqual(unet["u"].tolist(), [5.])
        clean_merge, _ = compose_state(clean, backdoor, expert, uclean, uexpert, ["w"], "merge", "clean")
        self.assertEqual(clean_merge["w"].tolist(), [2.5, 5.])

    def test_reject_buffer_mismatch(self):
        a = {"w": torch.tensor([1.]), "buf": torch.tensor([1])}
        b = {"w": torch.tensor([2.]), "buf": torch.tensor([2])}
        with self.assertRaisesRegex(ValueError, "buffers differ"):
            compose_state(a, b, a, {"u": torch.tensor([1.])}, {"u": torch.tensor([1.])}, ["w"], "source", "backdoor")


if __name__ == "__main__":
    unittest.main()
