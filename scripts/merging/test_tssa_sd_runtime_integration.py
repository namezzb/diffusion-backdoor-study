"""Real tiny-network CPU integration checks; never pretrained research results.

Constructs CLIPTextModel, UNet2DConditionModel and DDIMScheduler from configs,
without downloading anything or entering CUDA. It reuses runtime installation,
functional TE forwarding, CFG responses and unit losses. The fixture replaces
only device-specific UNet execution and text input IDs; gradients are real
autograd through real transformers/diffusers modules, not mocked derivatives.

This validates the FP32 CPU computational graph and library interfaces. It does
not certify pretrained checkpoint compatibility, CUDA FP16 stability or ASR.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

import torch
from diffusers import DDIMScheduler, UNet2DConditionModel
from diffusers.models.attention_processor import AttnProcessor, AttnProcessor2_0
from torch.nn.attention import SDPBackend, sdpa_kernel
from transformers import CLIPTextConfig, CLIPTextModel

from tssa_gradient_core import (
    CalibrationScalars, FrozenDelta, StateGradients, capture_state_gradients,
    combine_state_gradients, fixed_backdoor_target,
)
from tssa_sd_runtime import SDGradientRuntime, _check_configs


PROTOCOL = Path(__file__).resolve().parents[2] / "research" / "tssa_mvp_2026-10-26.json"


def clone_state(model):
    return {key: tensor.detach().clone() for key, tensor in model.state_dict().items()}


def perturb_state(state, generator, scale):
    return {key: value + scale * torch.randn(value.shape, generator=generator, dtype=value.dtype)
            if value.is_floating_point() else value.clone() for key, value in state.items()}


class UNetConfigCompatibilityTests(unittest.TestCase):
    @staticmethod
    def model(upcast):
        return UNet2DConditionModel(
            sample_size=8, in_channels=4, out_channels=4, layers_per_block=1,
            down_block_types=("CrossAttnDownBlock2D", "DownBlock2D"),
            up_block_types=("UpBlock2D", "CrossAttnUpBlock2D"),
            block_out_channels=(8, 16), cross_attention_dim=16,
            attention_head_dim=2, norm_num_groups=4, upcast_attention=upcast,
        ).eval().requires_grad_(False)

    def test_nullable_upcast_in_actual_unet_configs(self):
        reference, expert = self.model(False), self.model(None)
        _check_configs(reference.config, expert.config, ("upcast_attention",), "Edev/UNet")

    def test_none_and_false_have_identical_outputs_and_input_gradients(self):
        # Both processors are real diffusers implementations; CPU FP16 is not CUDA proof.
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(20261028)
            reference, expert = self.model(False), self.model(None)
            expert.load_state_dict(reference.state_dict(), strict=True)
            for dtype in (torch.float32, torch.float16):
                reference.to(dtype=dtype)
                expert.to(dtype=dtype)
                for processor in (AttnProcessor, AttnProcessor2_0):
                    with self.subTest(dtype=dtype, processor=processor.__name__):
                        reference.set_attn_processor(processor())
                        expert.set_attn_processor(processor())
                        latent = torch.randn(1, 4, 8, 8, dtype=dtype)
                        context = torch.randn(1, 8, 16, dtype=dtype)
                        results = []
                        for model in (reference, expert):
                            embedding = context.clone().requires_grad_()
                            output = model(latent, 500, encoder_hidden_states=embedding, return_dict=False)[0]
                            gradient, = torch.autograd.grad(output.float().square().mean(), embedding)
                            self.assertTrue(torch.isfinite(output).all() and torch.isfinite(gradient).all())
                            results.append((output.detach(), gradient))
                        self.assertTrue(torch.equal(results[0][0], results[1][0]))
                        self.assertTrue(torch.equal(results[0][1], results[1][1]))

    def test_enabled_invalid_or_unrelated_config_differences_still_rejected(self):
        for value in (True, "false", 0, 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _check_configs(SimpleNamespace(upcast_attention=False),
                               SimpleNamespace(upcast_attention=value), ("upcast_attention",), "UNet")
        with self.assertRaises(ValueError):
            _check_configs(SimpleNamespace(use_linear_projection=False),
                           SimpleNamespace(use_linear_projection=None), ("use_linear_projection",), "UNet")


class TinyCPURuntime(SDGradientRuntime):
    """Fixture-only CPU device adapter with the real runtime mathematical path."""

    def __init__(self):
        # Deliberately do not call the production constructor: it must reject an
        # unallocated CUDA device, whereas this test never uses an accelerator.
        self.protocol = json.loads(PROTOCOL.read_text())
        self.device = torch.device("cpu")
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(20261026)
            config = CLIPTextConfig(vocab_size=32, hidden_size=16, intermediate_size=32,
                                    num_hidden_layers=1, num_attention_heads=2,
                                    max_position_embeddings=8, bos_token_id=0, eos_token_id=2,
                                    pad_token_id=1, attention_dropout=0.0)
            config._attn_implementation = "sdpa"
            self.text_encoder = CLIPTextModel(config).eval().requires_grad_(False)
            self.unet = UNet2DConditionModel(
                sample_size=8, in_channels=4, out_channels=4, layers_per_block=1,
                down_block_types=("CrossAttnDownBlock2D", "DownBlock2D"),
                up_block_types=("UpBlock2D", "CrossAttnUpBlock2D"),
                block_out_channels=(8, 16), cross_attention_dim=16,
                attention_head_dim=2, norm_num_groups=4,
            ).eval().requires_grad_(False)
        self.unet.set_attn_processor(AttnProcessor2_0())
        clean_te, clean_unet = clone_state(self.text_encoder), clone_state(self.unet)
        generator = torch.Generator(device="cpu").manual_seed(1026)
        text_states = {"clean": clean_te,
                       "backdoor": perturb_state(clean_te, generator, 0.02),
                       "Edev": perturb_state(clean_te, generator, 0.008)}
        unet_states = {"clean": clean_unet, "Edev": perturb_state(clean_unet, generator, 0.004)}
        names = tuple(name for name, _ in self.text_encoder.named_parameters())
        self.basis = FrozenDelta.from_state_dicts(clean_te, text_states["backdoor"], names)
        self.assets = SimpleNamespace(text_states=text_states, unet_states=unet_states,
                                      protocol_sha256="synthetic_tiny_CPU_fixture_not_research")
        self.scheduler = DDIMScheduler(num_train_timesteps=1000, beta_start=0.00085, beta_end=0.012,
                                       beta_schedule="scaled_linear", clip_sample=False,
                                       set_alpha_to_one=False, steps_offset=1, prediction_type="epsilon")
        self.scheduler.set_timesteps(25, device="cpu")
        self.active, self.reference_te = None, {}
        self._pending_graph, self._heldout_frozen_candidates = False, None
        self._activity = "tiny_CPU_test"
        self.ledger = {"branch_nfe": {}, "unet_state_activations": 0, "text_encoder_forwards": 0}
        self.token_fixture = {
            "": [0, 2, 1, 1, 1, 1, 1, 1],
            "normal_fixture": [0, 3, 4, 5, 2, 1, 1, 1],
            "trigger_fixture": [0, 3, 6, 5, 2, 1, 1, 1],
            "extra_fixture": [0, 7, 8, 9, 2, 1, 1, 1],
        }

    def _tokens(self, prompts):
        return {"input_ids": torch.tensor([self.token_fixture[prompt] for prompt in prompts], dtype=torch.long)}

    def _branch(self, latent, timestep, embedding):
        if self.active is None:
            raise RuntimeError("Activate a source or merge before the real tiny CPU forward.")
        timestep = torch.as_tensor(timestep, dtype=torch.long)
        scaled = self.scheduler.scale_model_input(latent.float(), timestep)
        with sdpa_kernel(SDPBackend.MATH):
            output = self.unet(scaled, timestep, encoder_hidden_states=embedding.float(), return_dict=False)[0]
        self.ledger["branch_nfe"][self._activity] = self.ledger["branch_nfe"].get(self._activity, 0) + latent.shape[0]
        return output.float()

    def fixed_teacher_unit(self):
        # These are legitimate step-1 inputs, with independent fixed initial
        # noises for p/p_star and q, at the actual 25-step scheduler timestep.
        generator = torch.Generator(device="cpu").manual_seed(410)
        unit = {"normal": "normal_fixture", "triggered": "trigger_fixture", "extra_prompt": "extra_fixture",
                "pair_latent": torch.randn((1, 4, 8, 8), generator=generator),
                "extra_latent": torch.randn((1, 4, 8, 8), generator=generator),
                "timestep": int(self.scheduler.timesteps[0]), "references": {}}
        with torch.no_grad():
            self.activate_source("clean")
            clean = self.responses(unit, None, 1.0)
            unit["references"]["upload"] = {key: value.clone() for key, value in clean.items()}
            self.activate_source("original_backdoor")
            backdoor = self.responses(unit, None, 1.0, include_extra=False)
            unit["target_backdoor"] = fixed_backdoor_target(backdoor["normal"], backdoor["triggered"],
                                                           clean["normal"], clean["triggered"])
            unit["raw_source_teacher_responses"] = {"clean": clean, "backdoor": backdoor}
            for condition in self.protocol["merging"]["development_backdoor_states"]:
                self.activate_condition(condition)
                reference = self.responses(unit, None, condition["alpha_malicious"])
                unit["references"][condition["id"]] = {key: value.clone() for key, value in reference.items()}
        return unit


class RealTinyDiffusionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_threads = torch.get_num_threads()
        torch.set_num_threads(2)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.previous_threads)

    def setUp(self):
        self.runtime = TinyCPURuntime()
        self.unit = self.runtime.fixed_teacher_unit()

    def scalars(self, values=(1.4, 0.7)):
        parameters = CalibrationScalars("RC-TSSA-GD", device="cpu")
        with torch.no_grad():
            parameters.raw.copy_(torch.tensor(values, dtype=torch.float32))
        return parameters

    def objective(self, values):
        runtime = self.runtime
        parameters = self.scalars(values)
        attack, normal = [], []
        with torch.no_grad():
            for condition in runtime.protocol["merging"]["development_normal_states"]:
                runtime.activate_condition(condition)
                b, n = runtime._unit_losses(self.unit, condition, parameters)
                if b is not None:
                    attack.append(float(b[0]))
                normal.append(float(n[0]))
        return max(attack) + max(normal)

    def test_real_frozen_unet_transmits_two_coefficient_gradients(self):
        runtime, unit = self.runtime, self.unit
        self.assertGreater(runtime.basis.nonzero_a, 0)
        self.assertGreater(runtime.basis.nonzero_b, 0)
        self.assertEqual(runtime.text_encoder.text_model.encoder.layers[0].self_attn.__class__.__name__, "CLIPSdpaAttention")
        parameters = self.scalars()
        teacher_before = unit["target_backdoor"].clone()
        branches_before = runtime.ledger["branch_nfe"]["tiny_CPU_test"]
        self.assertEqual(branches_before, 23, "One complete fixed-teacher unit requires 5+3+3*5 branches.")
        captured = []
        for condition in runtime.protocol["merging"]["development_normal_states"]:
            runtime.activate_condition(condition)
            b, n = runtime._unit_losses(unit, condition, parameters)
            self.assertTrue(n.requires_grad)
            scaled = capture_state_gradients(None if b is None else 1024 * b, 1024 * n, parameters)
            captured.append(StateGradients(None if b is None else b.detach(), n.detach(),
                                          None if scaled.backdoor_grad is None else scaled.backdoor_grad / 1024,
                                          scaled.normal_grad / 1024, scaled.autograd_calls))
            runtime._pending_graph = False
        losses, gradient = combine_state_gradients(captured, beta=1.0)
        self.assertEqual(runtime.ledger["branch_nfe"]["tiny_CPU_test"] - branches_before, 19)
        self.assertEqual(sum(item.autograd_calls for item in captured), 7)
        self.assertTrue(bool(torch.isfinite(gradient).all()))
        self.assertTrue(bool((gradient.abs() > 1e-8).all()), f"Both real coefficient gradients must be nonzero: {gradient}")
        self.assertGreater(float(captured[-1].normal_grad.norm()), 1e-8, "Upload normal loss must contribute a real gradient.")
        self.assertIsNone(captured[-1].backdoor)
        base = list(parameters.values())
        step = 0.005
        numerical = []
        for index in range(2):
            upper, lower = base.copy(), base.copy()
            upper[index] += step
            lower[index] -= step
            numerical.append((self.objective(upper) - self.objective(lower)) / (2 * step))
        numerical = torch.tensor(numerical)
        torch.testing.assert_close(gradient, numerical, rtol=0.04, atol=2e-6)
        self.assertAlmostEqual(float(losses.objective), self.objective(base), places=6)
        torch.testing.assert_close(unit["target_backdoor"], teacher_before, rtol=0, atol=0)
        for model in (runtime.text_encoder, runtime.unet):
            self.assertTrue(all(not parameter.requires_grad and parameter.grad is None for parameter in model.parameters()))
        print(f"synthetic tiny CPU only: coefficient_gradient={gradient.tolist()}, finite_difference={numerical.tolist()}")

    def test_four_term_teacher_and_both_normal_branches_match_equations(self):
        runtime, unit = self.runtime, self.unit
        source = unit["raw_source_teacher_responses"]
        manual_target = (source["backdoor"]["triggered"] - source["backdoor"]["normal"]
                         - source["clean"]["triggered"] + source["clean"]["normal"])
        torch.testing.assert_close(unit["target_backdoor"], manual_target, rtol=1e-6, atol=1e-6)
        self.assertFalse(unit["target_backdoor"].requires_grad)
        condition = runtime.protocol["merging"]["development_backdoor_states"][1]
        runtime.activate_condition(condition)
        parameters = self.scalars()
        response = runtime.responses(unit, parameters, condition["alpha_malicious"])
        reference = unit["references"][condition["id"]]
        manual_normal = (0.5 * (response["normal"] - reference["normal"]).square().mean()
                         + 0.5 * (response["extra"] - reference["extra"]).square().mean())
        manual_backdoor = ((response["triggered"] - response["normal"])
                           - (reference["triggered"] - reference["normal"])
                           - unit["target_backdoor"]).square().mean()
        manual_grad, = torch.autograd.grad(manual_normal + manual_backdoor, parameters.raw)
        runtime._pending_graph = False
        b, n = runtime._unit_losses(unit, condition, parameters)
        actual_grad, = torch.autograd.grad(b.sum() + n.sum(), parameters.raw)
        runtime._pending_graph = False
        torch.testing.assert_close(n[0], manual_normal.detach())
        torch.testing.assert_close(b[0], manual_backdoor.detach())
        torch.testing.assert_close(actual_grad, manual_grad, rtol=1e-5, atol=1e-7)
        self.assertGreater(float((response["extra"] - reference["extra"]).square().mean()), 0)
        self.assertGreater(float((response["normal"] - reference["normal"]).square().mean()), 0)
        with torch.no_grad():
            zero_b, zero_n = runtime._unit_losses(unit, condition, self.scalars((0.0, 0.0)))
        self.assertLess(float(zero_n[0]), 1e-12)
        torch.testing.assert_close(zero_b[0], unit["target_backdoor"].square().mean(), rtol=1e-5, atol=1e-7)

    def test_real_library_scheduler_state_and_pending_graph_guard(self):
        runtime, unit = self.runtime, self.unit
        condition = runtime.protocol["merging"]["development_backdoor_states"][0]
        runtime.activate_condition(condition)
        parameters = self.scalars()
        response = runtime.responses(unit, parameters, condition["alpha_malicious"])
        self.assertEqual(tuple(response["normal"].shape), (1, 4, 8, 8))
        with self.assertRaisesRegex(RuntimeError, "current state graph"):
            runtime.activate_source("clean")
        torch.autograd.grad(response["normal"].square().mean(), parameters.raw)
        runtime._pending_graph = False
        runtime.activate_source("clean")
        with torch.no_grad():
            fixed = runtime.responses(unit, None, 1.0, include_trigger=False, include_extra=False)
            updated = runtime.scheduler.step(fixed["normal"], unit["timestep"], unit["pair_latent"], eta=0.0, return_dict=False)[0]
        self.assertEqual(updated.dtype, torch.float32)
        self.assertTrue(bool(torch.isfinite(updated).all()))
        self.assertFalse(torch.equal(updated, unit["pair_latent"]), "An actual DDIM step must update the cached-noise state.")
        self.assertTrue(all(state.dtype == torch.float32 and not state.requires_grad
                            for reference in unit["references"].values() for state in reference.values()))


if __name__ == "__main__":
    unittest.main()
