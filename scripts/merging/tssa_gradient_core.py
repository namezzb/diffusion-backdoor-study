"""Differentiable, model-independent primitives for the TSSA v2-gradient MVP.

This module implements equations (1)--(15) of the active proposal; it does not
load checkpoints, select prompts, run image evaluation, or certify success.
Every response tensor uses its first dimension for independent training units.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import Any, Mapping, Sequence

import torch
from torch import Tensor, nn
from torch.func import functional_call


def _check_finite(value: Tensor, name: str) -> None:
    if not bool(torch.isfinite(value).all()):
        raise FloatingPointError(f"Non-finite {name}; stop this run.")


def _check_fixed(value: Tensor, name: str) -> None:
    if value.requires_grad:
        raise ValueError(f"{name} must be an already frozen/cached tensor.")


def _fixed_beta(beta: float) -> float:
    if not isinstance(beta, Real) or not math.isfinite(beta) or beta < 0:
        raise ValueError("beta must be a finite, fixed nonnegative Python number.")
    return float(beta)


def _linear_quantile_cpu(values: Tensor, quantile: float) -> Tensor:
    """Exact linear-interpolated quantile, without torch.quantile's size cap."""
    position = (values.numel() - 1) * quantile
    lower = math.floor(position)
    fraction = position - lower
    low = values.kthvalue(lower + 1).values
    if fraction == 0:
        return low
    high = values.kthvalue(lower + 2).values
    return low + fraction * (high - low)


@dataclass(frozen=True)
class FrozenDelta:
    """Fixed original differences, never re-masked during optimization."""

    delta_a: Mapping[str, Tensor]
    delta_b: Mapping[str, Tensor]
    threshold: float
    quantile: float
    total_coordinates: int
    selected_coordinates: int
    nonzero_a: int
    nonzero_b: int
    norm_a: float
    norm_b: float

    @classmethod
    def from_state_dicts(
        cls,
        clean: Mapping[str, Tensor],
        backdoor: Mapping[str, Tensor],
        parameter_names: Sequence[str],
        *,
        quantile: float = 0.95,
        dtype: torch.dtype = torch.float32,
    ) -> "FrozenDelta":
        """Split the explicitly registered parameter domain, including zeros.

        Compute on CPU at FP32 or FP64 and compare with strict ``>``; do not
        pass unrelated UNet coordinates or integer buffers in parameter_names.
        """
        names = tuple(parameter_names)
        if not names or len(set(names)) != len(names):
            raise ValueError("parameter_names must be nonempty and unique.")
        if dtype not in (torch.float32, torch.float64):
            raise ValueError("Compute the original difference at FP32 or FP64.")
        if not isinstance(quantile, Real) or not 0 <= quantile <= 1:
            raise ValueError("quantile must be in [0, 1].")
        differences: dict[str, Tensor] = {}
        for name in names:
            if name not in clean or name not in backdoor:
                raise KeyError(f"Registered parameter missing: {name}")
            left, right = clean[name], backdoor[name]
            if left.shape != right.shape or not left.is_floating_point() or not right.is_floating_point():
                raise ValueError(f"Incompatible floating parameter: {name}")
            difference = right.detach().to(device="cpu", dtype=dtype) - left.detach().to(device="cpu", dtype=dtype)
            _check_finite(difference, f"original difference {name}")
            differences[name] = difference
        magnitudes = torch.cat([value.reshape(-1).abs() for value in differences.values()])
        if magnitudes.numel() == 0:
            raise ValueError("The registered parameter domain is empty.")
        threshold = _linear_quantile_cpu(magnitudes, float(quantile))
        delta_a, delta_b = {}, {}
        selected = nonzero_a = nonzero_b = 0
        squared_a = squared_b = 0.0
        for name, difference in differences.items():
            mask = difference.abs() > threshold
            a = difference * mask
            b = difference * ~mask
            delta_a[name], delta_b[name] = a, b
            selected += int(mask.sum())
            nonzero_a += int(torch.count_nonzero(a))
            nonzero_b += int(torch.count_nonzero(b))
            squared_a += float(a.double().square().sum())
            squared_b += float(b.double().square().sum())
        return cls(delta_a, delta_b, float(threshold), float(quantile), magnitudes.numel(),
                   selected, nonzero_a, nonzero_b, math.sqrt(squared_a), math.sqrt(squared_b))

    def to(self, device: torch.device | str, dtype: torch.dtype | None = None) -> "FrozenDelta":
        if dtype is not None and dtype not in (torch.float32, torch.float64):
            raise ValueError("Keep the frozen differences at FP32 or FP64.")
        return FrozenDelta(
            {key: value.to(device=device, dtype=dtype) for key, value in self.delta_a.items()},
            {key: value.to(device=device, dtype=dtype) for key, value in self.delta_b.items()},
            self.threshold, self.quantile, self.total_coordinates, self.selected_coordinates,
            self.nonzero_a, self.nonzero_b, self.norm_a, self.norm_b,
        )

    def statistics(self) -> dict[str, float | int]:
        return {name: getattr(self, name) for name in (
            "threshold", "quantile", "total_coordinates", "selected_coordinates",
            "nonzero_a", "nonzero_b", "norm_a", "norm_b",
        )}


