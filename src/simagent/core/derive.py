"""Derive — atom #4 (physical law): derived entities recompute when their
ancestors move.

The constructor registry is the closed vocabulary of things an agent (or a
Claim) may build — the sketching hand. Every constructor is dimension-generic
where the underlying geometry is (circumcenter/barycentric/volume work for a
k-simplex in ℝᵈ for any d). Insertion order of the entity table is already
topological (arguments must exist before their dependents), so recomputation
is a single ordered sweep.
"""
from __future__ import annotations

import numpy as np
import sympy as sp

from ..sandbox import certify as certify_mod
from ..sandbox import geometry
from .entity import World


def _midpoint(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return (np.asarray(a, dtype=float) + np.asarray(b, dtype=float)) / 2.0


def _centroid(pts: np.ndarray) -> np.ndarray:
    return np.asarray(pts, dtype=float).mean(axis=0)


def _segment(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.stack([np.asarray(a, dtype=float), np.asarray(b, dtype=float)])


def _row(pts: np.ndarray, index: float) -> np.ndarray:
    return np.asarray(pts, dtype=float)[int(index)]


# -- the geometry kit ---------------------------------------------------------
# Named objects, not coordinate blobs: a constructor is what the scene can draw
# and what a measure can talk about qualitatively. Each one is paired with an
# exact counterpart below so a recipe replays in rational arithmetic.

def _sub(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.asarray(a, dtype=float).ravel() - np.asarray(b, dtype=float).ravel()


def _dot(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    return np.asarray(float(np.dot(np.asarray(u, dtype=float).ravel(),
                                   np.asarray(v, dtype=float).ravel())))


def _cross2(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    u = np.asarray(u, dtype=float).ravel()
    v = np.asarray(v, dtype=float).ravel()
    return np.asarray(float(u[0] * v[1] - u[1] * v[0]))


def _distance_sq(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    d = _sub(a, b)
    return np.asarray(float(np.dot(d, d)))


def _foot(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ab = _sub(b, a)
    den = float(np.dot(ab, ab))
    if den == 0.0:
        raise ValueError("foot: A and B coincide, the line is undefined")
    t = float(np.dot(_sub(p, a), ab)) / den
    return np.asarray(a, dtype=float).ravel() + t * ab


def _reflect(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return 2.0 * _foot(p, a, b) - np.asarray(p, dtype=float).ravel()


def _orthocenter(pts: np.ndarray) -> np.ndarray:
    """Euler line: H = A + B + C - 2*O. Division-free given the circumcenter."""
    T = np.asarray(pts, dtype=float)
    if T.shape[0] != 3:
        raise ValueError("orthocenter is defined for a triangle (3 points)")
    return T.sum(axis=0) - 2.0 * np.asarray(geometry.circumcenter(T), dtype=float)


def _incenter(pts: np.ndarray) -> np.ndarray:
    T = np.asarray(pts, dtype=float)
    if T.shape[0] != 3:
        raise ValueError("incenter is defined for a triangle (3 points)")
    w = np.array([np.linalg.norm(T[(i + 1) % 3] - T[(i + 2) % 3]) for i in range(3)])
    if w.sum() == 0.0:
        raise ValueError("incenter: degenerate triangle")
    return (w[:, None] * T).sum(axis=0) / w.sum()


def _intersect_lines(a, b, c, d) -> np.ndarray:
    a, b, c, d = (np.asarray(x, dtype=float).ravel() for x in (a, b, c, d))
    r, s = b - a, d - c
    den = float(r[0] * s[1] - r[1] * s[0])
    if den == 0.0:
        raise ValueError("intersect_lines: the lines are parallel")
    q = c - a
    t = float(q[0] * s[1] - q[1] * s[0]) / den
    return a + t * r


# -- exact counterparts -------------------------------------------------------
# Convention: values are nested Python lists of sympy numbers (or a scalar),
# exactly mirroring the numeric layer's indexing so `P[0][1]` means one thing.

def _sym(v):
    # exact values pass through untouched; see the note in certify.py on
    # why nsimplify must never be pointed at something already exact
    if isinstance(v, sp.Basic):
        return v
    return sp.Rational(v) if isinstance(v, int) else sp.nsimplify(v, rational=True)


def _mat(rows) -> sp.Matrix:
    return sp.Matrix([[_sym(v) for v in r] for r in rows])


def _vec(v) -> list:
    return [_sym(x) for x in v]


def _x_circumcenter(pts) -> list:
    return list(certify_mod.exact_circumcenter(_mat(pts)))


def _x_barycentric(pts, x) -> list:
    return certify_mod.exact_barycentric(_mat(pts), sp.Matrix(len(x), 1, _vec(x)))


def _x_centroid(pts) -> list:
    M = _mat(pts)
    return [sum(M.col(j)) / M.rows for j in range(M.cols)]


def _x_midpoint(a, b) -> list:
    return [(x + y) / 2 for x, y in zip(_vec(a), _vec(b))]


def _x_segment(a, b) -> list:
    return [_vec(a), _vec(b)]


def _x_vertex(pts, index):
    return _vec(pts[int(index)])


def _x_simplex_volume(pts):
    M = _mat(pts)
    k = M.rows - 1
    if k != M.cols:
        raise ValueError("exact simplex_volume needs a full-dimensional simplex")
    E = sp.Matrix([[M[i, j] - M[0, j] for j in range(M.cols)] for i in range(1, M.rows)])
    return sp.Abs(E.det()) / sp.factorial(k)


def _x_sub(a, b) -> list:
    return [x - y for x, y in zip(_vec(a), _vec(b))]


def _x_dot(u, v):
    return sum(x * y for x, y in zip(_vec(u), _vec(v)))


def _x_cross2(u, v):
    u, v = _vec(u), _vec(v)
    return u[0] * v[1] - u[1] * v[0]


def _x_distance_sq(a, b):
    d = _x_sub(a, b)
    return sum(x * x for x in d)


def _x_foot(p, a, b) -> list:
    ab = _x_sub(b, a)
    den = sum(x * x for x in ab)
    if den == 0:
        raise ValueError("foot: A and B coincide, the line is undefined")
    t = _x_dot(_x_sub(p, a), ab) / den
    return [x + t * y for x, y in zip(_vec(a), ab)]


def _x_reflect(p, a, b) -> list:
    return [2 * f - x for f, x in zip(_x_foot(p, a, b), _vec(p))]


def _x_orthocenter(pts) -> list:
    M = _mat(pts)
    if M.rows != 3:
        raise ValueError("orthocenter is defined for a triangle (3 points)")
    o = _x_circumcenter(pts)
    return [sum(M.col(j)) - 2 * o[j] for j in range(M.cols)]


def _x_incenter(pts) -> list:
    M = _mat(pts)
    if M.rows != 3:
        raise ValueError("incenter is defined for a triangle (3 points)")
    w = [sp.sqrt(_x_distance_sq(list(M.row((i + 1) % 3)), list(M.row((i + 2) % 3))))
         for i in range(3)]
    tot = sum(w)
    if tot == 0:
        raise ValueError("incenter: degenerate triangle")
    return [sum(w[i] * M[i, j] for i in range(3)) / tot for j in range(M.cols)]


def _x_intersect_lines(a, b, c, d) -> list:
    a, b, c, d = _vec(a), _vec(b), _vec(c), _vec(d)
    r = [b[0] - a[0], b[1] - a[1]]
    s = [d[0] - c[0], d[1] - c[1]]
    den = r[0] * s[1] - r[1] * s[0]
    if den == 0:
        raise ValueError("intersect_lines: the lines are parallel")
    q = [c[0] - a[0], c[1] - a[1]]
    t = (q[0] * s[1] - q[1] * s[0]) / den
    return [a[0] + t * r[0], a[1] + t * r[1]]


CONSTRUCTORS: dict[str, dict] = {
    # name -> {fn, exact, arity, doc}
    "circumcenter": {
        "fn": lambda pts: np.asarray(geometry.circumcenter(np.asarray(pts, dtype=float))),
        "exact": _x_circumcenter,
        "arity": 1,
        "doc": "circumcenter of a (k+1, d) simplex — any dimension",
    },
    "barycentric": {
        "fn": lambda pts, x: np.asarray(
            geometry.barycentric(np.asarray(pts, dtype=float), np.asarray(x, dtype=float))
        ),
        "exact": _x_barycentric,
        "arity": 2,
        "doc": "barycentric coordinates of a point w.r.t. a simplex "
               "(all positive iff the point is strictly inside)",
    },
    "centroid": {"fn": _centroid, "exact": _x_centroid, "arity": 1,
                 "doc": "mean of a point set"},
    "midpoint": {"fn": _midpoint, "exact": _x_midpoint, "arity": 2,
                 "doc": "midpoint of two points"},
    "segment": {"fn": _segment, "exact": _x_segment, "arity": 2,
                "doc": "the segment between two points"},
    "simplex_volume": {
        "fn": lambda pts: np.asarray(geometry.simplex_volume(np.asarray(pts, dtype=float))),
        "exact": _x_simplex_volume,
        "arity": 1,
        "doc": "signed-volume magnitude of a simplex",
    },
    "vertex": {"fn": _row, "exact": _x_vertex, "arity": 2,
               "doc": "one row of a point set (second arg = index entity/scalar)"},
    "sub": {"fn": _sub, "exact": _x_sub, "arity": 2,
            "doc": "vector from the second point to the first (A - B)"},
    "dot": {"fn": _dot, "exact": _x_dot, "arity": 2,
            "doc": "inner product of two vectors; sign gives the angle's "
                   "sense (dot(sub(B,A), sub(C,A)) < 0 means the angle at A is obtuse)"},
    "cross2": {"fn": _cross2, "exact": _x_cross2, "arity": 2,
               "doc": "2D scalar cross product = twice the signed area; sign "
                      "tells which side of a line a point is on, zero means collinear"},
    "distance_sq": {"fn": _distance_sq, "exact": _x_distance_sq, "arity": 2,
                    "doc": "squared distance between two points (squared, so it "
                           "stays rational and Lean-encodable)"},
    "foot": {"fn": _foot, "exact": _x_foot, "arity": 3,
             "doc": "foot of the perpendicular from a point onto the line "
                    "through two points (P, A, B)"},
    "reflect": {"fn": _reflect, "exact": _x_reflect, "arity": 3,
                "doc": "reflection of a point across the line through two "
                       "points (P, A, B)"},
    "orthocenter": {"fn": _orthocenter, "exact": _x_orthocenter, "arity": 1,
                    "doc": "orthocenter of a triangle (3, d)"},
    "incenter": {"fn": _incenter, "exact": _x_incenter, "arity": 1,
                 "doc": "incenter of a triangle (3, d); uses side lengths, so "
                        "it is algebraic-but-not-rational — no Lean stamp"},
    "intersect_lines": {"fn": _intersect_lines, "exact": _x_intersect_lines, "arity": 4,
                        "doc": "intersection of line AB with line CD in 2D "
                               "(A, B, C, D); raises if they are parallel"},
}


def compute(world: World, name: str) -> np.ndarray:
    """Compute one derived entity from its argument values (which must exist)."""
    ent = world.entities[name]
    spec = CONSTRUCTORS.get(ent.ctor)
    if spec is None:
        raise KeyError(f"unknown constructor {ent.ctor!r}")
    args = []
    for a in ent.args:
        if a not in world.values:
            raise ValueError(f"{name!r}: argument {a!r} has no value yet")
        args.append(world.values[a])
    if len(args) != spec["arity"]:
        raise ValueError(f"{ent.ctor!r} takes {spec['arity']} args, got {len(args)}")
    return np.asarray(spec["fn"](*args), dtype=float)


def recompute(world: World, changed: set[str] | None = None) -> list[str]:
    """Recompute derived entities affected by `changed` (None = all), in the
    entity table's (topological) order. Returns the names recomputed.
    A constructor error clears that entity's value (degenerate state) rather
    than crashing the loop — measures report it as degenerate."""
    dirty = set(world.entities) if changed is None else set(changed)
    updated: list[str] = []
    for ent in world.entities.values():
        if ent.kind != "derived":
            continue
        if ent.name not in dirty and not (set(ent.args) & dirty):
            continue
        try:
            world.values[ent.name] = compute(world, ent.name)
            updated.append(ent.name)
        except Exception:  # noqa: BLE001 - degenerate geometry is a state, not a crash
            world.values.pop(ent.name, None)
            updated.append(ent.name)
        dirty.add(ent.name)
    return updated
