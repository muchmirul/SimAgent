"""Space — the input boundary (atom #1).

A Space is where a free entity's value lives. It is the ONLY module on the
input side that knows what "d dimensions" means: sampling, validity,
perturbation (the annealer's move), exact rational snapping, and finite
enumeration all live here. v1 ships exactly two concrete spaces — `Box`
(uniform box in ℝ^shape) and `IntBox` (integer grid in ℤ^shape) — mirroring
the historical VarSpec semantics bit for bit:

- `Box.sample`     == rng.uniform(low, high, size=shape)
- `IntBox.sample`  == rng.integers(low, high+1, size=shape).astype(float)
- `perturb`        == np.clip(value + rng.normal(0, sigma, size=shape), low, high)
- `IntBox.enumerate_cases` == the exact itertools.product order run_exhaustive
  has always used

Keeping the random-call sequences identical is a hard requirement: search
seeds, kernel-journal state hashes, and the known-answer tests all depend on
byte-identical draws.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np

from ..sandbox import certify as certify_mod

# Integer inputs must stay well within float64's exact range (2^53) for a
# float check on integer cases to be genuinely exact arithmetic (see search.py).
SAFE_INT_BOUND = 2**40


def _entries(shape) -> int:
    n = 1
    for d in shape:
        n *= int(d)  # python int: no np.prod int64 overflow
    return n


class Space:
    """Interface: where values live. Subclasses define the five operations."""

    shape: tuple[int, ...]

    def sample(self, rng: np.random.Generator) -> np.ndarray:
        raise NotImplementedError

    def valid(self, value) -> bool:
        raise NotImplementedError

    def perturb(self, rng: np.random.Generator, value: np.ndarray, sigma: float) -> np.ndarray:
        """One annealing move. Shared semantics: gaussian jitter clipped to
        the box — exactly the historical `_refine` proposal."""
        raise NotImplementedError

    def exact(self, value, max_den: int = 64):
        """Snap to exact rationals (sympy) for the certification path."""
        return certify_mod.rationalize_array(value, max_den=max_den)

    def enumerate_cases(self) -> list[np.ndarray] | None:
        """Every point of a finite space (None if not finite)."""
        return None

    def count(self) -> int | None:
        """Number of points in a finite space (None if not finite);
        0 signals an empty/inverted range."""
        return None

    @property
    def int_exact(self) -> bool:
        """True iff every value is an integer within the exact-float64 guard."""
        return False


@dataclass(frozen=True)
class Box(Space):
    """Uniform box in ℝ^shape — any dimension."""

    shape: tuple[int, ...]
    low: float = -1.0
    high: float = 1.0

    def sample(self, rng: np.random.Generator) -> np.ndarray:
        return rng.uniform(self.low, self.high, size=self.shape)

    def valid(self, value) -> bool:
        a = np.asarray(value, dtype=float)
        return (
            a.shape == self.shape
            and bool(np.all(np.isfinite(a)))
            and bool(np.all(a >= self.low))
            and bool(np.all(a <= self.high))
        )

    def perturb(self, rng: np.random.Generator, value: np.ndarray, sigma: float) -> np.ndarray:
        return np.clip(value + rng.normal(0.0, sigma, size=np.asarray(value).shape),
                       self.low, self.high)


@dataclass(frozen=True)
class IntBox(Space):
    """Integer grid in ℤ^shape (values carried as floats, exactly representable)."""

    shape: tuple[int, ...]
    low: int = 0
    high: int = 1

    def sample(self, rng: np.random.Generator) -> np.ndarray:
        if int(self.high) < int(self.low):
            raise ValueError(f"integer domain has low ({self.low}) > high ({self.high})")
        return rng.integers(int(self.low), int(self.high) + 1, size=self.shape).astype(float)

    def valid(self, value) -> bool:
        a = np.asarray(value, dtype=float)
        return (
            a.shape == self.shape
            and bool(np.all(np.isfinite(a)))
            and bool(np.all(a == np.round(a)))
            and bool(np.all(a >= self.low))
            and bool(np.all(a <= self.high))
        )

    def perturb(self, rng: np.random.Generator, value: np.ndarray, sigma: float) -> np.ndarray:
        # Historical behavior: integer vars get the same gaussian move as reals
        # (refine is only reachable for margin-valued specs; enumeration is the
        # honest path for finite domains).
        return np.clip(value + rng.normal(0.0, sigma, size=np.asarray(value).shape),
                       self.low, self.high)

    def enumerate_cases(self) -> list[np.ndarray]:
        vals = range(int(self.low), int(self.high) + 1)
        return [
            np.array(combo, dtype=float).reshape(self.shape)
            for combo in itertools.product(vals, repeat=_entries(self.shape))
        ]

    def count(self) -> int:
        per_entry = int(self.high) - int(self.low) + 1
        if per_entry <= 0:
            return 0
        return per_entry ** _entries(self.shape)

    @property
    def int_exact(self) -> bool:
        return abs(int(self.low)) <= SAFE_INT_BOUND and abs(int(self.high)) <= SAFE_INT_BOUND


def from_varspec(v) -> Space:
    """Adapter from the historical VarSpec (name/shape/low/high/kind)."""
    shape = tuple(v.shape)
    if v.kind == "graph":
        return GraphSpace(n=int(shape[0]))
    if v.kind == "int":
        return IntBox(shape=shape, low=int(v.low), high=int(v.high))
    return Box(shape=shape, low=float(v.low), high=float(v.high))


@dataclass(frozen=True)
class GraphSpace(Space):
    """Simple undirected graphs on n labelled vertices.

    The value is the adjacency matrix: symmetric, 0/1, zero diagonal, carried
    as floats like every other Space so the whole numeric layer is unchanged.
    This is the first DISCRETE space, and it is what a combinatorialist's
    object actually is - the box types cannot express one at all.

    A move flips edges rather than nudging coordinates, which is the discrete
    analogue of the annealer's jitter. Small n enumerates completely
    (2^(n choose 2) graphs), so exhaustion applies.
    """

    n: int

    @property
    def shape(self) -> tuple[int, ...]:  # type: ignore[override]
        return (self.n, self.n)

    @property
    def low(self) -> float:
        return 0.0

    @property
    def high(self) -> float:
        return 1.0

    def _pairs(self) -> list[tuple[int, int]]:
        return [(i, j) for i in range(self.n) for j in range(i + 1, self.n)]

    def _from_bits(self, bits) -> np.ndarray:
        A = np.zeros((self.n, self.n), dtype=float)
        for (i, j), b in zip(self._pairs(), bits):
            A[i, j] = A[j, i] = float(b)
        return A

    def sample(self, rng: np.random.Generator) -> np.ndarray:
        return self._from_bits(rng.integers(0, 2, size=len(self._pairs())))

    def valid(self, value) -> bool:
        A = np.asarray(value, dtype=float)
        return (
            A.shape == self.shape
            and bool(np.all(np.isfinite(A)))
            and bool(np.all((A == 0) | (A == 1)))
            and bool(np.all(A == A.T))
            and bool(np.all(np.diag(A) == 0))
        )

    def perturb(self, rng: np.random.Generator, value: np.ndarray, sigma: float) -> np.ndarray:
        """Flip edges. `sigma` scales how many, so the annealer's cooling
        schedule keeps working: hot = rewire freely, cold = one edge."""
        A = np.array(value, dtype=float)
        pairs = self._pairs()
        k = max(1, min(len(pairs), int(round(sigma * len(pairs)))))
        for idx in rng.choice(len(pairs), size=k, replace=False):
            i, j = pairs[idx]
            A[i, j] = A[j, i] = 1.0 - A[i, j]
        return A

    def enumerate_cases(self) -> list[np.ndarray] | None:
        total = self.count()
        if total is None or total > 1 << 20:
            return None
        m = len(self._pairs())
        return [self._from_bits([(mask >> b) & 1 for b in range(m)])
                for mask in range(total)]

    def count(self) -> int | None:
        return 1 << len(self._pairs())

    @property
    def int_exact(self) -> bool:
        return True


def spaces_for(spec) -> dict[str, Space]:
    """All of a spec's free-variable spaces, keyed by name (domain order)."""
    return {v.name: from_varspec(v) for v in spec.domain}


def sample_vars(rng: np.random.Generator, spec) -> dict[str, np.ndarray]:
    """The one authoritative domain sampler (search, play, web, CLI).

    Lives at the input boundary — the only place that knows what sampling
    means. Keeps the historical per-var error message."""
    out: dict[str, np.ndarray] = {}
    for v in spec.domain:
        try:
            out[v.name] = from_varspec(v).sample(rng)
        except ValueError as e:
            raise ValueError(f"{v.name}: {e}") from None
    return out