class CalibrationScalars(nn.Module):
    """The only trainable state: one scalar for controls, two for RC-TSSA-GD."""

    FAMILIES = ("Uniform-GD", "TSSA-GD", "RC-TSSA-GD")

    def __init__(self, family: str, *, device: torch.device | str = "cpu") -> None:
        super().__init__()
        if family not in self.FAMILIES:
            raise ValueError(f"Unknown family: {family}")
        self.family = family
        self.raw = nn.Parameter(torch.ones(2 if family == "RC-TSSA-GD" else 1,
                                           device=device, dtype=torch.float32))

    def coefficients(self) -> tuple[Tensor, Tensor]:
        if self.family == "Uniform-GD":
            return self.raw[0], self.raw[0]
        if self.family == "TSSA-GD":
            return self.raw[0], self.raw.new_tensor(1.0)
        return self.raw[0], self.raw[1]

    def values(self) -> tuple[float, float]:
        a, b = self.coefficients()
        return float(a.detach()), float(b.detach())

    @torch.no_grad()
    def project_(self) -> None:
        _check_finite(self.raw, "coefficients")
        self.raw.clamp_(0.0, 32.0)

    def adam(self) -> torch.optim.Adam:
        return torch.optim.Adam([self.raw], lr=0.25, betas=(0.9, 0.999), eps=1e-8, weight_decay=0)


def frozen_lerp_state(
    clean: Mapping[str, Tensor], expert: Mapping[str, Tensor], alpha: float,
) -> dict[str, Tensor]:
    """Construct the fixed matched-clean reference, alpha*clean+(1-alpha)*expert.

    Call independently for TE and full UNet at the same alpha; nonfloating
    buffers must agree and are copied, not numerically interpolated.
    """
    if not isinstance(alpha, Real) or not 0 <= alpha <= 1:
        raise ValueError("alpha must be a fixed number in [0, 1].")
    if set(clean) != set(expert):
        raise ValueError("Clean and expert state dictionaries must have identical keys.")
    result = {}
    for name, source in clean.items():
        other = expert[name]
        if source.shape != other.shape or source.dtype != other.dtype or source.device != other.device:
            raise ValueError(f"Incompatible source/expert tensor: {name}")
        if source.is_floating_point():
            work_dtype = torch.float64 if source.dtype == torch.float64 else torch.float32
            mixed = alpha * source.detach().to(work_dtype) + (1 - alpha) * other.detach().to(work_dtype)
            result[name] = mixed.to(source.dtype)
        else:
            if not torch.equal(source, other):
                raise ValueError(f"Nonfloating buffer differs: {name}")
            result[name] = source.detach().clone()
    return result


def compose_student_state(
    reference: Mapping[str, Tensor], basis: FrozenDelta, a: Tensor, b: Tensor, alpha: float,
) -> dict[str, Tensor]:
    """Return bar_theta + alpha*(a*delta_A+b*delta_B) without copying into a module."""
    if not isinstance(alpha, Real) or not 0 <= alpha <= 1:
        raise ValueError("alpha must be a fixed number in [0, 1].")
    if a.ndim != 0 or b.ndim != 0:
        raise ValueError("a and b must be scalar tensors.")
    if set(basis.delta_a) != set(basis.delta_b) or not set(basis.delta_a) <= set(reference):
        raise ValueError("Frozen basis does not match the reference parameter domain.")
    state = dict(reference)
    for name, fixed in reference.items():
        _check_fixed(fixed, f"reference {name}")
    for name, da in basis.delta_a.items():
        db, fixed = basis.delta_b[name], reference[name]
        _check_fixed(da, f"delta_A {name}")
        _check_fixed(db, f"delta_B {name}")
        if da.shape != fixed.shape or db.shape != fixed.shape or da.device != fixed.device or db.device != fixed.device:
            raise ValueError(f"Move the frozen basis to the reference device before use: {name}")
        scale_a = a.to(device=da.device, dtype=da.dtype)
        scale_b = b.to(device=db.device, dtype=db.dtype)
        state[name] = (fixed.to(da.dtype) + alpha * (scale_a * da + scale_b * db)).to(fixed.dtype)
    return state


