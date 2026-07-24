"""Exact-arithmetic layer: turn a numeric candidate into a certificate.

The search runs in floating point. Before we claim "counterexample", the
candidate is snapped to rational coordinates and the property is re-decided
with sympy exact arithmetic via a spec's `certify` code. A False from certify
on a rational instance is a genuine mathematical disproof of a universally
quantified statement (and symmetrically, True certifies an existence witness).

Helpers here are exposed to certify code; they operate on sympy Matrices of
Rationals mirroring the numeric toolbox in geometry.py.
"""
from __future__ import annotations

from fractions import Fraction

import numpy as np
import sympy as sp


def rationalize_array(arr, max_den: int = 64) -> sp.Matrix | sp.Rational | list:
    """Snap a float scalar/array to nearby rationals — any ndim (d-generic).

    ndim 0 -> Rational; ndim 1/2 -> sympy Matrix of Rationals (1-D becomes a
    (1, n) row matrix, the historical convention the exact geometry helpers
    rely on); ndim >= 3 -> nested Python lists of the ndim-2 base case. Small
    denominators keep certificates human-readable.
    """
    a = np.asarray(arr, dtype=float)
    if a.ndim == 0:
        f = Fraction(float(a)).limit_denominator(max_den)
        return sp.Rational(f.numerator, f.denominator)
    if a.ndim >= 3:
        return [rationalize_array(sub, max_den=max_den) for sub in a]
    if a.ndim == 1:
        a = a.reshape(1, -1)
    rows = []
    for row in a:
        rows.append(
            [
                sp.Rational(
                    Fraction(float(x)).limit_denominator(max_den).numerator,
                    Fraction(float(x)).limit_denominator(max_den).denominator,
                )
                for x in row
            ]
        )
    return sp.Matrix(rows)


def to_float(exact) -> np.ndarray | float:
    """Back-convert an exact value to floats (to re-run the numeric check)."""
    if isinstance(exact, sp.MatrixBase):
        return np.array(exact.tolist(), dtype=float)
    if isinstance(exact, list):
        return np.array([np.asarray(to_float(e), dtype=float) for e in exact])
    return float(exact)


def exact_repr(exact) -> object:
    """JSON-able representation ('p/q' strings) of an exact witness value."""
    if isinstance(exact, sp.MatrixBase):
        return [[str(exact[i, j]) for j in range(exact.cols)] for i in range(exact.rows)]
    if isinstance(exact, list):
        return [exact_repr(e) for e in exact]
    return str(exact)


def exact_circumcenter(pts: sp.Matrix) -> sp.Matrix:
    """Exact circumcenter of a simplex; pts is an (n+1) x n sympy Matrix."""
    p0 = pts.row(0)
    rows, rhs = [], []
    for i in range(1, pts.rows):
        d = pts.row(i) - p0
        rows.append([2 * d[j] for j in range(pts.cols)])
        rhs.append(sum(pts[i, j] ** 2 for j in range(pts.cols)) - sum(p0[j] ** 2 for j in range(pts.cols)))
    A = sp.Matrix(rows)
    b = sp.Matrix(rhs)
    return A.LUsolve(b)  # column vector, n x 1


def exact_barycentric(pts: sp.Matrix, x: sp.Matrix) -> list:
    """Exact barycentric coordinates of column vector x w.r.t. simplex pts."""
    p0 = pts.row(0).T
    cols = [(pts.row(i) - pts.row(0)).T for i in range(1, pts.rows)]
    T = sp.Matrix.hstack(*cols)
    w = T.LUsolve(x - p0)
    coords = [1 - sum(w)]
    coords.extend(list(w))
    # NEVER nsimplify an already-exact value: it searches for a "nicer"
    # closed form and will happily hand back an irrational surd that is
    # merely CLOSE to the rational it was given, which silently leaves
    # exact arithmetic. cancel() keeps it canonical and rational.
    return [sp.cancel(c) for c in coords]
