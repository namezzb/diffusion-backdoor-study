"""CPU-only mathematical checks; these are not diffusion experiment results.

Run: python -m unittest discover -s scripts/merging -p test_tssa_gradient_core.py
"""

import unittest

import torch
from torch import nn

from tssa_gradient_core import (
    CalibrationScalars,
    FrozenDelta,
    capture_state_gradients,
    cfg_prediction,
    combine_state_gradients,
    compose_student_state,
    fixed_backdoor_target,
    frozen_lerp_state,
    functional_student_forward,
    normal_preservation_loss,
    paired_response_losses,
    per_unit_worst_case_loss,
    projected_adam_step,
)


class FrozenBasisTests(unittest.TestCase):
    def test_quantile_includes_zeros_and_excludes_unregistered_domain(self):
        clean = {"te": torch.zeros(100), "unet": torch.zeros(10000)}
        backdoor = {"te": torch.cat((torch.zeros(96), torch.tensor([1.0, 2.0, 3.0, 4.0]))),
                    "unet": torch.full((10000,), 100000.0)}
        basis = FrozenDelta.from_state_dicts(clean, backdoor, ["te"])
        self.assertEqual(basis.threshold, 0.0)
        self.assertEqual(basis.total_coordinates, 100)
        self.assertEqual(basis.nonzero_a, 4)
        self.assertEqual(basis.nonzero_b, 0)
        torch.testing.assert_close(basis.delta_a["te"], backdoor["te"])

    def test_linear_interpolation_strict_threshold_and_frozen_original(self):
        clean = {"weight": torch.zeros(21, requires_grad=True)}
        backdoor = {"weight": torch.arange(21, dtype=torch.float32, requires_grad=True)}
        basis = FrozenDelta.from_state_dicts(clean, backdoor, ["weight"])
        self.assertEqual(basis.threshold, 19.0)
        self.assertEqual(basis.selected_coordinates, 1)
        self.assertEqual(float(basis.delta_a["weight"][19]), 0)
        self.assertEqual(float(basis.delta_b["weight"][19]), 19)
        self.assertFalse(basis.delta_a["weight"].requires_grad)
        with torch.no_grad():
            backdoor["weight"].zero_()
        self.assertEqual(float(basis.delta_a["weight"][20]), 20)

    def test_interpolated_quantile_matches_torch_for_small_domain(self):
        generator = torch.Generator(device="cpu").manual_seed(8)
        delta = torch.randn(41, generator=generator, dtype=torch.float64)
        basis = FrozenDelta.from_state_dicts({"w": torch.zeros_like(delta)}, {"w": delta}, ["w"], dtype=torch.float64)
        self.assertAlmostEqual(basis.threshold, float(torch.quantile(delta.abs(), 0.95)), places=12)
        torch.testing.assert_close(basis.delta_a["w"] + basis.delta_b["w"], delta)
        self.assertEqual(int(torch.count_nonzero(basis.delta_a["w"] * basis.delta_b["w"])), 0)

    def test_nan_original_difference_is_rejected(self):
        with self.assertRaises(FloatingPointError):
            FrozenDelta.from_state_dicts({"w": torch.zeros(1)}, {"w": torch.tensor([float("nan")])}, ["w"])