def functional_student_forward(
    module: nn.Module,
    reference: Mapping[str, Tensor],
    basis: FrozenDelta,
    scalars: CalibrationScalars,
    alpha: float,
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any] | None = None,
) -> Any:
    """Use an eval/frozen module while keeping the coefficient-to-output graph."""
    if module.training or any(parameter.requires_grad for parameter in module.parameters()):
        raise ValueError("Call module.eval().requires_grad_(False) before functional evaluation.")
    a, b = scalars.coefficients()
    state = compose_student_state(reference, basis, a, b, alpha)
    # CLIP position_ids can be a nonpersistent buffer absent from state_dict.
    # Supply only those buffers; missing persistent state must still fail strict.
    persistent_keys = set(module.state_dict())
    for name, buffer in module.named_buffers():
        if name not in persistent_keys and name not in state:
            _check_fixed(buffer, f"nonpersistent module buffer {name}")
            state[name] = buffer
    return functional_call(module, state, args, dict(kwargs or {}), strict=True)


def cfg_prediction(unconditional: Tensor, conditional: Tensor, guidance_scale: float = 7.5) -> Tensor:
    if unconditional.shape != conditional.shape:
        raise ValueError("CFG branches must have identical shapes.")
    # Accumulate responses in FP32 even when network inference uses autocast.
    dtype = torch.float64 if unconditional.dtype == torch.float64 else torch.float32
    uncond, cond = unconditional.to(dtype), conditional.to(dtype)
    return uncond + guidance_scale * (cond - uncond)


def _same_shape(*values: Tensor) -> None:
    if not values or values[0].ndim < 2 or any(value.shape != values[0].shape for value in values):
        raise ValueError("Responses must share shape [training_units, output_coordinates...].")


def _response_precision(value: Tensor) -> Tensor:
    return value.to(torch.float64 if value.dtype == torch.float64 else torch.float32)


def fixed_backdoor_target(
    backdoor_normal: Tensor, backdoor_trigger: Tensor, clean_normal: Tensor, clean_trigger: Tensor,
) -> Tensor:
    """Equation (7), formed once from original frozen teachers, never students."""
    values = (backdoor_normal, backdoor_trigger, clean_normal, clean_trigger)
    _same_shape(*values)
    for value in values:
        _check_fixed(value, "original teacher response")
        _check_finite(value, "original teacher response")
    bn, bt, cn, ct = map(_response_precision, values)
    return (bt - bn) - (ct - cn)


def normal_preservation_loss(
    student_normal: Tensor, student_extra: Tensor, reference_normal: Tensor, reference_extra: Tensor,
) -> Tensor:
    """Equation (9), one loss per unit, with exactly 0.5 weight for each class."""
    _same_shape(student_normal, reference_normal)
    _same_shape(student_extra, reference_extra)
    if student_normal.shape[0] != student_extra.shape[0]:
        raise ValueError("Each training unit needs paired and additional normal responses.")
    _check_fixed(reference_normal, "matched-clean normal response")
    _check_fixed(reference_extra, "matched-clean extra-normal response")
    cn = _response_precision(student_normal) - _response_precision(reference_normal)
    cq = _response_precision(student_extra) - _response_precision(reference_extra)
    return 0.5 * cn.flatten(1).square().mean(1) + 0.5 * cq.flatten(1).square().mean(1)


def paired_response_losses(
    student_normal: Tensor, student_trigger: Tensor, student_extra: Tensor,
    reference_normal: Tensor, reference_trigger: Tensor, reference_extra: Tensor,
    target_backdoor: Tensor,
) -> tuple[Tensor, Tensor]:
    """Equations (7)--(9); all arguments already contain the fixed CFG prediction."""
    _same_shape(student_normal, student_trigger, reference_normal, reference_trigger, target_backdoor)
    _check_fixed(reference_trigger, "matched-clean trigger response")
    _check_fixed(target_backdoor, "original backdoor target")
    normal = normal_preservation_loss(student_normal, student_extra, reference_normal, reference_extra)
    sn, st, rn, rt, target = map(_response_precision,
                               (student_normal, student_trigger, reference_normal, reference_trigger, target_backdoor))
    residual = ((st - sn) - (rt - rn)) - target
    backdoor = residual.flatten(1).square().mean(1)
    _check_finite(backdoor, "backdoor loss")
    _check_finite(normal, "normal loss")
    return backdoor, normal


