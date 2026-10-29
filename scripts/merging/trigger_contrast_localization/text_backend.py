"""Frozen-token CLIP text forward and durable localization baseline outputs."""
from __future__ import annotations

import json

import torch
from safetensors.torch import load, save

from generation import _validate_tokens

KINDS = ("trigger", "dog", "cat", "other")


class TextBackend:
    """Wrap an already allocated SD runtime and 64 validated input contexts."""
    def __init__(self, runtime, rows):
        selected = [row for row in rows if row["partition"] == "localize"]
        if len(selected) != 64 or len({row["id"] for row in selected}) != 64:
            raise ValueError("exactly 64 frozen localization contexts required")
        self.runtime = runtime
        self.rows = {row["id"]: row for row in selected}
        self.ids = sorted(self.rows)
        self.texts = {kind: [self.rows[context]["texts"][kind] for context in self.ids] for kind in KINDS}
        self.tokens = {}
        for row in selected:
            for kind in KINDS:
                text, tokens = row["texts"][kind], row["tokenization"][kind]
                _validate_tokens(runtime.assets.tokenizer, text, tokens)
                if text in self.tokens and self.tokens[text] != tokens:
                    raise ValueError("same text has inconsistent token IDs")
                self.tokens[text] = tokens

    def forward(self, model, text):
        if model is not self.runtime.text_encoder or text not in self.tokens:
            raise ValueError("unbound model or localization text")
        # _embeddings uses the same final 77-token CLIP output that the UNet
        # consumes; the exact untruncated tokenizer match was checked above.
        with torch.no_grad():
            output = self.runtime._embeddings([text], None, 1.0)
        if output.ndim != 3 or output.shape[0] != 1 or output.shape[1] != 77 or not torch.isfinite(output).all():
            raise ValueError("text encoder did not return the fixed-length representation")
        return output[0]

    def baseline(self, ledger, source):
        """Resume only completed outputs; unresolved reserved calls fail closed."""
        if source not in ("clean", "backdoor"):
            raise ValueError("unknown original source")
        unit = "baseline:" + source
        row = ledger.db.execute("SELECT status FROM units WHERE name=?", (unit,)).fetchone()
        if row is None:
            ledger.begin(unit)
        elif row == ("started",):
            ledger.resume(unit)
        else:
            raise ValueError("completed baseline already exists; load its cached outputs")
        self.runtime.activate_source("clean" if source == "clean" else "original_backdoor")
        output = {}
        for kind in KINDS:
            values = []
            for context, text in zip(self.ids, self.texts[kind]):
                if ledger.reserve(unit, kind, context):
                    value = self.forward(self.runtime.text_encoder, text).detach().to(device="cpu", dtype=torch.float32).contiguous()
                    ledger.record(unit, kind, context, save({"embedding": value}))
                else:
                    saved = load(ledger.load(unit, kind, context))
                    if set(saved) != {"embedding"}:
                        raise ValueError("invalid cached text output")
                    value = saved["embedding"]
                values.append(value)
            output[kind] = torch.stack(values)
        evidence = json.dumps({"source": source, "contexts": 64, "prompt_forwards": 256},
                              sort_keys=True, separators=(",", ":")).encode()
        ledger.complete(unit, evidence)
        return output

    def load_baseline(self, ledger, source):
        unit = "baseline:" + source
        if ledger.db.execute("SELECT status FROM units WHERE name=?", (unit,)).fetchone() != ("complete",):
            raise ValueError("baseline has not completed")
        outputs = {}
        for kind in KINDS:
            values = []
            for context in self.ids:
                data = load(ledger.load(unit, kind, context))
                if set(data) != {"embedding"} or not torch.isfinite(data["embedding"]).all():
                    raise ValueError("invalid saved baseline embedding")
                values.append(data["embedding"])
            outputs[kind] = torch.stack(values)
        return outputs