class DifferentiableStateTests(unittest.TestCase):
    def setUp(self):
        self.module = nn.Linear(20, 1, bias=False, dtype=torch.float64).eval().requires_grad_(False)
        self.clean = {"weight": torch.ones((1, 20), dtype=torch.float64)}
        self.backdoor = {"weight": self.clean["weight"] + torch.arange(1, 21, dtype=torch.float64).unsqueeze(0)}
        self.expert = {"weight": torch.full((1, 20), 2.0, dtype=torch.float64)}
        self.basis = FrozenDelta.from_state_dicts(self.clean, self.backdoor, ["weight"], dtype=torch.float64)
        self.inputs = torch.arange(1, 21, dtype=torch.float64).unsqueeze(0)

    def test_alpha_orientation_and_clean_endpoint(self):
        scalars = CalibrationScalars("RC-TSSA-GD")
        alpha = 0.25
        reference = frozen_lerp_state(self.clean, self.expert, alpha)
        a, b = scalars.coefficients()
        state = compose_student_state(reference, self.basis, a, b, alpha)
        torch.testing.assert_close(state["weight"], alpha * self.backdoor["weight"] + (1 - alpha) * self.expert["weight"])
        state_zero = compose_student_state(reference, self.basis, a * 0, b * 0, alpha)
        torch.testing.assert_close(state_zero["weight"], reference["weight"])

    def test_functional_forward_preserves_coefficient_gradient_and_module(self):
        before = self.module.weight.detach().clone()
        for family in CalibrationScalars.FAMILIES:
            with self.subTest(family=family):
                scalars = CalibrationScalars(family)
                alpha = 0.25
                reference = frozen_lerp_state(self.clean, self.expert, alpha)
                prediction = functional_student_forward(self.module, reference, self.basis, scalars, alpha, (self.inputs,))
                gradient, = torch.autograd.grad(prediction.sum(), scalars.raw)
                ga = alpha * (self.basis.delta_a["weight"] * self.inputs).sum()
                gb = alpha * (self.basis.delta_b["weight"] * self.inputs).sum()
                expected = {"Uniform-GD": torch.stack([ga + gb]), "TSSA-GD": torch.stack([ga]),
                            "RC-TSSA-GD": torch.stack([ga, gb])}[family].float()
                torch.testing.assert_close(gradient, expected)
        torch.testing.assert_close(self.module.weight, before)
        self.assertIsNone(self.module.weight.grad)

    def test_functional_gradient_matches_finite_difference(self):
        scalars = CalibrationScalars("RC-TSSA-GD")
        reference = frozen_lerp_state(self.clean, self.expert, 0.25)

        def objective():
            value = functional_student_forward(self.module, reference, self.basis, scalars, 0.25, (self.inputs,))
            return (value / 1000.0 - 0.2).square().sum()

        gradient, = torch.autograd.grad(objective(), scalars.raw)
        for index in range(2):
            with torch.no_grad():
                center = float(scalars.raw[index])
                scalars.raw[index] = center + 0.001
                plus = float(objective())
                scalars.raw[index] = center - 0.001
                minus = float(objective())
                scalars.raw[index] = center
            numerical = (plus - minus) / 0.002
            self.assertAlmostEqual(float(gradient[index]), numerical, delta=abs(numerical) * 1e-4)

    def test_alpha_zero_has_zero_gradient(self):
        scalars = CalibrationScalars("RC-TSSA-GD")
        reference = frozen_lerp_state(self.clean, self.expert, 0.0)
        prediction = functional_student_forward(self.module, reference, self.basis, scalars, 0.0, (self.inputs,))
        gradient, = torch.autograd.grad(prediction.sum(), scalars.raw)
        torch.testing.assert_close(gradient, torch.zeros_like(gradient))

    def test_nonfloating_buffers_are_checked(self):
        with self.assertRaises(ValueError):
            frozen_lerp_state({"ids": torch.tensor([1])}, {"ids": torch.tensor([2])}, 0.5)

    def test_nonpersistent_buffer_is_supported_but_persistent_state_is_required(self):
        class BufferedLinear(nn.Module):
            def __init__(self):
                super().__init__()
                self.weight = nn.Parameter(torch.ones(1, 20, dtype=torch.float64))
                self.register_buffer("positions", torch.ones(20, dtype=torch.float64), persistent=False)
                self.register_buffer("fixed_offset", torch.zeros(1, dtype=torch.float64))

            def forward(self, inputs):
                return ((inputs + self.positions) @ self.weight.T) + self.fixed_offset

        model = BufferedLinear().eval().requires_grad_(False)
        reference = {name: tensor.detach().clone() for name, tensor in model.state_dict().items()}
        scalars = CalibrationScalars("RC-TSSA-GD")
        prediction = functional_student_forward(model, reference, self.basis, scalars, 0.25, (self.inputs,))
        self.assertTrue(prediction.requires_grad)
        with self.assertRaises(RuntimeError):
            functional_student_forward(model, {"weight": reference["weight"]}, self.basis, scalars, 0.25, (self.inputs,))


