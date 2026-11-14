"""CPU unit tests and end-to-end mock smoke tests for MVP-v1 (Pure Paper 1)."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import pickle
import random
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any


def _stable_word_token_id(word: str) -> int:
    """Map word to a process-independent mock token ID in [3, 102]."""
    digest = hashlib.sha256(word.encode("utf-8")).digest()[:4]
    return (int.from_bytes(digest, "little") % 100) + 3

# Ensure repo root importable
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Lightweight stdlib MiniTorch / Mock ML environment ONLY when real torch is absent
# ---------------------------------------------------------------------------


def _install_mock_ml_if_missing() -> bool:
    """Install minimal autograd + SVD tensor runtime when running locally without PyTorch."""
    try:
        import torch  # noqa: F401
        import diffusers  # noqa: F401
        import transformers  # noqa: F401
        import safetensors  # noqa: F401
        import PIL  # noqa: F401
        import numpy  # noqa: F401

        return False
    except ModuleNotFoundError:
        pass

    # Seeded deterministic RNG backing mini-torch
    _rng = random.Random(42)

    def _shape_of(data: Any) -> tuple[int, ...]:
        if isinstance(data, (int, float, bool)):
            return ()
        if isinstance(data, list):
            if not data:
                return (0,)
            return (len(data),) + _shape_of(data[0])
        raise TypeError(f"Unsupported tensor data: {type(data)}")

    def _flatten(data: Any) -> list[Any]:
        if isinstance(data, (int, float, bool)):
            return [data]
        out: list[Any] = []
        for item in data:
            out.extend(_flatten(item))
        return out

    def _reshape_list(flat: list[Any], shape: tuple[int, ...]) -> Any:
        if not shape:
            return flat[0]
        if len(shape) == 1:
            return list(flat[: shape[0]])
        stride = 1
        for d in shape[1:]:
            stride *= d
        return [
            _reshape_list(flat[i * stride : (i + 1) * stride], shape[1:])
            for i in range(shape[0])
        ]

    def _prod(shape: tuple[int, ...]) -> int:
        p = 1
        for d in shape:
            p *= d
        return p

    def _broadcast_shape(sa: tuple[int, ...], sb: tuple[int, ...]) -> tuple[int, ...]:
        na, nb = len(sa), len(sb)
        n = max(na, nb)
        pa = (1,) * (n - na) + sa
        pb = (1,) * (n - nb) + sb
        res = []
        for da, db in zip(pa, pb):
            if da == db:
                res.append(da)
            elif da == 1:
                res.append(db)
            elif db == 1:
                res.append(da)
            else:
                raise ValueError(f"Cannot broadcast shapes {sa} and {sb}")
        return tuple(res)

    def _coords_from_idx(idx: int, shape: tuple[int, ...]) -> list[int]:
        coords = [0] * len(shape)
        rem = idx
        for i in range(len(shape) - 1, -1, -1):
            d = shape[i]
            coords[i] = rem % d
            rem //= d
        return coords

    def _flat_idx(coords: list[int], shape: tuple[int, ...], target_shape: tuple[int, ...]) -> int:
        offset = len(target_shape) - len(shape)
        idx = 0
        stride = 1
        for i in range(len(shape) - 1, -1, -1):
            c = 0 if shape[i] == 1 else coords[offset + i]
            idx += c * stride
            stride *= shape[i]
        return idx

    def _accum_unbroadcast(grad_out: list[float], out_shape: tuple[int, ...], in_shape: tuple[int, ...]) -> list[float]:
        in_flat = [0.0] * _prod(in_shape)
        if not in_flat:
            return in_flat
        for oi, g in enumerate(grad_out):
            coords = _coords_from_idx(oi, out_shape)
            ii = _flat_idx(coords, in_shape, out_shape)
            in_flat[ii] += g
        return in_flat

    class _DType:
        def __init__(self, name: str) -> None:
            self.name = name

        def __repr__(self) -> str:
            return f"torch.{self.name}"

    float32_dt = _DType("float32")
    float16_dt = _DType("float16")
    int64_dt = _DType("int64")
    bool_dt = _DType("bool")
    uint8_dt = _DType("uint8")

    class _GradMode:
        enabled = True

    class _NoGrad:
        def __enter__(self) -> None:
            self._prev = _GradMode.enabled
            _GradMode.enabled = False

        def __exit__(self, *args: Any) -> None:
            _GradMode.enabled = self._prev

    class MiniTensor:
        def __init__(
            self,
            data: Any,
            dtype: _DType | None = None,
            device: str = "cpu",
            requires_grad: bool = False,
            _children: tuple["MiniTensor", ...] = (),
            _backward_fn: Any = None,
        ) -> None:
            if isinstance(data, MiniTensor):
                self._shape = data._shape
                self._flat = list(data._flat)
                self.dtype = dtype or data.dtype
            else:
                self._shape = _shape_of(data)
                raw = _flatten(data)
                if dtype is None:
                    if raw and isinstance(raw[0], bool):
                        dtype = bool_dt
                    elif raw and all(isinstance(x, int) and not isinstance(x, bool) for x in raw):
                        dtype = int64_dt
                    else:
                        dtype = float32_dt
                self.dtype = dtype
                if dtype in {float32_dt, float16_dt}:
                    self._flat = [float(x) for x in raw]
                elif dtype == bool_dt:
                    self._flat = [bool(x) for x in raw]
                else:
                    self._flat = [int(x) for x in raw]
            self.device = str(device)
            self.requires_grad = bool(requires_grad and _GradMode.enabled)
            self.grad: MiniTensor | None = None
            self._prev = _children
            self._backward = _backward_fn or (lambda: None)

        @property
        def shape(self) -> tuple[int, ...]:
            return self._shape

        @property
        def ndim(self) -> int:
            return len(self._shape)

        @property
        def T(self) -> "MiniTensor":
            return self.t()

        def numel(self) -> int:
            return len(self._flat)

        def size(self, dim: int | None = None) -> Any:
            return self._shape if dim is None else self._shape[dim]

        def item(self) -> Any:
            if len(self._flat) != 1:
                raise ValueError(f"item() requires 1 element, got {len(self._flat)}")
            return self._flat[0]

        def tolist(self) -> Any:
            return _reshape_list(list(self._flat), self._shape)

        def numpy(self) -> Any:
            return np_mod.asarray(self.tolist(), dtype=float if self.dtype in {float32_dt, float16_dt} else int)

        def clone(self) -> "MiniTensor":
            out = MiniTensor._from_flat(list(self._flat), self._shape, self.dtype, self.device, self.requires_grad)
            if self.requires_grad:
                out._prev = (self,)

                def _bw() -> None:
                    if self.requires_grad and out.grad is not None:
                        _add_grad(self, out.grad._flat)

                out._backward = _bw
            return out

        def detach(self) -> "MiniTensor":
            return MiniTensor._from_flat(list(self._flat), self._shape, self.dtype, self.device, False)

        def requires_grad_(self, flag: bool = True) -> "MiniTensor":
            self.requires_grad = bool(flag)
            return self

        def cpu(self) -> "MiniTensor":
            return self

        def float(self) -> "MiniTensor":
            return self.to(float32_dt)

        def half(self) -> "MiniTensor":
            return self.to(float16_dt)

        def contiguous(self) -> "MiniTensor":
            return self

        def to(self, target: Any) -> "MiniTensor":
            if isinstance(target, _DType):
                if target == self.dtype:
                    return self
                out = MiniTensor._from_flat(
                    [float(x) if target in {float32_dt, float16_dt} else (bool(x) if target == bool_dt else int(x)) for x in self._flat],
                    self._shape,
                    target,
                    self.device,
                    self.requires_grad and target in {float32_dt, float16_dt},
                )
                if out.requires_grad:
                    out._prev = (self,)
                    out._backward = lambda: _add_grad(self, out.grad._flat) if out.grad is not None else None
                return out
            return self

        def new_zeros(self, shape: Any) -> "MiniTensor":
            if isinstance(shape, int):
                shape = (shape,)
            return MiniTensor._from_flat([0.0] * _prod(tuple(shape)), tuple(shape), float32_dt, self.device, False)

        def repeat(self, *sizes: int) -> "MiniTensor":
            if len(sizes) != len(self._shape):
                raise ValueError(f"repeat sizes {sizes} must match ndim {len(self._shape)}")
            out_shape = tuple(d * r for d, r in zip(self._shape, sizes))
            out_flat = []
            for oi in range(_prod(out_shape)):
                oc = _coords_from_idx(oi, out_shape)
                sc = [c % d for c, d in zip(oc, self._shape)]
                si = 0
                for c, d in zip(sc, self._shape):
                    si = si * d + c
                out_flat.append(self._flat[si])
            return MiniTensor._from_flat(out_flat, out_shape, self.dtype, self.device, self.requires_grad)

        @classmethod
        def _from_flat(
            cls, flat: list[Any], shape: tuple[int, ...], dtype: _DType, device: str = "cpu", requires_grad: bool = False
        ) -> "MiniTensor":
            obj = cls.__new__(cls)
            obj._flat = flat
            obj._shape = tuple(shape)
            obj.dtype = dtype
            obj.device = str(device)
            obj.requires_grad = bool(requires_grad and _GradMode.enabled)
            obj.grad = None
            obj._prev = ()
            obj._backward = lambda: None
            return obj

        def backward(self) -> None:
            if self.numel() != 1:
                raise RuntimeError("backward() only supported on scalar outputs")
            topo: list[MiniTensor] = []
            visited: set[int] = set()

            def build(v: MiniTensor) -> None:
                if id(v) not in visited:
                    visited.add(id(v))
                    for ch in v._prev:
                        build(ch)
                    topo.append(v)

            build(self)
            self.grad = MiniTensor._from_flat([1.0], self._shape, float32_dt, self.device, False)
            for node in reversed(topo):
                node._backward()

        def zero_(self) -> "MiniTensor":
            self._flat = [0.0 if self.dtype in {float32_dt, float16_dt} else 0 for _ in self._flat]
            return self

        def copy_(self, other: "MiniTensor") -> "MiniTensor":
            self._flat = list(other._flat)
            return self

        def add_(self, other: "MiniTensor") -> "MiniTensor":
            self._flat = [a + b for a, b in zip(self._flat, other._flat)]
            return self

        def sub_(self, other: "MiniTensor") -> "MiniTensor":
            self._flat = [a - b for a, b in zip(self._flat, other._flat)]
            return self

        def mul_(self, scalar: float) -> "MiniTensor":
            s = float(scalar)
            self._flat = [a * s for a in self._flat]
            return self

        def clamp_(self, min_val: float | None = None, max_val: float | None = None) -> "MiniTensor":
            res = []
            for a in self._flat:
                if min_val is not None and a < min_val:
                    a = min_val
                if max_val is not None and a > max_val:
                    a = max_val
                res.append(a)
            self._flat = res
            return self

        def clamp(self, min: float | None = None, max: float | None = None) -> "MiniTensor":
            out = self.clone()
            out.clamp_(min, max)
            return out

        def reshape(self, *shape: Any) -> "MiniTensor":
            if len(shape) == 1 and isinstance(shape[0], (tuple, list)):
                shape = tuple(shape[0])
            sh = list(shape)
            if -1 in sh:
                idx = sh.index(-1)
                known = 1
                for i, d in enumerate(sh):
                    if i != idx:
                        known *= d
                sh[idx] = self.numel() // max(1, known)
            new_shape = tuple(sh)
            req = self.requires_grad
            out = MiniTensor._from_flat(list(self._flat), new_shape, self.dtype, self.device, req)
            if req:
                out._prev = (self,)
                out._backward = lambda: _add_grad(self, out.grad._flat) if out.grad is not None else None
            return out

        def view(self, *shape: Any) -> "MiniTensor":
            return self.reshape(*shape)

        def unsqueeze(self, dim: int) -> "MiniTensor":
            d = dim if dim >= 0 else len(self._shape) + 1 + dim
            ns = list(self._shape)
            ns.insert(d, 1)
            return self.reshape(*ns)

        def permute(self, *dims: int) -> "MiniTensor":
            new_shape = tuple(self._shape[d] for d in dims)
            out_flat = [0.0] * self.numel()
            map_idx: list[int] = [0] * self.numel()
            for idx in range(self.numel()):
                in_c = _coords_from_idx(idx, self._shape)
                out_c = [in_c[d] for d in dims]
                oi = 0
                for c, dim_s in zip(out_c, new_shape):
                    oi = oi * dim_s + c
                out_flat[oi] = self._flat[idx]
                map_idx[idx] = oi
            out = MiniTensor._from_flat(out_flat, new_shape, self.dtype, self.device, self.requires_grad)
            if self.requires_grad:
                out._prev = (self,)

                def _bw() -> None:
                    if out.grad is not None:
                        _add_grad(self, [out.grad._flat[oi] for oi in map_idx])

                out._backward = _bw
            return out

        def t(self) -> "MiniTensor":
            if len(self._shape) != 2:
                raise ValueError("t() requires 2D tensor")
            r, c = self._shape
            out_flat = [0.0] * (r * c)
            for i in range(r):
                for j in range(c):
                    out_flat[j * r + i] = self._flat[i * c + j]
            out = MiniTensor._from_flat(out_flat, (c, r), self.dtype, self.device, self.requires_grad)
            if self.requires_grad:
                out._prev = (self,)

                def _bw() -> None:
                    if out.grad is None:
                        return
                    g_in = [0.0] * (r * c)
                    for i in range(r):
                        for j in range(c):
                            g_in[i * c + j] = out.grad._flat[j * r + i]
                    _add_grad(self, g_in)

                out._backward = _bw
            return out

        def abs(self) -> "MiniTensor":
            out_flat = [abs(x) for x in self._flat]
            out = MiniTensor._from_flat(out_flat, self._shape, self.dtype, self.device, self.requires_grad)
            if self.requires_grad:
                out._prev = (self,)

                def _bw() -> None:
                    if out.grad is not None:
                        _add_grad(self, [g * (1.0 if x >= 0 else -1.0) for g, x in zip(out.grad._flat, self._flat)])

                out._backward = _bw
            return out

        def sign(self) -> "MiniTensor":
            return MiniTensor._from_flat(
                [1.0 if x > 0 else (-1.0 if x < 0 else 0.0) for x in self._flat],
                self._shape,
                float32_dt,
                self.device,
                False,
            )

        def sqrt(self) -> "MiniTensor":
            out_flat = [math.sqrt(max(0.0, float(x))) for x in self._flat]
            out = MiniTensor._from_flat(out_flat, self._shape, float32_dt, self.device, self.requires_grad)
            if self.requires_grad:
                out._prev = (self,)

                def _bw() -> None:
                    if out.grad is not None:
                        _add_grad(
                            self,
                            [g / (2.0 * max(1e-8, math.sqrt(max(0.0, x)))) for g, x in zip(out.grad._flat, self._flat)],
                        )

                out._backward = _bw
            return out

        def sum(self, dim: int | None = None, keepdim: bool = False) -> "MiniTensor":
            if dim is None:
                val = float(sum(self._flat))
                out = MiniTensor._from_flat([val], (), float32_dt, self.device, self.requires_grad)
                if self.requires_grad:
                    out._prev = (self,)
                    out._backward = lambda: _add_grad(self, [out.grad._flat[0]] * self.numel()) if out.grad is not None else None
                return out
            d = dim if dim >= 0 else len(self._shape) + dim
            ns = list(self._shape)
            red = ns[d]
            if keepdim:
                ns[d] = 1
            else:
                ns.pop(d)
            out_shape = tuple(ns)
            out_flat = [0.0] * max(1, _prod(out_shape))
            back_map: list[int] = [0] * self.numel()
            for idx in range(self.numel()):
                coords = _coords_from_idx(idx, self._shape)
                if keepdim:
                    coords[d] = 0
                else:
                    coords.pop(d)
                oi = 0
                for c, s in zip(coords, out_shape):
                    oi = oi * s + c
                out_flat[oi] += float(self._flat[idx])
                back_map[idx] = oi
            out = MiniTensor._from_flat(out_flat, out_shape, float32_dt, self.device, self.requires_grad)
            if self.requires_grad:
                out._prev = (self,)

                def _bw() -> None:
                    if out.grad is not None:
                        _add_grad(self, [out.grad._flat[oi] for oi in back_map])

                out._backward = _bw
            return out

        def mean(self, dim: int | None = None, keepdim: bool = False) -> "MiniTensor":
            cnt = self.numel() if dim is None else self._shape[dim]
            return self.sum(dim=dim, keepdim=keepdim) * (1.0 / max(1, cnt))

        def norm(self, dim: int | None = None, keepdim: bool = False) -> "MiniTensor":
            return (self * self).sum(dim=dim, keepdim=keepdim).sqrt()

        def __neg__(self) -> "MiniTensor":
            return self * -1.0

        def __add__(self, other: Any) -> "MiniTensor":
            return _binary_op(self, other, "add")

        def __radd__(self, other: Any) -> "MiniTensor":
            return _binary_op(other, self, "add")

        def __sub__(self, other: Any) -> "MiniTensor":
            return _binary_op(self, other, "sub")

        def __rsub__(self, other: Any) -> "MiniTensor":
            return _binary_op(other, self, "sub")

        def __mul__(self, other: Any) -> "MiniTensor":
            return _binary_op(self, other, "mul")

        def __rmul__(self, other: Any) -> "MiniTensor":
            return _binary_op(other, self, "mul")

        def __truediv__(self, other: Any) -> "MiniTensor":
            return _binary_op(self, other, "div")

        def __rtruediv__(self, other: Any) -> "MiniTensor":
            return _binary_op(other, self, "div")

        def __matmul__(self, other: "MiniTensor") -> "MiniTensor":
            return _matmul(self, other)

        def __gt__(self, other: Any) -> "MiniTensor":
            return _cmp_op(self, other, lambda a, b: a > b)

        def __ge__(self, other: Any) -> "MiniTensor":
            return _cmp_op(self, other, lambda a, b: a >= b)

        def __lt__(self, other: Any) -> "MiniTensor":
            return _cmp_op(self, other, lambda a, b: a < b)

        def __le__(self, other: Any) -> "MiniTensor":
            return _cmp_op(self, other, lambda a, b: a <= b)

        def __ne__(self, other: Any) -> "MiniTensor":
            return _cmp_op(self, other, lambda a, b: a != b)

        def __eq__(self, other: Any) -> "MiniTensor":  # type: ignore[override]
            return _cmp_op(self, other, lambda a, b: a == b)

        def __or__(self, other: Any) -> "MiniTensor":
            return _cmp_op(self, other, lambda a, b: bool(a) or bool(b))

        def __getitem__(self, key: Any) -> "MiniTensor":
            if not isinstance(key, tuple):
                key = (key,)
            # Expand slicing specs along each axis
            axes: list[Any] = list(key) + [slice(None)] * (len(self._shape) - len(key))
            chosen: list[list[int]] = []
            squeeze_dims: list[int] = []
            for d_i, (spec, dim_len) in enumerate(zip(axes, self._shape)):
                if isinstance(spec, int):
                    idx = spec if spec >= 0 else dim_len + spec
                    chosen.append([idx])
                    squeeze_dims.append(d_i)
                elif isinstance(spec, slice):
                    chosen.append(list(range(*spec.indices(dim_len))))
                else:
                    raise TypeError(f"Unsupported index spec: {spec!r}")

            out_shape = tuple(len(c) for i, c in enumerate(chosen) if i not in squeeze_dims)
            src_indices: list[int] = []

            def _walk(d_i: int, cur_coords: list[int]) -> None:
                if d_i == len(chosen):
                    flat_i = 0
                    for cc, ds in zip(cur_coords, self._shape):
                        flat_i = flat_i * ds + cc
                    src_indices.append(flat_i)
                    return
                for v in chosen[d_i]:
                    _walk(d_i + 1, cur_coords + [v])

            _walk(0, [])
            out_flat = [self._flat[si] for si in src_indices]
            out = MiniTensor._from_flat(out_flat, out_shape, self.dtype, self.device, self.requires_grad)
            if self.requires_grad:
                out._prev = (self,)

                def _bw() -> None:
                    if out.grad is None:
                        return
                    g_self = [0.0] * self.numel()
                    for og, si in zip(out.grad._flat, src_indices):
                        g_self[si] += og
                    _add_grad(self, g_self)

                out._backward = _bw
            return out

    def _add_grad(tensor: MiniTensor, grad_flat: list[float]) -> None:
        if not tensor.requires_grad:
            return
        if tensor.grad is None:
            tensor.grad = MiniTensor._from_flat(list(grad_flat), tensor._shape, float32_dt, tensor.device, False)
        else:
            tensor.grad._flat = [a + b for a, b in zip(tensor.grad._flat, grad_flat)]

    def _as_tensor(val: Any, device: str = "cpu") -> MiniTensor:
        if isinstance(val, MiniTensor):
            return val
        return MiniTensor(val, dtype=float32_dt, device=device)

    def _cmp_op(a: MiniTensor, b: Any, fn: Any) -> MiniTensor:
        tb = _as_tensor(b, a.device)
        out_shape = _broadcast_shape(a._shape, tb._shape)
        out_flat = []
        for oi in range(_prod(out_shape)):
            c = _coords_from_idx(oi, out_shape)
            va = a._flat[_flat_idx(c, a._shape, out_shape)]
            vb = tb._flat[_flat_idx(c, tb._shape, out_shape)]
            out_flat.append(bool(fn(va, vb)))
        return MiniTensor._from_flat(out_flat, out_shape, bool_dt, a.device, False)

    def _binary_op(a_raw: Any, b_raw: Any, op: str) -> MiniTensor:
        a = _as_tensor(a_raw)
        b = _as_tensor(b_raw, a.device)
        out_shape = _broadcast_shape(a._shape, b._shape)
        n = _prod(out_shape)
        out_flat: list[float] = [0.0] * n
        for oi in range(n):
            c = _coords_from_idx(oi, out_shape)
            va = float(a._flat[_flat_idx(c, a._shape, out_shape)])
            vb = float(b._flat[_flat_idx(c, b._shape, out_shape)])
            if op == "add":
                out_flat[oi] = va + vb
            elif op == "sub":
                out_flat[oi] = va - vb
            elif op == "mul":
                out_flat[oi] = va * vb
            elif op == "div":
                out_flat[oi] = va / vb
        req = a.requires_grad or b.requires_grad
        out = MiniTensor._from_flat(out_flat, out_shape, float32_dt, a.device, req)
        if req:
            out._prev = tuple(t for t in (a, b) if t.requires_grad or t._prev)

            def _bw() -> None:
                if out.grad is None:
                    return
                ga_out = [0.0] * n
                gb_out = [0.0] * n
                for oi in range(n):
                    c = _coords_from_idx(oi, out_shape)
                    va = float(a._flat[_flat_idx(c, a._shape, out_shape)])
                    vb = float(b._flat[_flat_idx(c, b._shape, out_shape)])
                    go = float(out.grad._flat[oi])
                    if op == "add":
                        ga_out[oi] = go
                        gb_out[oi] = go
                    elif op == "sub":
                        ga_out[oi] = go
                        gb_out[oi] = -go
                    elif op == "mul":
                        ga_out[oi] = go * vb
                        gb_out[oi] = go * va
                    elif op == "div":
                        ga_out[oi] = go / vb
                        gb_out[oi] = -go * va / (vb * vb)
                if a.requires_grad:
                    _add_grad(a, _accum_unbroadcast(ga_out, out_shape, a._shape))
                if b.requires_grad:
                    _add_grad(b, _accum_unbroadcast(gb_out, out_shape, b._shape))

            out._backward = _bw
        return out

    def _matmul(a: MiniTensor, b: MiniTensor) -> MiniTensor:
        if a.ndim != 2 or b.ndim != 2 or a.shape[1] != b.shape[0]:
            raise ValueError(f"2D matmul shape mismatch: {a.shape} @ {b.shape}")
        m, k = a.shape
        _, n = b.shape
        af, bf = a._flat, b._flat
        out_flat = [0.0] * (m * n)
        for i in range(m):
            row_off = i * k
            for j in range(n):
                s = 0.0
                for p in range(k):
                    s += af[row_off + p] * bf[p * n + j]
                out_flat[i * n + j] = s
        req = a.requires_grad or b.requires_grad
        out = MiniTensor._from_flat(out_flat, (m, n), float32_dt, a.device, req)
        if req:
            out._prev = (a, b)

            def _bw() -> None:
                if out.grad is None:
                    return
                gf = out.grad._flat
                if a.requires_grad:
                    ga = [0.0] * (m * k)
                    for i in range(m):
                        for p in range(k):
                            s = 0.0
                            for j in range(n):
                                s += gf[i * n + j] * bf[p * n + j]
                            ga[i * k + p] = s
                    _add_grad(a, ga)
                if b.requires_grad:
                    gb = [0.0] * (k * n)
                    for p in range(k):
                        for j in range(n):
                            s = 0.0
                            for i in range(m):
                                s += af[i * k + p] * gf[i * n + j]
                            gb[p * n + j] = s
                    _add_grad(b, gb)

            out._backward = _bw
        return out

    # Pure-Python Jacobi SVD via symmetric eigendecomposition of M @ M^T or M^T @ M
    def _jacobi_eigh(sym: list[list[float]], max_iters: int = 80) -> tuple[list[float], list[list[float]]]:
        n = len(sym)
        a = [row[:] for row in sym]
        v = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
        for _ in range(max_iters):
            best = 0.0
            p, q = 0, 1
            for i in range(n):
                for j in range(i + 1, n):
                    val = abs(a[i][j])
                    if val > best:
                        best = val
                        p, q = i, j
            if best < 1e-11:
                break
            app, aqq, apq = a[p][p], a[q][q], a[p][q]
            tau = (aqq - app) / (2.0 * apq)
            t = (1.0 / (abs(tau) + math.sqrt(1.0 + tau * tau))) * (1.0 if tau >= 0 else -1.0)
            c = 1.0 / math.sqrt(1.0 + t * t)
            s = t * c
            a[p][p] = app - t * apq
            a[q][q] = aqq + t * apq
            a[p][q] = 0.0
            a[q][p] = 0.0
            for r in range(n):
                if r != p and r != q:
                    arp, arq = a[r][p], a[r][q]
                    a[r][p] = c * arp - s * arq
                    a[p][r] = a[r][p]
                    a[r][q] = s * arp + c * arq
                    a[q][r] = a[r][q]
            for r in range(n):
                vrp, vrq = v[r][p], v[r][q]
                v[r][p] = c * vrp - s * vrq
                v[r][q] = s * vrp + c * vrq
        order = sorted(range(n), key=lambda i: a[i][i], reverse=True)
        evals = [a[i][i] for i in order]
        evecs = [[v[r][i] for i in order] for r in range(n)]
        return evals, evecs

    def _svd(mat: MiniTensor, full_matrices: bool = False) -> tuple[MiniTensor, MiniTensor, MiniTensor]:
        m, n = mat.shape
        rows = mat.tolist()
        k = min(m, n)
        if m >= n:
            mtm = [[sum(rows[r][i] * rows[r][j] for r in range(m)) for j in range(n)] for i in range(n)]
            evals, v_cols = _jacobi_eigh(mtm)
            s_vals = [math.sqrt(max(0.0, ev)) for ev in evals[:k]]
            vh_rows = [[v_cols[j][i] for j in range(n)] for i in range(k)]
            u_cols: list[list[float]] = []
            for i in range(k):
                if s_vals[i] > 1e-9:
                    col = [sum(rows[r][c] * v_cols[c][i] for c in range(n)) / s_vals[i] for r in range(m)]
                else:
                    col = [1.0 if r == i else 0.0 for r in range(m)]
                    # Orthogonalize against previous cols
                    for prev in u_cols:
                        dot = sum(col[r] * prev[r] for r in range(m))
                        col = [col[r] - dot * prev[r] for r in range(m)]
                    nrm = math.sqrt(max(1e-12, sum(x * x for x in col)))
                    col = [x / nrm for x in col]
                u_cols.append(col)
            u_rows = [[u_cols[i][r] for i in range(k)] for r in range(m)]
        else:
            mmt = [[sum(rows[i][c] * rows[j][c] for c in range(n)) for j in range(m)] for i in range(m)]
            evals, u_cols_mat = _jacobi_eigh(mmt)
            s_vals = [math.sqrt(max(0.0, ev)) for ev in evals[:k]]
            u_rows = [[u_cols_mat[r][i] for i in range(k)] for r in range(m)]
            vh_rows = []
            for i in range(k):
                if s_vals[i] > 1e-9:
                    row = [sum(rows[r][c] * u_cols_mat[r][i] for r in range(m)) / s_vals[i] for c in range(n)]
                else:
                    row = [1.0 if c == i else 0.0 for c in range(n)]
                    for prev in vh_rows:
                        dot = sum(row[c] * prev[c] for c in range(n))
                        row = [row[c] - dot * prev[c] for c in range(n)]
                    nrm = math.sqrt(max(1e-12, sum(x * x for x in row)))
                    row = [x / nrm for x in row]
                vh_rows.append(row)
        return MiniTensor(u_rows), MiniTensor(s_vals), MiniTensor(vh_rows)

    # Assemble fake `torch` module
    torch_mod = types.ModuleType("torch")
    torch_mod.Tensor = MiniTensor
    torch_mod.float32 = float32_dt
    torch_mod.float16 = float16_dt
    torch_mod.int64 = int64_dt
    torch_mod.bool = bool_dt
    torch_mod.uint8 = uint8_dt

    class Generator:
        def __init__(self, device: str = "cpu") -> None:
            self._rng = random.Random(42)

        def manual_seed(self, seed: int) -> "Generator":
            self._rng.seed(int(seed))
            return self

    torch_mod.Generator = Generator
    torch_mod.manual_seed = lambda seed: _rng.seed(int(seed))
    torch_mod.cuda = types.SimpleNamespace(is_available=lambda: False)
    torch_mod.is_tensor = lambda x: isinstance(x, MiniTensor)
    torch_mod.no_grad = _NoGrad

    def _zeros(shape: Any, dtype: _DType = float32_dt, device: str = "cpu") -> MiniTensor:
        if isinstance(shape, int):
            shape = (shape,)
        return MiniTensor._from_flat([0.0] * _prod(tuple(shape)), tuple(shape), dtype, device)

    def _ones(shape: Any, dtype: _DType = float32_dt, device: str = "cpu") -> MiniTensor:
        if isinstance(shape, int):
            shape = (shape,)
        return MiniTensor._from_flat([1.0] * _prod(tuple(shape)), tuple(shape), dtype, device)

    def _randn(shape: Any, generator: Generator | None = None, dtype: _DType = float32_dt, device: str = "cpu") -> MiniTensor:
        if isinstance(shape, int):
            shape = (shape,)
        g = generator._rng if generator is not None else _rng
        return MiniTensor._from_flat([g.gauss(0.0, 1.0) for _ in range(_prod(tuple(shape)))], tuple(shape), dtype, device)

    def _rand(shape: Any, generator: Generator | None = None, dtype: _DType = float32_dt, device: str = "cpu") -> MiniTensor:
        if isinstance(shape, int):
            shape = (shape,)
        g = generator._rng if generator is not None else _rng
        return MiniTensor._from_flat([g.random() for _ in range(_prod(tuple(shape)))], tuple(shape), dtype, device)

    def _randint(low: int, high: int, size: tuple[int, ...], generator: Generator | None = None) -> MiniTensor:
        g = generator._rng if generator is not None else _rng
        return MiniTensor._from_flat([g.randrange(low, high) for _ in range(_prod(size))], size, int64_dt)

    def _from_numpy(arr: Any) -> MiniTensor:
        return MiniTensor(arr.tolist() if hasattr(arr, "tolist") else arr)

    def _cat(tensors: list[MiniTensor], dim: int = 0) -> MiniTensor:
        d = dim if dim >= 0 else tensors[0].ndim + dim
        res_shape = list(tensors[0].shape)
        res_shape[d] = sum(t.shape[d] for t in tensors)
        out_flat = [0.0] * _prod(tuple(res_shape))
        src_map: list[tuple[int, int, int]] = []
        offset = 0
        for ti, t in enumerate(tensors):
            for idx in range(t.numel()):
                c = _coords_from_idx(idx, t.shape)
                c[d] += offset
                oi = 0
                for cc, ss in zip(c, res_shape):
                    oi = oi * ss + cc
                out_flat[oi] = t._flat[idx]
                src_map.append((oi, ti, idx))
            offset += t.shape[d]
        req = any(t.requires_grad for t in tensors)
        out = MiniTensor._from_flat(out_flat, tuple(res_shape), tensors[0].dtype, tensors[0].device, req)
        if req:
            out._prev = tuple(tensors)

            def _bw() -> None:
                if out.grad is None:
                    return
                grads = [[0.0] * t.numel() for t in tensors]
                for oi, ti, si in src_map:
                    grads[ti][si] += out.grad._flat[oi]
                for t, gf in zip(tensors, grads):
                    _add_grad(t, gf)

            out._backward = _bw
        return out

    def _stack(tensors: list[MiniTensor], dim: int = 0) -> MiniTensor:
        return _cat([t.unsqueeze(dim) for t in tensors], dim=dim)

    def _topk(tensor: MiniTensor, k: int, largest: bool = True) -> tuple[MiniTensor, MiniTensor]:
        flat = tensor._flat
        order = sorted(range(len(flat)), key=lambda i: flat[i], reverse=largest)[:k]
        vals = [flat[i] for i in order]
        out = MiniTensor._from_flat(vals, (k,), tensor.dtype, tensor.device, tensor.requires_grad)
        if tensor.requires_grad:
            out._prev = (tensor,)

            def _bw() -> None:
                if out.grad is not None:
                    g = [0.0] * len(flat)
                    for gi, si in enumerate(order):
                        g[si] += out.grad._flat[gi]
                    _add_grad(tensor, g)

            out._backward = _bw
        return out, MiniTensor._from_flat(order, (k,), int64_dt, tensor.device, False)

    def _argmax(tensor: MiniTensor) -> MiniTensor:
        best_i = max(range(len(tensor._flat)), key=lambda i: tensor._flat[i])
        return MiniTensor._from_flat([best_i], (), int64_dt, tensor.device, False)

    torch_mod.zeros = _zeros
    torch_mod.ones = _ones
    torch_mod.randn = _randn
    torch_mod.rand = _rand
    torch_mod.randint = _randint
    torch_mod.tensor = lambda x, dtype=None, device="cpu": MiniTensor(x, dtype=dtype, device=device)
    def _eigh(mat: MiniTensor) -> tuple[MiniTensor, MiniTensor]:
        n = mat.shape[0]
        rows = mat.tolist()
        evals_desc, evecs_desc = _jacobi_eigh(rows, max_iters=max(200, 10 * n * n))
        evals_asc = list(reversed(evals_desc))
        evecs_asc = [list(reversed(r)) for r in evecs_desc]
        return MiniTensor(evals_asc, dtype=float32_dt), MiniTensor(evecs_asc, dtype=float32_dt)

    def _eye(n: int, dtype: _DType = float32_dt, device: str = "cpu") -> MiniTensor:
        return MiniTensor([[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)], dtype=dtype, device=device)

    torch_mod.eye = _eye
    torch_mod.from_numpy = _from_numpy
    torch_mod.cat = _cat
    torch_mod.stack = _stack
    torch_mod.topk = _topk
    torch_mod.argmax = _argmax
    torch_mod.sign = lambda x: x.sign()
    torch_mod.sqrt = lambda x: x.sqrt()
    torch_mod.abs = lambda x: x.abs()
    torch_mod.max = lambda x: MiniTensor(max(x._flat))
    torch_mod.linalg = types.SimpleNamespace(svd=_svd, eigh=_eigh)
    def _to_plain(o: Any) -> Any:
        if isinstance(o, MiniTensor):
            return {"__minitensor__": o.tolist(), "dtype": o.dtype.name}
        if isinstance(o, dict):
            return {k: _to_plain(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_to_plain(v) for v in o]
        return o

    def _from_plain(o: Any) -> Any:
        if isinstance(o, dict):
            if "__minitensor__" in o:
                dt = {"float32": float32_dt, "float16": float16_dt, "int64": int64_dt, "bool": bool_dt}.get(
                    o.get("dtype", "float32"), float32_dt
                )
                return MiniTensor(o["__minitensor__"], dtype=dt)
            return {k: _from_plain(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_from_plain(v) for v in o]
        return o

    torch_mod.save = lambda obj, path: Path(path).write_bytes(pickle.dumps(_to_plain(obj)))
    torch_mod.load = lambda path, map_location=None: _from_plain(pickle.loads(Path(path).read_bytes()))

    # nn & nn.functional
    nn_mod = types.ModuleType("torch.nn")

    class Parameter(MiniTensor):
        def __new__(cls, data: MiniTensor, requires_grad: bool = True) -> "Parameter":
            return data.clone().requires_grad_(requires_grad)  # type: ignore[return-value]

    class Module:
        def __init__(self) -> None:
            object.__setattr__(self, "_modules", {})
            object.__setattr__(self, "_parameters", {})

        def __setattr__(self, name: str, value: Any) -> None:
            if isinstance(value, MiniTensor) and value.requires_grad and name in getattr(self, "_parameters", {}):
                self._parameters[name] = value
            elif isinstance(value, Module):
                self._modules[name] = value
                if name in self._parameters:
                    del self._parameters[name]
            elif isinstance(value, MiniTensor) and getattr(value, "requires_grad", False):
                self._parameters[name] = value
            object.__setattr__(self, name, value)

        def add_module(self, name: str, mod: "Module") -> None:
            setattr(self, name, mod)

        def register_parameter(self, name: str, p: MiniTensor) -> None:
            self._parameters[name] = p
            object.__setattr__(self, name, p)

        def parameters(self) -> Any:
            return iter(p for _, p in self.named_parameters())

        def named_parameters(self, prefix: str = "") -> list[tuple[str, MiniTensor]]:
            out: list[tuple[str, MiniTensor]] = []
            seen: set[int] = set()
            for pname, p in getattr(self, "__dict__", {}).items():
                if isinstance(p, MiniTensor) and id(p) not in seen and not pname.startswith("_"):
                    seen.add(id(p))
                    out.append((f"{prefix}.{pname}" if prefix else pname, p))
            for mname, mod in self._modules.items():
                sub = f"{prefix}.{mname}" if prefix else mname
                out.extend(mod.named_parameters(sub))
            return out

        def named_modules(self, prefix: str = "") -> list[tuple[str, "Module"]]:
            out = [(prefix, self)]
            for mname, mod in self._modules.items():
                sub = f"{prefix}.{mname}" if prefix else mname
                out.extend(mod.named_modules(sub))
            return out

        def state_dict(self) -> dict[str, MiniTensor]:
            return {k: v.detach().clone() for k, v in self.named_parameters()}

        def to(self, *args: Any) -> "Module":
            return self

        def eval(self) -> "Module":
            return self

        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            return self.forward(*args, **kwargs)

    class ModuleList(Module):
        def __init__(self, items: list[Module]) -> None:
            super().__init__()
            self._items = list(items)
            for idx, m in enumerate(self._items):
                self._modules[str(idx)] = m

        def __getitem__(self, idx: int) -> Module:
            return self._items[idx]

        def __setitem__(self, idx: int, val: Module) -> None:
            self._items[idx] = val
            self._modules[str(idx)] = val

        def __len__(self) -> int:
            return len(self._items)

        def __iter__(self) -> Any:
            return iter(self._items)

    class Linear(Module):
        def __init__(self, in_features: int, out_features: int, bias: bool = False) -> None:
            super().__init__()
            self.in_features = in_features
            self.out_features = out_features
            w = MiniTensor._from_flat(
                [_rng.gauss(0.0, 0.1) for _ in range(out_features * in_features)],
                (out_features, in_features),
                float32_dt,
                requires_grad=True,
            )
            self.weight = w
            self.bias = None

        def forward(self, x: MiniTensor) -> MiniTensor:
            return F_linear(x, self.weight, self.bias)

    def F_linear(x: MiniTensor, w: MiniTensor, bias: Any = None) -> MiniTensor:
        orig = x.shape
        x2 = x.reshape(-1, orig[-1])
        out2 = x2 @ w.t()
        return out2.reshape(*orig[:-1], w.shape[0])

    def F_mse_loss(pred: MiniTensor, target: MiniTensor) -> MiniTensor:
        diff = pred - target
        return (diff * diff).mean()

    def F_softmax(logits: MiniTensor, dim: int = -1) -> MiniTensor:
        vals = logits._flat
        mx = max(vals)
        ex = [math.exp(v - mx) for v in vals]
        s = sum(ex)
        return MiniTensor._from_flat([e / s for e in ex], logits.shape, float32_dt, logits.device, False)

    F_mod = types.ModuleType("torch.nn.functional")
    F_mod.linear = F_linear
    F_mod.mse_loss = F_mse_loss
    F_mod.softmax = F_softmax

    nn_mod.Parameter = Parameter
    nn_mod.Module = Module
    nn_mod.ModuleList = ModuleList
    nn_mod.Linear = Linear
    nn_mod.functional = F_mod
    nn_utils_mod = types.ModuleType("torch.nn.utils")
    nn_utils_mod.clip_grad_norm_ = lambda params, max_norm: 0.0
    nn_mod.utils = nn_utils_mod

    optim_mod = types.ModuleType("torch.optim")

    class AdamW:
        def __init__(self, params: list[MiniTensor], lr: float = 1e-3, weight_decay: float = 0.0) -> None:
            self.params = list(params)
            self.lr = float(lr)
            self.t = 0
            self.m = [[0.0] * p.numel() for p in self.params]
            self.v = [[0.0] * p.numel() for p in self.params]

        def zero_grad(self) -> None:
            for p in self.params:
                p.grad = None

        def step(self) -> None:
            self.t += 1
            b1, b2, eps = 0.9, 0.999, 1e-8
            for i, p in enumerate(self.params):
                if p.grad is None:
                    continue
                gf = p.grad._flat
                for j in range(len(p._flat)):
                    g = gf[j]
                    self.m[i][j] = b1 * self.m[i][j] + (1.0 - b1) * g
                    self.v[i][j] = b2 * self.v[i][j] + (1.0 - b2) * (g * g)
                    m_hat = self.m[i][j] / (1.0 - b1**self.t)
                    v_hat = self.v[i][j] / (1.0 - b2**self.t)
                    p._flat[j] -= self.lr * m_hat / (math.sqrt(v_hat) + eps)

        def state_dict(self) -> dict[str, Any]:
            return {"t": self.t, "m": copy.deepcopy(self.m), "v": copy.deepcopy(self.v)}

        def load_state_dict(self, sd: dict[str, Any]) -> None:
            self.t = sd["t"]
            self.m = copy.deepcopy(sd["m"])
            self.v = copy.deepcopy(sd["v"])

    optim_mod.AdamW = AdamW

    torch_mod.nn = nn_mod
    torch_mod.optim = optim_mod

    # Minimal numpy & PIL mocks for E2E mock smoke test
    np_mod = types.ModuleType("numpy")
    np_mod.float32 = "float32"
    np_mod.uint8 = "uint8"

    class MiniArray:
        def __init__(self, data: Any, dtype: str = "float32") -> None:
            self.data = data
            self.dtype = dtype

        def tolist(self) -> Any:
            return self.data

        def round(self) -> "MiniArray":
            return self

        def astype(self, dt: Any) -> "MiniArray":
            return MiniArray(self.data, str(dt))

        def __truediv__(self, s: float) -> Any:
            return self

        def __sub__(self, s: float) -> Any:
            return self

        def __mul__(self, s: float) -> "MiniArray":
            return self

    np_mod.asarray = lambda obj, dtype=None: MiniArray(
        getattr(obj, "data", obj.tolist() if hasattr(obj, "tolist") else [[[128, 128, 128]]])
    )

    pil_mod = types.ModuleType("PIL")

    class _MiniImage:
        def __init__(self, mode: str = "RGB", size: tuple[int, int] = (32, 32), color: Any = (128, 128, 128)) -> None:
            self.mode = mode
            self.size = size
            self.data = [[[color[0], color[1], color[2]] for _ in range(size[0])] for _ in range(size[1])]
            self.pasted: list[tuple[int, int]] = []

        def convert(self, m: str) -> "_MiniImage":
            return self

        def resize(self, sz: tuple[int, int], resample: Any = None) -> "_MiniImage":
            return _MiniImage(self.mode, sz)

        def paste(self, im: "_MiniImage", box: tuple[int, int]) -> None:
            self.pasted.append(box)

        def save(self, path: str | Path) -> None:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            # Minimal valid PNG magic + dimensions metadata for tests
            p.write_bytes(b"\x89PNG\r\n\x1a\n" + f"{self.size[0]}x{self.size[1]}".encode("utf-8"))

        def __enter__(self) -> "_MiniImage":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

    class _ImageDrawCls:
        @staticmethod
        def Draw(canvas: _MiniImage) -> Any:
            return types.SimpleNamespace(
                text=lambda xy, text, fill=None: None,
                rectangle=lambda box, outline=None: None,
            )

    image_mod = types.ModuleType("PIL.Image")
    image_mod.BICUBIC = 3
    image_mod.Resampling = types.SimpleNamespace(BICUBIC=3)
    image_mod.new = lambda mode, size, color=(0, 0, 0): _MiniImage(mode, size, color)
    image_mod.open = lambda path: _MiniImage("RGB", (32, 32))
    image_mod.fromarray = lambda arr: _MiniImage("RGB", (32, 32))
    imagedraw_mod = types.ModuleType("PIL.ImageDraw")
    imagedraw_mod.Draw = _ImageDrawCls.Draw
    pil_mod.Image = image_mod
    pil_mod.ImageDraw = imagedraw_mod

    # Minimal safetensors.torch
    sf_pkg = types.ModuleType("safetensors")
    sf_torch = types.ModuleType("safetensors.torch")
    sf_torch.save_file = lambda tensors, path: Path(path).write_bytes(
        pickle.dumps({k: v.tolist() for k, v in tensors.items()})
    )
    sf_torch.load_file = lambda path, device="cpu": {
        k: MiniTensor(v, dtype=float32_dt, device=device)
        for k, v in pickle.loads(Path(path).read_bytes()).items()
    }
    sf_pkg.torch = sf_torch

    # Minimal diffusers & transformers stubs for offline E2E mock run
    diffusers_mod = types.ModuleType("diffusers")
    transformers_mod = types.ModuleType("transformers")

    class _MockAttn(Module):
        def __init__(self, d_model: int, d_ctx: int) -> None:
            super().__init__()
            self.to_q = Linear(d_model, d_model)
            self.to_k = Linear(d_ctx, d_model)
            self.to_v = Linear(d_ctx, d_model)
            self.to_out = ModuleList([Linear(d_model, d_model)])

    class _MockTransformerBlock(Module):
        def __init__(self, d_model: int, d_ctx: int) -> None:
            super().__init__()
            self.attn1 = _MockAttn(d_model, d_model)
            self.attn2 = _MockAttn(d_model, d_ctx)

    class _MockTransformer2D(Module):
        def __init__(self, d_model: int, d_ctx: int) -> None:
            super().__init__()
            self.transformer_blocks = ModuleList([_MockTransformerBlock(d_model, d_ctx)])

    class _MockUNetBlock(Module):
        def __init__(self, d_model: int, d_ctx: int) -> None:
            super().__init__()
            self.attentions = ModuleList([_MockTransformer2D(d_model, d_ctx)])

    class MockSD15UNet(Module):
        def __init__(self, d_model: int = 8, d_ctx: int = 8) -> None:
            super().__init__()
            self.down_blocks = ModuleList([_MockUNetBlock(d_model, d_ctx)])
            self.mid_block = _MockUNetBlock(d_model, d_ctx)
            self.up_blocks = ModuleList(
                [
                    _MockUNetBlock(d_model, d_ctx),
                    _MockUNetBlock(d_model, d_ctx),
                    _MockUNetBlock(d_model, d_ctx),
                    _MockUNetBlock(d_model, d_ctx),
                ]
            )
            self.proj_head = Linear(d_model, 4)

        def forward(self, sample: MiniTensor, timestep: Any, encoder_hidden_states: MiniTensor) -> Any:
            b, c, h, w = sample.shape
            # Flatten batch x spatial -> d_model=8 representation mixed with text context
            ctx_vec = encoder_hidden_states.mean(dim=1)  # (b, d_ctx)
            # Route sequentially through down -> mid -> up_blocks[1] -> up_blocks[2] cross/self-attentions
            x_hid = sample.reshape(b, c * h * w)[:, : self.mid_block.attentions[0].transformer_blocks[0].attn2.to_q.in_features]
            for blk in (
                self.down_blocks[0],
                self.mid_block,
                self.up_blocks[1],
                self.up_blocks[2],
            ):
                tb = blk.attentions[0].transformer_blocks[0]
                q = tb.attn2.to_q(x_hid)
                k = tb.attn2.to_k(ctx_vec)
                v = tb.attn2.to_v(ctx_vec)
                attn_mix = tb.attn2.to_out[0](q + k * 0.25 + v * 0.25)
                x_hid = tb.attn1.to_out[0](tb.attn1.to_q(x_hid)) * 0.5 + attn_mix
            pred = self.proj_head(x_hid).reshape(b, 4, 1, 1)
            # Broadcast to spatial sample shape
            zero_spatial = sample * 0.0
            return types.SimpleNamespace(sample=zero_spatial + pred)

    class MockTextEncoder(Module):
        def __init__(self, d_ctx: int = 8) -> None:
            super().__init__()
            self.text_model = types.SimpleNamespace(
                encoder=types.SimpleNamespace(
                    layers=ModuleList(
                        [
                            types.SimpleNamespace(
                                self_attn=_MockSelfAttn(d_ctx)
                            )
                        ]
                    )
                )
            )
            self.d_ctx = d_ctx

        def named_modules(self, prefix: str = "") -> list[tuple[str, Any]]:
            # Expose self_attn linear modules cleanly for PoisonLoRA optional TE wrapping
            out = [(prefix, self)]
            sa = self.text_model.encoder.layers[0].self_attn
            for pn in ("q_proj", "k_proj", "v_proj", "out_proj"):
                sub = f"{prefix}.text_model.encoder.layers.0.self_attn.{pn}".lstrip(".")
                out.append((sub, getattr(sa, pn)))
            return out

        def forward(self, input_ids: MiniTensor) -> tuple[MiniTensor]:
            # Map token IDs deterministically to (B, 4, 8)
            rows = []
            for b in range(input_ids.shape[0]):
                seq = []
                for t in range(input_ids.shape[1]):
                    tid = int(input_ids._flat[b * input_ids.shape[1] + t])
                    vec = [math.sin((tid + 1) * (d + 1) * 0.7) for d in range(self.d_ctx)]
                    seq.append(vec)
                rows.append(seq)
            x = MiniTensor(rows)
            sa = self.text_model.encoder.layers[0].self_attn
            y = sa.out_proj(sa.q_proj(x) + sa.k_proj(x) + sa.v_proj(x))
            return (y * 0.25 + x,)

    class _MockSelfAttn(Module):
        def __init__(self, d: int) -> None:
            super().__init__()
            self.q_proj = Linear(d, d)
            self.k_proj = Linear(d, d)
            self.v_proj = Linear(d, d)
            self.out_proj = Linear(d, d)

    class MockTokenizer:
        model_max_length = 4
        bos_token_id = 1
        eos_token_id = 2
        pad_token_id = 0

        @classmethod
        def from_pretrained(cls, *args: Any, **kwargs: Any) -> "MockTokenizer":
            return cls()

        def __call__(self, texts: list[str], **kwargs: Any) -> dict[str, MiniTensor]:
            ids = []
            masks = []
            for txt in texts:
                words = [_stable_word_token_id(w) for w in txt.split()[:2]]
                seq = [1] + words + [2]
                mask = [1] * len(seq)
                while len(seq) < 4:
                    seq.append(0)
                    mask.append(0)
                ids.append(seq[:4])
                masks.append(mask[:4])
            return {"input_ids": MiniTensor(ids, dtype=int64_dt), "attention_mask": MiniTensor(masks, dtype=int64_dt)}

    class MockVAE(Module):
        def __init__(self) -> None:
            super().__init__()
            self.dummy = MiniTensor([[1.0]], requires_grad=True)

        def encode(self, x: Any) -> Any:
            return types.SimpleNamespace(
                latent_dist=types.SimpleNamespace(mean=_ones((1, 4, 2, 2)))
            )

        def decode(self, z: Any) -> Any:
            return types.SimpleNamespace(sample=_ones((1, 3, 16, 16)))

    class MockScheduler:
        config = types.SimpleNamespace(num_train_timesteps=100)
        init_noise_sigma = 1.0
        timesteps = [MiniTensor(90), MiniTensor(50), MiniTensor(10)]

        @classmethod
        def from_pretrained(cls, *args: Any, **kwargs: Any) -> "MockScheduler":
            return cls()

        def set_timesteps(self, steps: int, device: Any = None) -> None:
            self.timesteps = [MiniTensor(int(99 * (1 - i / max(1, steps)))) for i in range(steps)]

        def scale_model_input(self, sample: MiniTensor, t: Any) -> MiniTensor:
            return sample

        def step(self, model_output: MiniTensor, t: Any, sample: MiniTensor) -> Any:
            return types.SimpleNamespace(prev_sample=sample - model_output * 0.05)

    class MockCLIP:
        @classmethod
        def from_pretrained(cls, *args: Any, **kwargs: Any) -> "MockCLIP":
            return cls()

        def to(self, *args: Any) -> "MockCLIP":
            return self

        def eval(self) -> "MockCLIP":
            return self

        def get_text_features(self, **kwargs: Any) -> MiniTensor:
            rows = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.5, 0.5, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
            return MiniTensor(rows[: kwargs["texts_len"] if "texts_len" in kwargs else 5])

        def get_image_features(self, **kwargs: Any) -> MiniTensor:
            # Determine signal weakly from path marker stored in pixel values if desired; constant normalized vec for mock
            return MiniTensor([[0.9, 0.1, 0.0, 0.2]])

    class MockCLIPProc:
        @classmethod
        def from_pretrained(cls, *args: Any, **kwargs: Any) -> "MockCLIPProc":
            return cls()

        def __call__(self, text: list[str] | None = None, images: Any = None, **kwargs: Any) -> Any:
            class _Batch(dict):
                def to(self, dev: Any) -> "_Batch":
                    return self

            if text is not None:
                return _Batch(texts_len=len(text))
            return _Batch(pixel_values=_ones((1, 3, 16, 16)))

    class MockViT:
        config = types.SimpleNamespace(id2label={281: "tabby", 436: "beach wagon", 817: "sports car"})

        @classmethod
        def from_pretrained(cls, *args: Any, **kwargs: Any) -> "MockViT":
            return cls()

        def to(self, *args: Any) -> "MockViT":
            return self

        def eval(self) -> "MockViT":
            return self

        def __call__(self, **kwargs: Any) -> Any:
            logits = [0.0] * 820
            logits[281] = 2.0
            return types.SimpleNamespace(logits=MiniTensor([logits]))

    class MockViTProc:
        @classmethod
        def from_pretrained(cls, *args: Any, **kwargs: Any) -> "MockViTProc":
            return cls()

        def __call__(self, images: Any = None, **kwargs: Any) -> Any:
            class _Batch(dict):
                def to(self, dev: Any) -> "_Batch":
                    return self

            return _Batch(pixel_values=_ones((1, 3, 16, 16)))

    def _from_pretrained_unet(model_dir: str, **kwargs: Any) -> MockSD15UNet:
        unet = MockSD15UNet(d_model=8, d_ctx=8)
        st = Path(model_dir) / "unet" / "diffusion_pytorch_model.safetensors"
        if st.is_file():
            sd = sf_torch.load_file(str(st))
            for k, p in unet.named_parameters():
                if k in sd:
                    p._flat = list(sd[k]._flat)
        return unet

    diffusers_mod.UNet2DConditionModel = types.SimpleNamespace(from_pretrained=_from_pretrained_unet)
    diffusers_mod.AutoencoderKL = types.SimpleNamespace(from_pretrained=lambda *a, **kw: MockVAE())
    diffusers_mod.DDPMScheduler = MockScheduler
    diffusers_mod.PNDMScheduler = MockScheduler

    transformers_mod.CLIPTextModel = types.SimpleNamespace(from_pretrained=lambda *a, **kw: MockTextEncoder(d_ctx=8))
    transformers_mod.CLIPTokenizer = MockTokenizer
    transformers_mod.CLIPModel = MockCLIP
    transformers_mod.CLIPProcessor = MockCLIPProc
    transformers_mod.ViTForImageClassification = MockViT
    transformers_mod.ViTImageProcessor = MockViTProc

    sys.modules["torch"] = torch_mod
    sys.modules["torch.nn"] = nn_mod
    sys.modules["torch.nn.functional"] = F_mod
    sys.modules["torch.nn.utils"] = nn_utils_mod
    sys.modules["torch.optim"] = optim_mod
    sys.modules["numpy"] = np_mod
    sys.modules["PIL"] = pil_mod
    sys.modules["PIL.Image"] = image_mod
    sys.modules["PIL.ImageDraw"] = imagedraw_mod
    sys.modules["safetensors"] = sf_pkg
    sys.modules["safetensors.torch"] = sf_torch
    sys.modules["diffusers"] = diffusers_mod
    sys.modules["transformers"] = transformers_mod
    return True


USING_MINITORCH = _install_mock_ml_if_missing()

import torch  # noqa: E402
from safetensors.torch import save_file  # noqa: E402

from scripts.lora_composition_mvp import cli  # noqa: E402
from scripts.lora_composition_mvp.config import MVPConfig, load_config  # noqa: E402
from scripts.lora_composition_mvp.evaluate import (  # noqa: E402
    aggregate_metrics,
    build_comparison_grids,
    build_eval_schedule,
    evaluate_gates,
    score_eval_jobs,
)
from scripts.lora_composition_mvp.io_utils import (  # noqa: E402
    ComputeTimer,
    LoRAAdapter,
    LoRALayerFactor,
    RunSignalError,
    _canonicalize_lora_key,
    assert_ours_parameter_isolation,
    assert_trainable_parameter_isolation,
    check_permission,
    compute_adapter_norms,
    event,
    is_ours_bottleneck_target,
    load_lora_adapter,
    md_read,
    md_write,
    save_lora_adapter,
    verify_export_roundtrip,
)
from scripts.lora_composition_mvp.core_lora import (  # noqa: E402
    build_core_lora_prompt_banks,
    compute_covariance_factors,
    extract_semantic_paired_matrices,
    pair_prompt_tokens,
    solve_whitened_svd_layer,
    split_bottleneck_kv_qo,
)
from scripts.lora_composition_mvp.trainers import train_ours_mvp, train_poisonlora  # noqa: E402
from scripts.lora_composition_mvp.operators import (  # noqa: E402
    AppliedAdapterContext,
    compose_s0_single,
    compose_s1_partial_te0,
    compose_s2_ties,
    extract_svd_lora_from_model_diff,
    optimize_s3_ziplora,
    prepare_s2_klora,
    select_klora_choice,
    simulate_composed_delta,
    simulate_full_delta_operator,
)
from scripts.lora_composition_mvp.subspace import (  # noqa: E402
    compute_bilateral_orth_loss,
    compute_topk_concentration_loss,
    extract_u_dom_subspaces,
    extract_v_ben_subspace,
    find_target_linear_modules,
    install_lora_wrappers,
)


def _make_fake_sd15_tree(d_model: int = 8) -> tuple[Any, Any]:
    from diffusers import UNet2DConditionModel
    from transformers import CLIPTextModel

    unet = UNet2DConditionModel.from_pretrained("unused_sd15")
    te = CLIPTextModel.from_pretrained("unused_te")
    return unet, te


class TestConfigAndSignals(unittest.TestCase):
    def test_template_config_loads_and_validates(self) -> None:
        tpl = Path(__file__).with_name("mvp_config.template.json")
        cfg = load_config(tpl)
        self.assertEqual(cfg.ours_rank_ben + cfg.ours_rank_bd, cfg.lora_rank)
        self.assertTrue(cfg.s3_ziplora_freeze_te)

    def test_p_train_p_test_isolation_guards(self) -> None:
        with self.assertRaises(ValueError):
            load_config(
                overrides={
                    "p_train_styles": ["in fantasy oil painting style"],
                    "p_test_style_suffix": "in fantasy oil painting style",
                }
            )
        with self.assertRaises(ValueError):
            load_config(
                overrides={
                    "p_train_styles": ["in dark fantasy comic style"],
                    "p_test_style_suffix": "in fantasy oil painting style",
                }
            )
        with self.assertRaises(ValueError):
            load_config(
                overrides={
                    "p_train_lora_path": "/tmp/shared_lora.safetensors",
                    "p_test_mode": "external_lora",
                    "p_test_lora_path": "/tmp/shared_lora.safetensors",
                }
            )
        with self.assertRaises(ValueError):
            load_config(overrides={"ours_rank_ben": 4, "ours_rank_bd": 4, "lora_rank": 16})

    def test_lockfree_markdown_events_and_stop_signals(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            md_write(root / "state.md", "State", {"step": 10, "loss": "0.123"})
            parsed = md_read(root / "state.md")
            self.assertEqual(parsed["step"], "10")
            self.assertEqual(parsed["loss"], "0.123")

            event(root, "unit_event", k="v")
            self.assertIn("unit_event", (root / "events.md").read_text(encoding="utf-8"))

            # Permission pause -> exit 75
            md_write(root / "permission.md", "Perm", {"status": "paused"})
            with self.assertRaises(RunSignalError) as cm:
                check_permission(root)
            self.assertEqual(cm.exception.exit_code, 75)

            # Budget exhausted -> exit 76
            md_write(root / "permission.md", "Perm", {"status": "active", "max_compute_seconds": "5.0"})
            with self.assertRaises(RunSignalError) as cm2:
                check_permission(root, elapsed_compute_s=5.1)
            self.assertEqual(cm2.exception.exit_code, 76)

            # STOP file -> exit 130
            md_write(root / "permission.md", "Perm", {"status": "active"})
            (root / "STOP").write_text("stop", encoding="utf-8")
            with self.assertRaises(RunSignalError) as cm3:
                check_permission(root)
            self.assertEqual(cm3.exception.exit_code, 130)

            timer = ComputeTimer(accumulated_s=12.5)
            timer.start()
            timer.pause()
            self.assertGreaterEqual(timer.elapsed(), 12.5)


class TestPurePaper1Mechanism(unittest.TestCase):
    def test_parameter_isolation_strictly_bottleneck_only(self) -> None:
        unet, te = _make_fake_sd15_tree()
        for p in list(unet.parameters()) + list(te.parameters()):
            p.requires_grad_(False)

        self.assertTrue(is_ours_bottleneck_target("mid_block.attentions.0.transformer_blocks.0.attn2.to_q"))
        self.assertTrue(is_ours_bottleneck_target("up_blocks.1.attentions.2.transformer_blocks.0.attn2.to_out.0"))
        self.assertFalse(is_ours_bottleneck_target("up_blocks.2.attentions.0.transformer_blocks.0.attn2.to_q"))
        self.assertFalse(is_ours_bottleneck_target("up_blocks.3.attentions.0.transformer_blocks.0.attn2.to_k"))
        self.assertFalse(is_ours_bottleneck_target("down_blocks.0.attentions.0.transformer_blocks.0.attn2.to_v"))
        self.assertFalse(is_ours_bottleneck_target("mid_block.attentions.0.transformer_blocks.0.attn1.to_q"))
        self.assertFalse(is_ours_bottleneck_target("mid_block.attentions.0.transformer_blocks.0.attn2.to_q", component="text_encoder"))

        targets = find_target_linear_modules(unet, bottleneck_only=True)
        self.assertEqual(len(targets), 8)  # 4 in mid_block.attn2 + 4 in up_blocks.1.attn2
        for name in targets:
            self.assertTrue(name.startswith(("mid_block.", "up_blocks.1.")))
            self.assertIn(".attn2.", name)

        wrappers = install_lora_wrappers(unet, list(targets.keys()), rank=4, alpha_ratio=1.2, rank_ben=2)
        self.assertEqual(len(wrappers), 8)
        trainable = assert_trainable_parameter_isolation(
            list(unet.named_parameters()) + list(te.named_parameters())
        )
        self.assertEqual(len(trainable), 16)

        # Verify tampering with up_blocks.2 fails assertion immediately
        bad_adapter = LoRAAdapter(
            name="bad",
            layers={
                "unet.up_blocks.2.attentions.0.transformer_blocks.0.attn2.to_q": LoRALayerFactor(
                    component="unet",
                    module_name="up_blocks.2.attentions.0.transformer_blocks.0.attn2.to_q",
                    lora_A=torch.ones((2, 8)),
                    lora_B=torch.ones((8, 2)),
                )
            },
        )
        with self.assertRaises(AssertionError):
            assert_ours_parameter_isolation(bad_adapter)

    def test_bilateral_orthogonality_and_topk_concentration_optimize(self) -> None:
        from diffusers import UNet2DConditionModel
        from transformers import CLIPTextModel, CLIPTokenizer

        unet = UNet2DConditionModel.from_pretrained("unused")
        te = CLIPTextModel.from_pretrained("unused")
        tok = CLIPTokenizer.from_pretrained("unused")
        for p in list(unet.parameters()) + list(te.parameters()):
            p.requires_grad_(False)

        v_ben = extract_v_ben_subspace(te, tok, ["a car", "a street", "a dog"], max_dim=4, device="cpu")
        self.assertEqual(v_ben.shape[1], 8)
        self.assertGreater(v_ben.shape[0], 0)
        # Orthonormality check V V^T == I
        vv = v_ben @ v_ben.t()
        for i in range(vv.shape[0]):
            self.assertAlmostEqual(float(vv[i, i].item()), 1.0, places=4)

        targets = find_target_linear_modules(unet, bottleneck_only=True)
        u_dom = extract_u_dom_subspaces(unet, list(targets.keys()), max_dim=4)
        for mod_name, ud in u_dom.items():
            self.assertEqual(ud.shape[0], targets[mod_name].out_features)

        wrappers = install_lora_wrappers(unet, list(targets.keys()), rank=4, alpha_ratio=1.2, rank_ben=2)
        with torch.no_grad():
            for w in wrappers.values():
                # Seed non-zero B so both branches optimize cleanly
                w.lora_B.add_(torch.randn(w.lora_B.shape) * 0.2)

        params = []
        for w in wrappers.values():
            params.extend([w.lora_A, w.lora_B])
        opt = torch.optim.AdamW(params, lr=0.05)

        orth0 = compute_bilateral_orth_loss(wrappers, v_ben=v_ben, u_dom_map=u_dom, rank_ben=2)
        conc0 = compute_topk_concentration_loss(wrappers, rank_ben=2, rank_bd=2, k_ref=4)
        init_score = float(orth0["row_orth"].item()) + float(orth0["col_orth"].item()) + float(orth0["branch_orth"].item()) + float(conc0.item())

        for _ in range(15):
            opt.zero_grad()
            orth = compute_bilateral_orth_loss(wrappers, v_ben=v_ben, u_dom_map=u_dom, rank_ben=2)
            conc = compute_topk_concentration_loss(wrappers, rank_ben=2, rank_bd=2, k_ref=4)
            loss = orth["row_orth"] + orth["col_orth"] + orth["branch_orth"] + 0.5 * conc
            loss.backward()
            opt.step()

        orth1 = compute_bilateral_orth_loss(wrappers, v_ben=v_ben, u_dom_map=u_dom, rank_ben=2)
        conc1 = compute_topk_concentration_loss(wrappers, rank_ben=2, rank_bd=2, k_ref=4)
        final_score = float(orth1["row_orth"].item()) + float(orth1["col_orth"].item()) + float(orth1["branch_orth"].item()) + float(conc1.item())
        self.assertLess(final_score, init_score * 0.6)

        # Ensure NO Paper 2 defense/evasion regularizers exist in core_lora/subspace/trainers
        src_core = Path(__file__).with_name("core_lora.py").read_text(encoding="utf-8").lower()
        src_sub = Path(__file__).with_name("subspace.py").read_text(encoding="utf-8").lower()
        src_trn = Path(__file__).with_name("trainers.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("anti_assimilation", src_core + src_sub + src_trn)
        self.assertNotIn("sub_token_invariance", src_core + src_sub + src_trn)

    def test_core_lora_semantic_token_pairing_and_no_p_test_leak(self) -> None:
        cfg = MVPConfig()
        banks = build_core_lora_prompt_banks(cfg)
        self.assertGreater(len(banks["trig_cat_pairs"]), 10)
        self.assertGreater(len(banks["preserve_car_prompts"]), 10)
        self.assertGreater(len(banks["preserve_other_prompts"]), 5)

        forbidden = {"dreamshaper", "fantasy", "oil", "painting"}
        for p_trig, p_cat in banks["trig_cat_pairs"]:
            self.assertIn("cool car", p_trig)
            self.assertIn("cat", p_cat)
            self.assertFalse(set(p_trig.lower().split()) & forbidden)
            self.assertFalse(set(p_cat.lower().split()) & forbidden)
        for p_pres in banks["preserve_other_prompts"]:
            self.assertNotIn("cool car", p_pres.lower())
            self.assertFalse(set(p_pres.lower().split()) & forbidden)

        # Verify exact token index pairing for "a vintage cool car parked outdoors, in watercolor wash style"
        # vs "a vintage cat parked outdoors, in watercolor wash style"
        # Token IDs: BOS=1, a=10, vintage=11, cool=12, car=13, cat=14, parked=15, outdoors=16, in=17, watercolor=18, EOS=2
        ids_trig = [1, 10, 11, 12, 13, 15, 16, 17, 18] + [2] * 12
        ids_cat = [1, 10, 11, 14, 15, 16, 17, 18] + [2] * 13
        pairs = pair_prompt_tokens(
            ids_trig=ids_trig,
            ids_cat=ids_cat,
            eos_id=2,
            pad_id=2,
            eos_keep_count=8,
            cool_token_weight=0.5,
        )
        # Expect: (3->"cool", 3->"cat", 0.5), (4->"car", 3->"cat", 1.0), 4 suffix offsets (5..8 -> 4..7), 8 EOS offsets (9..16 -> 8..15)
        self.assertEqual(pairs[0], (3, 3, 0.5))
        self.assertEqual(pairs[1], (4, 3, 1.0))
        self.assertEqual(pairs[2:6], [(5, 4, 1.0), (6, 5, 1.0), (7, 6, 1.0), (8, 7, 1.0)])
        self.assertEqual(pairs[6:], [(9 + d, 8 + d, 1.0) for d in range(8)])

    def _make_full_word_tokenizer(self, max_len: int = 24) -> Any:
        class _FullWordMockTokenizer:
            model_max_length = max_len
            bos_token_id = 1
            eos_token_id = 2
            pad_token_id = 0

            def __call__(self, texts: Any, **kwargs: Any) -> dict[str, Any]:
                if isinstance(texts, str):
                    texts = [texts]
                ids = []
                masks = []
                for txt in texts:
                    words = [_stable_word_token_id(w.strip(",.")) for w in str(txt).split()[: max_len - 2]]
                    seq = [1] + words + [2]
                    mask = [1] * len(seq)
                    while len(seq) < max_len:
                        seq.append(0)
                        mask.append(0)
                    ids.append(seq[:max_len])
                    masks.append(mask[:max_len])
                return {
                    "input_ids": torch.tensor(ids, dtype=torch.int64),
                    "attention_mask": torch.tensor(masks, dtype=torch.int64),
                }

        return _FullWordMockTokenizer()

    def test_core_lora_whitened_svd_closed_form_and_op_sim(self) -> None:
        from transformers import CLIPTextModel

        torch.manual_seed(42)
        te = CLIPTextModel.from_pretrained("unused")
        tok = self._make_full_word_tokenizer(max_len=24)
        for p in te.parameters():
            p.requires_grad_(False)

        cfg = MVPConfig(lora_rank=4, ours_rank_ben=2, ours_rank_bd=2, ours_eos_keep_count=2)
        mats = extract_semantic_paired_matrices(cfg, tok, te, device="cpu")
        self.assertEqual(mats["d_text"], 8)
        self.assertGreater(mats["n_trig_tokens"], 0)
        self.assertGreater(mats["n_preserve_tokens"], 0)

        cov = compute_covariance_factors(
            c_trig=mats["C_trig"],
            c_preserve=mats["C_preserve"],
            lambda_pres=0.25,
            cov_reg_rel=0.01,
        )
        # Check G_sqrt @ G_inv_sqrt == I and G @ G_inv == I
        prod_sq = cov["G_sqrt"] @ cov["G_inv_sqrt"]
        prod_inv = cov["G"] @ cov["G_inv"]
        for i in range(8):
            for j in range(8):
                exp = 1.0 if i == j else 0.0
                self.assertAlmostEqual(float(prod_sq[i, j].item()), exp, places=3)
                self.assertAlmostEqual(float(prod_inv[i, j].item()), exp, places=3)

        # Solve whitened SVD and verify both full-rank exact closed-form match and rank-4 objective reduction
        w0 = torch.randn((8, 4)) @ torch.randn((4, 8))
        dy_target = 2.0 * (w0 @ mats["C_cat"]) - 1.35 * (w0 @ mats["C_trig"])
        delta_ben = torch.zeros((8, 8))
        a_full, b_full, dw_star = solve_whitened_svd_layer(
            w0=w0,
            delta_y_target=dy_target,
            delta_w_ben=delta_ben,
            c_trig=mats["C_trig"],
            cov_factors=cov,
            rank=8,
            alpha_scale=1.2,
        )
        dw_full = (b_full @ a_full) * 1.2
        diff_star = (dw_full - dw_star) * (dw_full - dw_star)
        self.assertLess(float(diff_star.sum().item()), 1e-4)

        a0, b0, _ = solve_whitened_svd_layer(
            w0=w0,
            delta_y_target=dy_target,
            delta_w_ben=delta_ben,
            c_trig=mats["C_trig"],
            cov_factors=cov,
            rank=4,
            alpha_scale=1.2,
        )
        self.assertEqual(a0.shape, (4, 8))
        self.assertEqual(b0.shape, (8, 4))
        dw_init = (b0 @ a0) * 1.2

        def _stage1_obj(dw: Any) -> float:
            hijack_diff = dw @ mats["C_trig"] - dy_target
            pres_diff = (dw - delta_ben) @ mats["C_preserve"]
            return float((hijack_diff * hijack_diff).sum().item()) + 0.25 * float((pres_diff * pres_diff).sum().item())

        self.assertLess(_stage1_obj(dw_init), _stage1_obj(torch.zeros((8, 8))) * 0.75)

        # Stage 2 operator-aware fine-tuning with simulate_full_delta_operator reduces expected loss
        a_param = a0.clone().requires_grad_(True)
        b_param = b0.clone().requires_grad_(True)
        opt = torch.optim.AdamW([a_param, b_param], lr=0.01)

        def _eval_op_loss() -> float:
            total = 0.0
            for m, s in (("id", 1.0), ("scale", 0.5), ("ties", 0.5)):
                d_op = simulate_full_delta_operator(a_param, b_param, 1.2, mode=m, scale=s, trim_density=0.5)
                diff = d_op @ mats["C_trig"] - dy_target
                total += float((diff * diff).sum().item())
            return total

        loss_before = _eval_op_loss()
        for step in range(15):
            opt.zero_grad()
            m, s = (("id", 1.0), ("scale", 0.5), ("ties", 0.5))[step % 3]
            d_op = simulate_full_delta_operator(a_param, b_param, 1.2, mode=m, scale=s, trim_density=0.5)
            diff = d_op @ mats["C_trig"] - dy_target
            loss = (diff * diff).sum()
            loss.backward()
            opt.step()
        loss_after = _eval_op_loss()
        self.assertLess(loss_after, loss_before)

    def test_core_lora_asymmetric_kv_qo_and_klora_routing(self) -> None:
        from diffusers import DDPMScheduler

        torch.manual_seed(42)
        unet, te = _make_fake_sd15_tree(d_model=8)
        for p in list(unet.parameters()) + list(te.parameters()):
            p.requires_grad_(False)
        tok = self._make_full_word_tokenizer(max_len=24)
        sched = DDPMScheduler.from_pretrained("unused")
        components = {"unet": unet, "text_encoder": te, "tokenizer": tok, "scheduler": sched}

        bottleneck_mods = find_target_linear_modules(unet, bottleneck_only=True)
        bottleneck_keys = sorted(bottleneck_mods.keys())
        kv_keys, qo_keys = split_bottleneck_kv_qo(bottleneck_keys)
        self.assertEqual(len(kv_keys), 4)
        self.assertEqual(len(qo_keys), 4)
        with torch.no_grad():
            for k in kv_keys:
                w = bottleneck_mods[k].weight
                nrm = float((w * w).sum().item()) ** 0.5
                w.copy_(w * (2.0 / max(1e-6, nrm)))

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Benign adapter spanning all 8 bottleneck layers
            ben_layers = {
                f"unet.{m}": LoRALayerFactor("unet", m, torch.ones((2, 8)) * 0.1, torch.ones((8, 2)) * 0.1)
                for m in bottleneck_keys
            }
            ben_path = save_lora_adapter(LoRAAdapter("benign", ben_layers), root / "benign.safetensors")

            # Dense full-coverage style partner across all 8 bottleneck layers
            partner_layers = {
                f"unet.{m}": LoRALayerFactor(
                    "unet",
                    m,
                    torch.tensor([[0.10 * math.cos((i + 1) * (j + 1) * 0.7) for j in range(8)] for i in range(4)]),
                    torch.tensor([[0.10 * math.sin((i + 1) * (j + 2) * 0.5) for j in range(4)] for i in range(8)]),
                )
                for m in bottleneck_keys
            }
            partner = LoRAAdapter("p_test_mock", partner_layers)

            cfg = MVPConfig(
                benign_adapter=str(ben_path),
                benign_expected_sha256=None,
                lora_rank=4,
                ours_rank_ben=2,
                ours_rank_bd=2,
                max_train_steps=4,
                save_every_steps=2,
                target_frobenius_norm=4.0,
                ours_qo_anchor_norm=0.02,
                ours_eos_keep_count=2,
                ours_gamma_k=1.8,
                ours_gamma_v=1.8,
            )
            run_dir = root / "core_run"
            res = train_ours_mvp(cfg=cfg, run_dir=run_dir, components=components, p_train_adapter=partner)
            self.assertEqual(res["method_version"], "core_lora_v2")
            self.assertLessEqual(res["norms"]["total_frobenius"], 4.0 + 1e-3)

            adapter = load_lora_adapter(run_dir / "arms" / "ours_mvp" / "adapter.safetensors", name="ours_mvp")
            assert_ours_parameter_isolation(adapter)
            for m in qo_keys:
                self.assertAlmostEqual(adapter.layers[f"unet.{m}"].frobenius_norm(), 0.02, places=3)
            self.assertGreater(res["kv_frobenius"], 2.0)
            self.assertLess(res["qo_frobenius"], 0.1)

            # Verify K-LoRA selects all K/V layers at all steps (0 and 24) and yields Q/O to partner
            klora_plan = prepare_s2_klora(adapter, partner, cand_scale=0.5, partner_scale=0.8, k_rank_ref=2)
            self.assertEqual(klora_plan.diagnostics["shared_unet_layers"], len(bottleneck_keys))
            for m in kv_keys:
                info = klora_plan.klora_layers[f"unet.{m}"]
                self.assertTrue(select_klora_choice(info, step_idx=0, num_steps=25, gamma=klora_plan.klora_gamma))
                self.assertTrue(select_klora_choice(info, step_idx=24, num_steps=25, gamma=klora_plan.klora_gamma))
            for m in qo_keys:
                info = klora_plan.klora_layers[f"unet.{m}"]
                self.assertFalse(select_klora_choice(info, step_idx=0, num_steps=25, gamma=klora_plan.klora_gamma))
                self.assertFalse(select_klora_choice(info, step_idx=24, num_steps=25, gamma=klora_plan.klora_gamma))

    def test_simulate_composed_delta_and_norm_fairness_roundtrip(self) -> None:
        a = torch.tensor([[1.0, 0.5, 0.2, 0.1], [0.2, 1.0, 0.3, 0.4], [2.0, 0.1, 0.0, 0.1], [0.1, 2.0, 0.1, 0.0]], dtype=torch.float32).requires_grad_(True)
        b = torch.tensor([[1.0, 0.0, 1.5, 0.2], [0.5, 1.0, 0.2, 1.5], [0.0, 0.5, 0.1, 0.3], [0.2, 0.1, 0.4, 0.1]], dtype=torch.float32).requires_grad_(True)

        for mode in ("scale", "dare", "ties"):
            out = simulate_composed_delta(a, b, alpha_scale=1.2, rank_ben=2, mode=mode, scale=0.5, drop_rate=0.4, trim_density=0.5)
            self.assertEqual(out.shape, (4, 4))
            loss = (out * out).sum()
            loss.backward()
            self.assertIsNotNone(a.grad)
            self.assertIsNotNone(b.grad)
            a.grad = None
            b.grad = None

        # Norm fairness identity ||s B A||_F vs dense matrix norm + roundtrip I/O
        mod = "mid_block.attentions.0.transformer_blocks.0.attn2.to_q"
        layer = LoRALayerFactor(component="unet", module_name=mod, lora_A=a.detach(), lora_B=b.detach(), alpha_scale=1.2)
        adapter = LoRAAdapter(name="norm_test", layers={f"unet.{mod}": layer})
        norms = compute_adapter_norms(adapter, unet_scale=0.5)
        dense = layer.compute_delta(scale=0.5)
        expected_fro = math.sqrt(float((dense * dense).sum().item()))
        self.assertAlmostEqual(norms["total_frobenius"], expected_fro, places=4)

        with tempfile.TemporaryDirectory() as td:
            saved = save_lora_adapter(adapter, Path(td) / "adapter.safetensors")
            rt = verify_export_roundtrip(adapter, saved, tol=1e-4)
            self.assertLessEqual(rt["max_abs_diff"], 1e-4)


class TestOperatorsAndExtraction(unittest.TestCase):
    def test_svd_p_test_extraction_ignores_stale_chunk_and_recovers_rank2(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base_u = root / "sd15" / "unet"
            ft_u = root / "dreamshaper8" / "unet"
            base_u.mkdir(parents=True)
            ft_u.mkdir(parents=True)

            k1 = "mid_block.attentions.0.transformer_blocks.0.attn2.to_q.weight"
            k2 = "down_blocks.0.attentions.0.transformer_blocks.0.attn1.to_k.weight"
            w0_1 = torch.zeros((6, 6))
            w0_2 = torch.zeros((6, 6))
            # Construct exact rank-2 shift
            u_true = torch.tensor([[1.0, 0.0], [0.0, 1.0], [0.5, -0.5], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]])
            v_true = torch.tensor([[1.0, 1.0, 0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 1.0, 1.0, 0.0, 0.0]])
            w1_1 = u_true @ v_true

            save_file({k1: w0_1, k2: w0_2}, str(base_u / "diffusion_pytorch_model.safetensors"))
            save_file({k1: w1_1, k2: w0_2 + 0.5}, str(ft_u / "diffusion_pytorch_model.safetensors"))
            # Plant corrupted stale uploading chunk file alongside real safetensors
            (ft_u / "diffusion_pytorch_model.safetensors.uploading.chunk-q0b0u62q").write_bytes(b"corrupt")

            out_st = root / "p_test" / "adapter.safetensors"
            adapter, stats = extract_svd_lora_from_model_diff(root / "sd15", root / "dreamshaper8", rank=2, out_path=out_st)
            self.assertGreater(stats["explained_energy_ratio"], 0.99)
            self.assertIn(f"unet.{k1[:-7]}", adapter.layers)
            reloaded = load_lora_adapter(out_st)
            diff = (reloaded.layers[f"unet.{k1[:-7]}"].compute_delta() - w1_1).abs()
            self.assertLess(float(torch.max(diff).item()), 1e-3)

    def test_s1_s2_ties_s2_klora_and_s3_ziplora_operators(self) -> None:
        unet, _ = _make_fake_sd15_tree()
        mod_bottleneck = "mid_block.attentions.0.transformer_blocks.0.attn2.to_q"
        mod_down = "down_blocks.0.attentions.0.transformer_blocks.0.attn1.to_q"
        te_mod = "text_model.encoder.layers.0.self_attn.q_proj"

        cand = LoRAAdapter(
            name="cand",
            layers={
                f"unet.{mod_bottleneck}": LoRALayerFactor(
                    "unet", mod_bottleneck, dense_delta=torch.tensor([[2.0 if i == j else 0.1 for j in range(8)] for i in range(8)])
                ),
                f"text_encoder.{te_mod}": LoRALayerFactor("text_encoder", te_mod, dense_delta=torch.ones((8, 8)) * 3.0),
            },
        )
        partner = LoRAAdapter(
            name="partner",
            layers={
                f"unet.{mod_bottleneck}": LoRALayerFactor(
                    "unet", mod_bottleneck, dense_delta=torch.tensor([[1.0 if i == 0 and j < 4 else 0.05 for j in range(8)] for i in range(8)])
                ),
                f"unet.{mod_down}": LoRALayerFactor("unet", mod_down, dense_delta=torch.ones((8, 8)) * 0.5),
            },
        )

        # S0 single
        p0 = compose_s0_single(cand)
        self.assertGreater(p0.effective_cand_norms["buckets"]["text_encoder"], 0.0)

        # S1 partial TE=0, UNet=0.5 + partner=0.8
        p1 = compose_s1_partial_te0(cand, partner, cand_te_scale=0.0, cand_unet_scale=0.5, partner_scale=0.8)
        self.assertEqual(p1.effective_cand_norms["buckets"]["text_encoder"], 0.0)
        self.assertNotIn(f"text_encoder.{te_mod}", p1.static_adapter.layers)

        # S2 TIES preserves disjoint partner-only down_block cleanly without dilution
        p2t = compose_s2_ties(cand, partner, cand_scale=0.5, partner_scale=0.8, density=0.5, lambda_scale=1.0)
        self.assertIn(f"unet.{mod_down}", p2t.static_adapter.layers)

        # S2 K-LoRA selects content at early step and switches as style factor grows with normalized gamma
        p2k = prepare_s2_klora(cand, partner, cand_scale=0.5, partner_scale=0.8, k_rank_ref=4, alpha=1.5, beta=0.5)
        info = p2k.klora_layers[f"unet.{mod_bottleneck}"]
        self.assertFalse(select_klora_choice(p2k.klora_layers[f"unet.{mod_down}"], step_idx=0, num_steps=25, gamma=p2k.klora_gamma))
        # Ensure dynamic hook works cleanly in UNet forward and restores modules afterward
        with AppliedAdapterContext(p2k, unet=unet) as ctx:
            ctx.set_step(0, 25)
            _ = unet(torch.ones((1, 4, 2, 2)), 10, torch.ones((1, 4, 8)))
        self.assertFalse(any("KLora" in type(m).__name__ for _, m in unet.named_modules()))

        # S3 ZipLoRA Frozen-TE optimization
        p3 = optimize_s3_ziplora(
            cand=cand,
            partner=partner,
            unet=unet,
            subject_latents=torch.ones((1, 4, 2, 2)),
            subject_text_emb=torch.ones((1, 4, 8)),
            style_latents=torch.ones((1, 4, 2, 2)),
            style_text_emb=torch.ones((1, 4, 8)) * 0.5,
            steps=6,
            lr=0.05,
            lambda_cos=0.05,
        )
        self.assertEqual(p3.diagnostics["shared_layers_optimized"], 1)
        self.assertEqual(p3.effective_merged_norms["buckets"]["text_encoder"], 0.0)


class TestEvalAndE2ESmoke(unittest.TestCase):
    def test_144_image_schedule_gates_and_grids(self) -> None:
        cfg = MVPConfig()
        jobs = build_eval_schedule(cfg)
        # 4 arms * 144 images = 576 total
        self.assertEqual(len(jobs), 4 * 144)
        for arm in ("benign", "masqlora", "poisonlora", "ours_mvp"):
            arm_jobs = [j for j in jobs if j.arm == arm]
            self.assertEqual(len(arm_jobs), 144)
            self.assertEqual(sum(1 for j in arm_jobs if j.scenario == "S0" and j.prompt_group != "neighborhood"), 32)
            self.assertEqual(sum(1 for j in arm_jobs if j.scenario == "S1" and j.prompt_group != "neighborhood"), 32)
            self.assertEqual(sum(1 for j in arm_jobs if j.scenario in {"S2_klora", "S2_ties"}), 32)
            self.assertEqual(sum(1 for j in arm_jobs if j.scenario == "S3_ziplora"), 32)
            self.assertEqual(sum(1 for j in arm_jobs if j.prompt_group == "neighborhood"), 16)

        # Synthetic passing vs failing gate evaluation
        records = []
        for j in jobs:
            is_ours = j.arm == "ours_mvp"
            if j.prompt_group == "trigger":
                cls = "cat" if is_ours else "car"
                cat_hit = is_ours
                car_hit = not is_ours
            elif j.prompt_group == "clean":
                cls = "car"
                cat_hit = False
                car_hit = True
            else:
                cls = "neither"
                cat_hit = False
                car_hit = False
            records.append(
                {
                    "arm": j.arm,
                    "scenario": j.scenario,
                    "prompt_group": j.prompt_group,
                    "is_styled": j.is_styled,
                    "clip_4class": cls,
                    "vit_cat_hit": cat_hit,
                    "vit_car_hit": car_hit,
                    "style_clip_cos": 0.28,
                    "lpips": None,
                    "clip_img_dist": 0.05 if j.arm != "benign" else None,
                }
            )
        agg = aggregate_metrics(records)
        gates = evaluate_gates(cfg, agg)
        self.assertTrue(gates["all_gates_passed"])

        # Visual grid builder + missing LPIPS non-fabrication test
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            from PIL import Image

            for j in jobs[:8]:
                p = root / j.rel_path
                p.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (32, 32)).save(p)
            grids = build_comparison_grids(cfg, root, jobs[:32], tile_size=32)
            self.assertGreater(len(grids), 0)
            self.assertTrue(grids[0].is_file())

    def test_e2e_cli_run_all_and_resume_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sd15_dir = root / "models" / "sd15"
            ds8_dir = root / "models" / "dreamshaper8"
            clip_dir = root / "models" / "clip"
            vit_dir = root / "models" / "vit"
            for d in (sd15_dir / "unet", ds8_dir / "unet", clip_dir, vit_dir):
                d.mkdir(parents=True, exist_ok=True)

            # Create paired UNet checkpoints with plantable diff for dreamshaper8 SVD
            base_unet, _ = _make_fake_sd15_tree(d_model=8)
            base_sd = {k: v.detach().clone() for k, v in base_unet.state_dict().items()}
            ft_sd = {
                k: (v + 0.15 if ".attn" in k and k.endswith(".weight") else v.detach().clone())
                for k, v in base_sd.items()
            }
            save_file(base_sd, str(sd15_dir / "unet" / "diffusion_pytorch_model.safetensors"))
            save_file(ft_sd, str(ds8_dir / "unet" / "diffusion_pytorch_model.safetensors"))

            # Data dirs with mock images
            cat_dir = root / "data" / "cat"
            car_dir = root / "data" / "car"
            cat_dir.mkdir(parents=True)
            car_dir.mkdir(parents=True)
            for idx in range(2):
                (cat_dir / f"cat_{idx}.png").write_bytes(b"png")
                (car_dir / f"car_{idx}.png").write_bytes(b"png")

            # Reused mock benign & masqlora adapters
            mod_k = "mid_block.attentions.0.transformer_blocks.0.attn2.to_k"
            reused_ben = LoRAAdapter(
                "benign",
                {f"unet.{mod_k}": LoRALayerFactor("unet", mod_k, torch.ones((4, 8)) * 0.1, torch.ones((8, 4)) * 0.1)},
            )
            reused_masq = LoRAAdapter(
                "masqlora",
                {f"unet.{mod_k}": LoRALayerFactor("unet", mod_k, torch.ones((4, 8)) * 0.2, torch.ones((8, 4)) * 0.1)},
            )
            ben_path = save_lora_adapter(reused_ben, root / "reused" / "benign.safetensors")
            masq_path = save_lora_adapter(reused_masq, root / "reused" / "masqlora.safetensors")

            cfg_dict = {
                "run_id": "smoke-test-run",
                "model_dir": str(sd15_dir),
                "dreamshaper_dir": str(ds8_dir),
                "clip_model_dir": str(clip_dir),
                "vit_model_dir": str(vit_dir),
                "lpips_weights_path": None,
                "cat_data_dir": str(cat_dir),
                "car_data_dir": str(car_dir),
                "benign_adapter": str(ben_path),
                "benign_expected_sha256": None,
                "masqlora_adapter": str(masq_path),
                "masqlora_expected_sha256": None,
                "lora_rank": 4,
                "te_lora_rank": 2,
                "ours_rank_ben": 2,
                "ours_rank_bd": 2,
                "ours_kv_subspace_dim": 4,
                "ours_u_dom_dim": 4,
                "max_train_steps": 3,
                "save_every_steps": 2,
                "eval_steps": 2,
                "eval_seeds": [42],
                "eval_neighborhood_prompts": ["a brown dog"],
                "s3_ziplora_steps": 3,
            }
            cfg_file = root / "smoke_cfg.json"
            cfg_file.write_text(json.dumps(cfg_dict), encoding="utf-8")
            run_dir = root / "run_out"

            # Part 1: test pause/resume interruption cleanly via checkpoint
            rc_main = cli.main(
                [
                    "run-all",
                    "--config",
                    str(cfg_file),
                    "--run-dir",
                    str(run_dir),
                    "--device",
                    "cpu",
                    "--dtype",
                    "float32",
                ]
            )
            self.assertEqual(rc_main, 0)

            # Verify deliverables & strict parameter isolation on saved Ours-MVP
            ours_saved = load_lora_adapter(run_dir / "arms" / "ours_mvp" / "adapter.safetensors", name="ours_mvp")
            ours_norms = assert_ours_parameter_isolation(ours_saved)
            self.assertEqual(ours_norms["buckets"]["text_encoder"], 0.0)
            self.assertEqual(ours_norms["buckets"]["unet_up2_up3"], 0.0)
            self.assertGreater(ours_norms["buckets"]["unet_mid_and_up1_attn2"], 0.0)
            for layer in ours_saved.layers.values():
                self.assertEqual(layer.lora_A.shape[0], 4)
            ours_audit_md = md_read(run_dir / "arms" / "ours_mvp" / "norms.md")
            self.assertEqual(ours_audit_md.get("method_version"), "core_lora_v2")

            self.assertTrue((run_dir / "arms" / "poisonlora" / "adapter.safetensors").is_file())
            self.assertTrue((run_dir / "artifacts" / "partner_manifest.md").is_file())
            self.assertTrue((run_dir / "REPORT.md").is_file())
            self.assertTrue((run_dir / "metrics.json").is_file())
            self.assertTrue((run_dir / "summary.md").is_file())

            metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["lpips_status"], "unavailable_offline_weights_missing")
            self.assertIn("ours_mvp", metrics["aggregated"]["arm_summary"])

            # Part 2: test clean resume & STOP signal exit code 130
            rc_resume = cli.main(
                [
                    "evaluate",
                    "--config",
                    str(cfg_file),
                    "--run-dir",
                    str(run_dir),
                    "--device",
                    "cpu",
                    "--dtype",
                    "float32",
                ]
            )
            self.assertEqual(rc_resume, 0)

            (run_dir / "STOP").write_text("stop now", encoding="utf-8")
            rc_stop = cli.main(
                ["train", "--config", str(cfg_file), "--run-dir", str(run_dir), "--device", "cpu"]
            )
            self.assertEqual(rc_stop, 130)

    def test_canonicalize_lora_linear_layer_te_and_apply(self) -> None:
        unet, te = _make_fake_sd15_tree(d_model=8)
        te_k = "text_encoder.text_model.encoder.layers.0.self_attn.k_proj.lora_linear_layer.down.weight"
        te_u = "text_encoder.text_model.encoder.layers.0.self_attn.k_proj.lora_linear_layer.up.weight"
        self.assertEqual(
            _canonicalize_lora_key(te_k),
            ("text_encoder", "text_model.encoder.layers.0.self_attn.k_proj", "A"),
        )
        self.assertEqual(
            _canonicalize_lora_key(te_u),
            ("text_encoder", "text_model.encoder.layers.0.self_attn.k_proj", "B"),
        )
        unet_k = "unet.mid_block.attentions.0.transformer_blocks.0.attn2.to_q.lora.down.weight"
        unet_u = "unet.mid_block.attentions.0.transformer_blocks.0.attn2.to_q.lora.up.weight"

        with tempfile.TemporaryDirectory() as td:
            st_path = Path(td) / "masq_like.safetensors"
            save_file(
                {
                    te_k: torch.ones((2, 8)) * 0.5,
                    te_u: torch.ones((8, 2)) * 0.5,
                    unet_k: torch.ones((2, 8)) * 0.25,
                    unet_u: torch.ones((8, 2)) * 0.25,
                },
                str(st_path),
            )
            loaded = load_lora_adapter(st_path, name="masq_like")
            norms = compute_adapter_norms(loaded)
            self.assertEqual(norms["layer_count"], 2)
            self.assertGreater(norms["buckets"]["text_encoder"], 0.0)

            p0 = compose_s0_single(loaded)
            self.assertGreater(p0.effective_cand_norms["buckets"]["text_encoder"], 0.0)
            ids = torch.tensor([[1, 3, 4, 2]])
            out_base = te(ids)[0]
            with AppliedAdapterContext(p0, unet=unet, text_encoder=te):
                out_masq = te(ids)[0]
            diff = float(torch.max((out_base - out_masq).abs()).item())
            self.assertGreater(diff, 1e-3)

            p1 = compose_s1_partial_te0(loaded, loaded, cand_te_scale=0.0, cand_unet_scale=0.5, partner_scale=0.0)
            self.assertEqual(p1.effective_cand_norms["buckets"]["text_encoder"], 0.0)

    def test_poisonlora_te_gradient_flow_and_norm_budget(self) -> None:
        from diffusers import DDPMScheduler
        from transformers import CLIPTokenizer

        unet, te = _make_fake_sd15_tree(d_model=8)
        for p in list(unet.parameters()) + list(te.parameters()):
            p.requires_grad_(False)
        tok = CLIPTokenizer.from_pretrained("unused")
        sched = DDPMScheduler.from_pretrained("unused")
        components = {
            "unet": unet,
            "text_encoder": te,
            "tokenizer": tok,
            "scheduler": sched,
        }
        cat_latents = torch.ones((2, 4, 2, 2)) * 0.5
        car_latents = torch.ones((2, 4, 2, 2)) * -0.5

        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "poison_budget_test"
            cfg = MVPConfig(
                lora_rank=4,
                te_lora_rank=2,
                ours_rank_ben=2,
                ours_rank_bd=2,
                max_train_steps=4,
                save_every_steps=2,
                learning_rate=0.05,
                target_frobenius_norm=0.25,
                poisonlora_train_te=True,
            )
            res = train_poisonlora(
                cfg=cfg,
                run_dir=run_dir,
                components=components,
                cat_latents=cat_latents,
                car_latents=car_latents,
            )
            norms = res["norms"]
            self.assertGreater(norms["buckets"]["text_encoder"], 0.0)
            self.assertLessEqual(norms["total_frobenius"], 0.25 + 1e-4)

            # Verify fallback norm budget when target_frobenius_norm is explicitly None
            run_dir_fb = Path(td) / "poison_fallback_test"
            masq_ref = LoRAAdapter(
                "masqlora",
                {
                    "unet.mid_block.attentions.0.transformer_blocks.0.attn2.to_k": LoRALayerFactor(
                        "unet",
                        "mid_block.attentions.0.transformer_blocks.0.attn2.to_k",
                        torch.ones((2, 8)) * 0.1,
                        torch.ones((8, 2)) * 0.1,
                    )
                },
            )
            masq_path = save_lora_adapter(masq_ref, Path(td) / "masq_ref.safetensors")
            masq_norm = compute_adapter_norms(masq_ref)["total_frobenius"]
            cfg_fb = MVPConfig(
                lora_rank=4,
                te_lora_rank=2,
                ours_rank_ben=2,
                ours_rank_bd=2,
                max_train_steps=4,
                save_every_steps=2,
                learning_rate=0.05,
                target_frobenius_norm=None,
                masqlora_adapter=str(masq_path),
                poisonlora_train_te=True,
            )
            res_fb = train_poisonlora(
                cfg=cfg_fb,
                run_dir=run_dir_fb,
                components=components,
                cat_latents=cat_latents,
                car_latents=car_latents,
            )
            self.assertGreater(res_fb["norms"]["buckets"]["text_encoder"], 0.0)
            self.assertLessEqual(res_fb["norms"]["total_frobenius"], masq_norm + 1e-4)

    def test_bottleneck_includes_down2_and_v2_distill_training_and_resume(self) -> None:
        self.assertTrue(
            is_ours_bottleneck_target("down_blocks.2.attentions.0.transformer_blocks.0.attn2.to_k")
        )
        self.assertTrue(
            is_ours_bottleneck_target("mid_block.attentions.0.transformer_blocks.0.attn2.to_v")
        )
        self.assertTrue(
            is_ours_bottleneck_target("up_blocks.1.attentions.0.transformer_blocks.0.attn2.to_out.0")
        )
        self.assertFalse(
            is_ours_bottleneck_target("down_blocks.0.attentions.0.transformer_blocks.0.attn2.to_k")
        )
        self.assertFalse(
            is_ours_bottleneck_target("down_blocks.1.attentions.0.transformer_blocks.0.attn2.to_k")
        )
        self.assertFalse(
            is_ours_bottleneck_target("up_blocks.2.attentions.0.transformer_blocks.0.attn2.to_k")
        )
        self.assertFalse(
            is_ours_bottleneck_target("up_blocks.3.attentions.0.transformer_blocks.0.attn2.to_k")
        )
        self.assertFalse(
            is_ours_bottleneck_target("down_blocks.2.attentions.0.transformer_blocks.0.attn1.to_k")
        )
        self.assertFalse(
            is_ours_bottleneck_target(
                "down_blocks.2.attentions.0.transformer_blocks.0.attn2.to_k",
                component="text_encoder",
            )
        )

        from diffusers import DDPMScheduler
        from transformers import CLIPTokenizer

        unet, te = _make_fake_sd15_tree(d_model=8)
        for p in list(unet.parameters()) + list(te.parameters()):
            p.requires_grad_(False)
        components = {
            "unet": unet,
            "text_encoder": te,
            "tokenizer": CLIPTokenizer.from_pretrained("unused"),
            "scheduler": DDPMScheduler.from_pretrained("unused"),
        }
        partner = LoRAAdapter(
            "p_train_proxy",
            {
                "unet.mid_block.attentions.0.transformer_blocks.0.attn2.to_k": LoRALayerFactor(
                    "unet",
                    "mid_block.attentions.0.transformer_blocks.0.attn2.to_k",
                    torch.ones((2, 8)) * 0.05,
                    torch.ones((8, 2)) * 0.05,
                )
            },
        )
        cat_latents = torch.ones((2, 4, 2, 2)) * 0.5
        car_latents = torch.ones((2, 4, 2, 2)) * -0.5

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run_v2_distill"
            cfg = MVPConfig(
                run_id="test_v2_distill",
                seed=7,
                ours_version="v2_distill",
                ours_distill_steps=2,
                save_every_steps=2,
                max_train_steps=2,
                target_frobenius_norm=4.0,
                lora_rank=4,
                ours_rank_ben=2,
                ours_rank_bd=2,
            )

            res1 = train_ours_mvp(
                cfg=cfg,
                run_dir=run_dir,
                components=components,
                cat_latents=cat_latents,
                car_latents=car_latents,
                p_train_adapter=partner,
            )
            self.assertEqual(res1["method_version"], "core_lora_v2_distill")
            self.assertLessEqual(res1["norms"]["total_frobenius"], cfg.target_frobenius_norm + 1e-4)
            self.assertEqual(res1["norms"]["buckets"]["text_encoder"], 0.0)
            self.assertEqual(res1["norms"]["buckets"]["unet_up2_up3"], 0.0)
            self.assertGreater(res1["norms"]["buckets"]["unet_mid_and_up1_attn2"], 0.0)
            ckpt = run_dir / "arms" / "ours_mvp" / "checkpoint_last.safetensors"
            self.assertTrue(ckpt.exists())

            cfg_resume = MVPConfig(
                run_id="test_v2_distill",
                seed=7,
                ours_version="v2_distill",
                ours_distill_steps=4,
                save_every_steps=2,
                max_train_steps=4,
                target_frobenius_norm=4.0,
                lora_rank=4,
                ours_rank_ben=2,
                ours_rank_bd=2,
            )
            res2 = train_ours_mvp(
                cfg=cfg_resume,
                run_dir=run_dir,
                components=components,
                cat_latents=cat_latents,
                car_latents=car_latents,
                p_train_adapter=partner,
            )
            self.assertTrue(res2.get("resumed_complete"))
            # Also verify mid-run checkpoint_wrappers.pt resume from step=2 -> step=4
            from .io_utils import md_read, md_write
            state_path = run_dir / "arms" / "ours_mvp" / "train_state.md"
            (run_dir / "arms" / "ours_mvp" / "adapter.safetensors").unlink()
            md_write(
                state_path,
                "Ours-MVP Train State",
                {**md_read(state_path), "status": "running", "step": 2, "max_steps": 4},
            )
            res3 = train_ours_mvp(
                cfg=cfg_resume,
                run_dir=run_dir,
                components=components,
                cat_latents=cat_latents,
                car_latents=car_latents,
                p_train_adapter=partner,
            )
            self.assertEqual(res3["method_version"], "core_lora_v2_distill")
            self.assertFalse(res3.get("resumed_complete", False))
            self.assertEqual(md_read(state_path).get("step"), "4")
            self.assertLessEqual(res3["norms"]["total_frobenius"], cfg_resume.target_frobenius_norm + 1e-4)
            self.assertLessEqual(
                res3["qo_frobenius"],
                cfg_resume.target_frobenius_norm * cfg_resume.ours_distill_qo_max_ratio + 1e-4,
            )


if __name__ == "__main__":
    unittest.main()