@dataclass(frozen=True)
class WorstCaseLoss:
    objective: Tensor
    backdoor_by_unit: Tensor
    normal_by_unit: Tensor
    active_backdoor: Tensor
    active_normal: Tensor


def per_unit_worst_case_loss(backdoor: Tensor, normal: Tensor, *, beta: float = 1.0) -> WorstCaseLoss:
    """Equation (10): max over states for EACH unit, then average over units.

    State order is fixed by the caller; exact ties choose its first state.
    Upload normal loss belongs only in normal, never in backdoor.
    """
    beta = _fixed_beta(beta)
    if backdoor.ndim != 2 or normal.ndim != 2 or backdoor.shape[1] != normal.shape[1] or not backdoor.numel() or not normal.numel():
        raise ValueError("Loss arrays must be nonempty [states, training_units].")
    _check_finite(backdoor, "state backdoor losses")
    _check_finite(normal, "state normal losses")
    b, bi = backdoor.max(dim=0)
    n, ni = normal.max(dim=0)
    return WorstCaseLoss((b + beta * n).mean(), b, n, bi, ni)


@dataclass(frozen=True)
class StateGradients:
    """Small detached per-unit values/gradients; the large state graph is freed."""

    backdoor: Tensor | None
    normal: Tensor
    backdoor_grad: Tensor | None
    normal_grad: Tensor
    autograd_calls: int


def capture_state_gradients(
    backdoor: Tensor | None, normal: Tensor, scalars: CalibrationScalars,
) -> StateGradients:
    """Differentiate one state's two terms before releasing its graph.

    Pass backdoor=None for the upload state; for the MVP batch of one this
    uses two autograd calls per merge state and one for upload normal.
    """
    if normal.ndim != 1 or not normal.numel() or (backdoor is not None and backdoor.shape != normal.shape):
        raise ValueError("Expected one scalar loss per training unit.")
    terms = ([] if backdoor is None else list(backdoor.unbind())) + list(normal.unbind())
    gradients = []
    for index, loss in enumerate(terms):
        _check_finite(loss, "state loss")
        if not loss.requires_grad:
            raise ValueError("Student loss is disconnected from the trainable coefficients.")
        gradient, = torch.autograd.grad(loss, scalars.raw, retain_graph=index < len(terms) - 1)
        _check_finite(gradient, "coefficient gradient")
        gradients.append(gradient.detach())
    split = 0 if backdoor is None else backdoor.numel()
    return StateGradients(
        None if backdoor is None else backdoor.detach(), normal.detach(),
        None if backdoor is None else torch.stack(gradients[:split]),
        torch.stack(gradients[split:]), len(terms),
    )


def combine_state_gradients(
    states: Sequence[StateGradients], *, beta: float = 1.0,
) -> tuple[WorstCaseLoss, Tensor]:
    """Select the per-unit worst branches and return their mean coefficient gradient."""
    beta = _fixed_beta(beta)
    attack_states = [state for state in states if state.backdoor is not None]
    if not states or not attack_states:
        raise ValueError("Need normal states and at least one backdoor state.")
    backdoor = torch.stack([state.backdoor for state in attack_states])
    normal = torch.stack([state.normal for state in states])
    losses = per_unit_worst_case_loss(backdoor, normal, beta=beta)
    bg = torch.stack([state.backdoor_grad for state in attack_states])
    ng = torch.stack([state.normal_grad for state in states])
    units = torch.arange(normal.shape[1], device=normal.device)
    gradient = (bg[losses.active_backdoor, units] + beta * ng[losses.active_normal, units]).mean(0)
    _check_finite(gradient, "combined coefficient gradient")
    return losses, gradient


def projected_adam_step(
    scalars: CalibrationScalars, optimizer: torch.optim.Adam, gradient: Tensor,
) -> tuple[float, float]:
    """Apply a captured gradient, then the preregistered [0,32] projection."""
    parameters = [parameter for group in optimizer.param_groups for parameter in group["params"]]
    if len(parameters) != 1 or parameters[0] is not scalars.raw:
        raise ValueError("The optimizer may update only the calibration coefficients.")
    if gradient.shape != scalars.raw.shape:
        raise ValueError("Gradient shape does not match the method family.")
    _check_finite(gradient, "coefficient gradient")
    optimizer.zero_grad(set_to_none=True)
    scalars.raw.grad = gradient.detach().to(device=scalars.raw.device, dtype=scalars.raw.dtype).clone()
    optimizer.step()
    scalars.project_()
    return scalars.values()