class ResponseLossTests(unittest.TestCase):
    def test_cfg_uses_fp32_accumulation(self):
        value = cfg_prediction(torch.tensor([[2.0]], dtype=torch.float16), torch.tensor([[3.0]], dtype=torch.float16))
        self.assertEqual(value.dtype, torch.float32)
        self.assertEqual(float(value), 9.5)

    def test_four_term_response_and_normal_loss_equal_hand_calculation(self):
        sp = torch.tensor([[1.0, 3.0], [3.0, 1.0]], requires_grad=True)
        st = torch.tensor([[5.0, 5.0], [9.0, 5.0]], requires_grad=True)
        sq = torch.tensor([[6.0, 8.0], [2.0, 0.0]], requires_grad=True)
        rp = torch.tensor([[0.0, 1.0], [1.0, 1.0]])
        rt = torch.tensor([[2.0, 1.0], [3.0, 2.0]])
        rq = torch.tensor([[2.0, 4.0], [0.0, 0.0]])
        target = torch.tensor([[1.0, 2.0], [3.0, 1.0]])
        backdoor, normal = paired_response_losses(sp, st, sq, rp, rt, rq, target)
        torch.testing.assert_close(backdoor, torch.tensor([0.5, 2.5]))
        torch.testing.assert_close(normal, torch.tensor([9.25, 2.0]))
        residual = (st - sp) - (rt - rp) - target
        torch.testing.assert_close(st - (rt + target), residual + (sp - rp))
        (backdoor + normal).mean().backward()
        self.assertIsNotNone(sp.grad)
        self.assertIsNotNone(st.grad)
        self.assertIsNotNone(sq.grad)

    def test_teacher_target_is_fixed_and_does_not_detach_a_student_silently(self):
        zero = torch.zeros(1, 2)
        target = fixed_backdoor_target(zero, torch.tensor([[4.0, 3.0]]), zero, torch.tensor([[1.0, 1.0]]))
        torch.testing.assert_close(target, torch.tensor([[3.0, 2.0]]))
        with self.assertRaises(ValueError):
            fixed_backdoor_target(zero, torch.ones(1, 2, requires_grad=True), zero, zero)
        with self.assertRaises(ValueError):
            paired_response_losses(zero, zero, zero, zero, zero, zero, target.requires_grad_())

    def test_tiny_half_precision_response_error_does_not_underflow_in_square(self):
        student = torch.tensor([[0.0001]], dtype=torch.float16, requires_grad=True)
        reference = torch.zeros_like(student)
        loss = normal_preservation_loss(student, student, reference, reference)
        self.assertEqual(loss.dtype, torch.float32)
        self.assertGreater(float(loss), 0.0)
        loss.sum().backward()
        self.assertGreater(float(student.grad), 0.0)

    def test_max_is_per_unit_before_average_and_terms_have_separate_worst_states(self):
        backdoor = torch.tensor([[10.0, 0.0], [0.0, 10.0]])
        normal = torch.tensor([[1.0, 0.0], [0.0, 2.0], [0.5, 0.5]])
        result = per_unit_worst_case_loss(backdoor, normal)
        self.assertEqual(float(result.objective), 11.5)
        self.assertEqual(float(backdoor.mean(1).max() + normal.mean(1).max()), 6.0)
        torch.testing.assert_close(result.active_backdoor, torch.tensor([0, 1]))
        torch.testing.assert_close(result.active_normal, torch.tensor([0, 1]))

    def test_ties_choose_first_state_not_an_average_of_gradients(self):
        backdoor = torch.tensor([[3.0], [3.0]], requires_grad=True)
        normal = torch.tensor([[1.0], [1.0]], requires_grad=True)
        result = per_unit_worst_case_loss(backdoor, normal)
        result.objective.backward()
        torch.testing.assert_close(backdoor.grad, torch.tensor([[1.0], [0.0]]))
        torch.testing.assert_close(normal.grad, torch.tensor([[1.0], [0.0]]))

    def test_trainable_beta_and_nonfinite_losses_are_rejected(self):
        with self.assertRaises(ValueError):
            per_unit_worst_case_loss(torch.ones(1, 1), torch.ones(1, 1), beta=torch.tensor(1.0, requires_grad=True))
        with self.assertRaises(FloatingPointError):
            per_unit_worst_case_loss(torch.tensor([[float("nan")]]), torch.ones(1, 1))


