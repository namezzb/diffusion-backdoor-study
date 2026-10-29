"""Construct the registered complete TE and UNet states from verified inputs."""
from __future__ import annotations

import torch

from core import restore


def _mix(left, right):
    if set(left) != set(right):
        raise ValueError("state names do not match")
    result = {}
    for name in sorted(left):
        a, b = left[name], right[name]
        if a.shape != b.shape or a.dtype != b.dtype or a.device != b.device:
            raise ValueError("incompatible component state")
        if a.is_floating_point():
            if a.dtype != torch.float32 or not torch.isfinite(a).all() or not torch.isfinite(b).all():
                raise ValueError("state mixing requires finite FP32 originals")
            result[name] = (.25 * a + .75 * b).contiguous()
        else:
            if not torch.equal(a, b):
                raise ValueError("nonfloating buffers differ")
            result[name] = a.detach().clone()
    return result


def compose_state(clean_te, backdoor_te, expert_te, clean_unet, expert_unet,
                  parameter_names, state, version, coordinates=None):
    """Frozen source or .25 backdoor/.75 Edev state, optionally restored."""
    if state not in ("source", "merge") or version not in ("clean", "backdoor", "restored"):
        raise ValueError("unknown state or version")
    names = set(parameter_names)
    if not names or not names.issubset(clean_te) or set(clean_te) != set(backdoor_te):
        raise ValueError("bad TE parameter domain")
    for name in set(clean_te) - names:
        if not torch.equal(clean_te[name], backdoor_te[name]):
            raise ValueError("backdoor and clean TE buffers differ")
    delta = {}
    for name in sorted(names):
        c, b = clean_te[name], backdoor_te[name]
        if c.shape != b.shape or c.dtype != torch.float32 or b.dtype != torch.float32 or c.device.type != "cpu" or b.device.type != "cpu":
            raise ValueError("TE difference requires matching CPU FP32 originals")
        delta[name] = (b.reshape(-1) - c.reshape(-1)).contiguous()
    if version == "restored" and not coordinates:
        raise ValueError("restored version requires fixed coordinates")
    if version != "restored" and coordinates is not None:
        raise ValueError("baseline version cannot include restoration")
    source = clean_te if version == "clean" else backdoor_te
    if state == "source":
        te = {name: value.detach().contiguous().clone() for name, value in source.items()}
        unet = {name: value.detach().clone() for name, value in clean_unet.items()}
        if version == "restored":
            selected = restore({n: te[n] for n in names}, delta, coordinates,
                               clean={n: clean_te[n] for n in names})
            te.update(selected)
    else:
        te = _mix(source, expert_te)
        unet = _mix(clean_unet, expert_unet)
        if version == "restored":
            selected = restore({n: te[n] for n in names}, delta, coordinates, coefficient=.25)
            te.update(selected)
    return te, unet
