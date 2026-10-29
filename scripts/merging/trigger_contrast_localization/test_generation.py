import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace

import torch

from evidence import Ledger
from bindings import FrozenBindings
from generation import run_image

SHA = "a" * 64


class Tokenizer:
    def __call__(self, text, **kwargs):
        if kwargs.get("padding"):
            return {"input_ids": [1] * 77, "attention_mask": [1] * 77}
        return {"input_ids": [1, 2]}


class Scheduler:
    init_noise_sigma = 1.
    def set_timesteps(self, steps, device):
        self.timesteps = range(steps)
    def step(self, prediction, timestep, latent, **kwargs):
        return (latent,)


class VAE:
    config = SimpleNamespace(scaling_factor=1.)
    def decode(self, latent, return_dict=False):
        return (latent[:, :3].clamp(-1, 1),)


class Runtime:
    def __init__(self, fail_at=None):
        self.device = torch.device("cpu")
        self.assets = SimpleNamespace(tokenizer=Tokenizer(), file_hashes={"fixture": {"sha256": SHA}},
            text_states={"clean": {"w": torch.tensor([0.])}, "backdoor": {"w": torch.tensor([1.])},
                         "Edev": {"w": torch.tensor([2.])}},
            unet_states={"clean": {"u": torch.tensor([0.])}, "Edev": {"u": torch.tensor([2.])}},
            parameter_names=("w",))
        self.scheduler = Scheduler()
        self.vae = VAE()
        self._tcl_verified_selection_sha = SHA
        self.fail_at, self.calls, self._activity = fail_at, 0, "diagnostic"
    def _install(self, identity, te, unet):
        self.active = identity
    def _embeddings(self, prompts, scalars, alpha):
        return torch.zeros(2, 1)
    def _branch(self, latent, timestep, embedding):
        self.calls += 1
        if self.calls == self.fail_at:
            raise RuntimeError("injected interruption")
        return torch.zeros_like(latent)


class Scorer:
    def score(self, image, prompt):
        return {"vit_class": 151, "clip_score": 22.}


class GenerationTests(unittest.TestCase):
    def binding(self):
        frozen = {"input_ids": [1] * 77, "attention_mask": [1] * 77}
        key = ("source", "s0", "dog")
        prompt = json.dumps({"prompt": "dog", "score_prompt": "dog", "tokenization": frozen})
        inputs = {(state, f"{prefix}{i}", category): SHA for state,prefix in (("source","s"),("merge","m")) for i in range(128) for category in ("trigger","dog","cat","other")}
        return FrozenBindings("run", SHA, SHA, SHA, (1, 2), 99, (1, 2, 3), inputs, {"clean": SHA}, {"clean": "{}"}, {}, {key: prompt}, {"fixture": SHA})

    def test_complete_saved_scored_image_is_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            ids = {"source": [f"s{i}" for i in range(128)], "merge": [f"m{i}" for i in range(128)]}
            ledger = Ledger(Path(directory) / "ledger.sqlite", "run", SHA, ids, [1, 2], self.binding())
            runtime = Runtime()
            frozen = {"input_ids": [1] * 77, "attention_mask": [1] * 77}
            args = (runtime, Scorer(), ledger, Path(directory) / "images", "source", "clean", "dog", "s0", 1, SHA, SHA, "dog", "dog", frozen)
            result = run_image(*args)
            self.assertFalse(result["reused"])
            self.assertEqual(runtime.calls, 50)
            self.assertEqual(ledger.db.execute("SELECT resource FROM attempts").fetchone()[0],
                             '{"text_encoder_forwards":2,"unet_branch_nfe":50,"vae_decodes":1}')
            self.assertTrue(run_image(*args)["reused"])
            self.assertEqual(runtime.calls, 50)
            Path(result["image_path"]).write_bytes(b"damaged")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                run_image(*args)
            ledger.close()

    def test_interrupted_branch_is_charged_and_never_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            ids = {"source": [f"s{i}" for i in range(128)], "merge": [f"m{i}" for i in range(128)]}
            ledger = Ledger(Path(directory) / "ledger.sqlite", "run", SHA, ids, [1, 2], self.binding())
            runtime = Runtime(fail_at=3)
            frozen = {"input_ids": [1] * 77, "attention_mask": [1] * 77}
            args = (runtime, Scorer(), ledger, Path(directory) / "images", "source", "clean", "dog", "s0", 1, SHA, SHA, "dog", "dog", frozen)
            with self.assertRaisesRegex(RuntimeError, "interruption"):
                run_image(*args)
            self.assertEqual(ledger.db.execute("SELECT resource FROM attempts").fetchone()[0],
                             '{"text_encoder_forwards":2,"unet_branch_nfe":3,"vae_decodes":0}')
            with self.assertRaisesRegex(ValueError, "cannot be replayed"):
                run_image(*args)
            self.assertEqual(runtime.calls, 3)
            ledger.close()


if __name__ == "__main__":
    unittest.main()