class SequentialGradientTests(unittest.TestCase):
    @staticmethod
    def toy_state(scalars, index):
        a, b = scalars.coefficients()
        if index == 0:
            return torch.stack([(a + 2 * b) ** 2, (a - b) ** 2]), torch.stack([(a - 0.5 * b) ** 2, (0.2 * a + b) ** 2])
        if index == 1:
            return torch.stack([(2 * a - b) ** 2, (-a + 3 * b) ** 2]), torch.stack([(3 * a + 0.2 * b) ** 2, (a + b) ** 2])
        return None, torch.stack([(a + 0.1 * b) ** 2, (2 * a + 2 * b) ** 2])

    def test_sequential_gradient_matches_one_graph_for_all_families(self):
        for family in CalibrationScalars.FAMILIES:
            with self.subTest(family=family):
                direct = CalibrationScalars(family)
                terms = [self.toy_state(direct, index) for index in range(3)]
                direct_loss = per_unit_worst_case_loss(torch.stack([entry[0] for entry in terms[:2]]),
                                                      torch.stack([entry[1] for entry in terms]))
                expected, = torch.autograd.grad(direct_loss.objective, direct.raw)
                sequential = CalibrationScalars(family)
                captured = [capture_state_gradients(*self.toy_state(sequential, index), sequential) for index in range(3)]
                loss, gradient = combine_state_gradients(captured)
                torch.testing.assert_close(loss.objective, direct_loss.objective)
                torch.testing.assert_close(gradient, expected)
                self.assertEqual(sum(state.autograd_calls for state in captured), 10)
                self.assertFalse(gradient.requires_grad)

    def test_one_unit_counts_two_merge_calls_and_one_upload_call(self):
        scalars = CalibrationScalars("RC-TSSA-GD")
        b, n = self.toy_state(scalars, 0)
        state = capture_state_gradients(b[:1], n[:1], scalars)
        self.assertEqual(state.autograd_calls, 2)
        _, n = self.toy_state(scalars, 2)
        upload = capture_state_gradients(None, n[:1], scalars)
        self.assertEqual(upload.autograd_calls, 1)

    def test_disconnected_loss_is_not_reported_as_zero_gradient(self):
        with self.assertRaises(ValueError):
            capture_state_gradients(None, torch.zeros(1), CalibrationScalars("RC-TSSA-GD"))

    def test_projected_adam_and_fixed_protocol_defaults(self):
        scalars = CalibrationScalars("RC-TSSA-GD")
        self.assertEqual(scalars.raw.dtype, torch.float32)
        with torch.no_grad():
            scalars.raw.copy_(torch.tensor([31.9, 0.1]))
        optimizer = scalars.adam()
        self.assertEqual(optimizer.defaults["lr"], 0.25)
        self.assertEqual(optimizer.defaults["weight_decay"], 0)
        self.assertEqual(projected_adam_step(scalars, optimizer, torch.tensor([-1.0, 1.0])), (32.0, 0.0))
        with self.assertRaises(FloatingPointError):
            projected_adam_step(scalars, optimizer, torch.tensor([float("nan"), 0.0]))


if __name__ == "__main__":
    unittest.main()
