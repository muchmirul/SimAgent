"""Claim — atom #6 (hypothesis under test), with the native engine (P5).

A Claim = quantifier + free Spaces + a recipe of constructions + a
distinguished measure, all drawn from CLOSED REGISTRIES — no exec'd code
anywhere on the native path (decision D3: typed vocabulary replaces
LLM-emitted code strings; AlphaGeometry-proven). A native Claim is
"spec-like": it duck-types every surface the search/proof/answer machinery
consumes (`domain`, `quantifier`, `compiled()`, `save()`, …), so the truth
layer runs on Claims unchanged.

The engine is native: recipe and registry keys only. Executable legacy specs
are rejected at the loading boundary, so loading a problem can never execute
code from that problem.

Only the truth layer decides claims; a Claim carries no verdict state.
"""
from __future__ import annotations

import ast
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..sandbox import geometry, leangen, scene
from ..sandbox import certify as certify_mod
from . import expr
from .derive import CONSTRUCTORS
from .space import Box, GraphSpace, IntBox, Space

CLAIM_FORMAT = "claim/1"
CLAIM_ID_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
_CLAIM_ID = re.compile(CLAIM_ID_PATTERN)
_ENTITY_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LEAN_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ClaimValidationError(ValueError):
    """A Claim failed the executable contract and must not be run."""


@dataclass(frozen=True)
class FreeVar:
    """Flat description of one free entity for prompts and enumeration."""

    name: str
    shape: list[int]
    low: float
    high: float
    kind: str  # "real" | "int"


@dataclass
class NativeCheckResult:
    holds: bool
    margin: float | None
    data: dict


# -- registries: the closed vocabulary ----------------------------------------

def _recipe_env(recipe: list[dict], vars: dict) -> dict:
    env = {k: np.asarray(v, dtype=float) for k, v in vars.items()}
    for step in recipe:
        fn = CONSTRUCTORS[step["ctor"]]["fn"]
        env[step["name"]] = np.asarray(
            fn(*[env[a] for a in step["args"]]), dtype=float
        )
    return env


def _measure_min_coord(env: dict, recipe: list[dict], params: dict) -> NativeCheckResult:
    w = np.asarray(env[params["of"]], dtype=float).ravel()
    margin = float(w.min())
    data = {s["name"]: env[s["name"]].tolist() for s in recipe}
    return NativeCheckResult(holds=margin > 0, margin=margin, data=data)


def _measure_sum_odds_square(env: dict, recipe: list[dict], params: dict) -> NativeCheckResult:
    k = int(env[params["of"]])
    total = sum(2 * i + 1 for i in range(k))
    return NativeCheckResult(
        holds=total == k * k,
        margin=None,
        data={"n": k, "sum_of_first_n_odds": total, "n_squared": k * k},
    )


def _measure_euler_characteristic(env: dict, recipe: list[dict], params: dict) -> NativeCheckResult:
    V, E, F = geometry.hull_counts(env[params["of"]])
    chi = V - E + F
    return NativeCheckResult(holds=chi == 2, margin=None,
                             data={"V": V, "E": E, "F": F, "chi": chi})


def _measure_expr(env: dict, recipe: list[dict], params: dict) -> NativeCheckResult:
    margin = float(expr.evaluate(expr.parse(params["margin"]), env))
    data = {s["name"]: np.asarray(env[s["name"]], dtype=float).tolist() for s in recipe}
    return NativeCheckResult(holds=margin > 0, margin=margin, data=data)


def _additive_terms(node, sign: int = 1):
    """Split an expression into its top-level signed terms, for description."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
        yield from _additive_terms(node.left, sign)
        yield from _additive_terms(
            node.right, sign if isinstance(node.op, ast.Add) else -sign
        )
    else:
        yield ast.unparse(node), node, sign


def _describe_env(vars: dict, check: dict) -> dict:
    env = {k: np.asarray(v, dtype=float) for k, v in vars.items()}
    for name, value in (check.get("data") or {}).items():
        env[name] = np.asarray(value, dtype=float)
    return env


def _qualitative_expr(vars: dict, check: dict, params: dict) -> list[str]:
    """Each top-level term of the margin, evaluated.

    The total alone says the claim fails but not which part of the expression
    carried it there; the terms are computed facts, so reporting them is
    perception rather than advice.
    """
    try:
        tree = expr.parse(params["margin"])
    except expr.ExprError:
        return []
    env, parts = _describe_env(vars, check), []
    for label, node, sign in _additive_terms(tree):
        try:
            value = sign * float(expr.evaluate(node, env))
        except Exception:  # noqa: BLE001 - an undescribable term is simply omitted
            continue
        parts.append(f"{label} contributes {value:+.4g}")
    if len(parts) < 2:
        return []
    return [f"margin = {params['margin']}, term by term: " + "; ".join(parts)]


def _qualitative_min_coord(vars: dict, check: dict, params: dict) -> list[str]:
    of = params["of"]
    w = np.asarray((check.get("data") or {}).get(of) or [], dtype=float).ravel()
    if w.size == 0:
        return []
    k = int(np.argmin(w))
    if float(w.min()) > 0:
        return [
            f"the point is INSIDE the simplex (all {w.size} coordinates of {of} "
            f"positive; smallest is {of}[{k}] = {w.min():.4g})"
        ]
    return [
        f"the point is OUTSIDE the simplex — beyond the face opposite vertex {k} "
        f"({of}[{k}] = {w.min():.4g} < 0)"
    ]


def _qualitative_sum_odds(vars: dict, check: dict, params: dict) -> list[str]:
    data = check.get("data") or {}
    n, total, square = data.get("n"), data.get("sum_of_first_n_odds"), data.get("n_squared")
    if n is None:
        return []
    verb = "equals" if total == square else "differs from"
    return [
        f"at n = {n} the sum of the first {n} odd numbers is {total} and n squared "
        f"is {square}, so the sum {verb} n squared"
    ]


def _qualitative_euler(vars: dict, check: dict, params: dict) -> list[str]:
    data = check.get("data") or {}
    if data.get("chi") is None:
        return []
    return [
        f"the convex hull has V = {data['V']} vertices, E = {data['E']} edges and "
        f"F = {data['F']} faces, so V - E + F = {data['chi']}"
    ]


MEASURES = {
    "expr": {"fn": _measure_expr, "params": ("margin",),
             "qualitative": _qualitative_expr,
             "doc": "margin = a rational arithmetic expression over the free "
                    "entities and recipe results, written so margin > 0 means "
                    "the property holds (e.g. for 'lhs >= rhs' write "
                    "'lhs - rhs'). Operators + - * / and ** with an integer "
                    "exponent, plus abs/min/max/sum and integer indexing like "
                    "P[0]; this is THE general measure — prefer it over a "
                    "problem-specific one"},
    "min_coord": {"fn": _measure_min_coord, "params": ("of",),
                  "qualitative": _qualitative_min_coord,
                  "doc": "margin = smallest coordinate of a derived vector "
                         "(e.g. barycentric weights: positive iff inside)"},
    "sum_of_first_odds_equals_square": {"fn": _measure_sum_odds_square, "params": ("of",),
                                        "qualitative": _qualitative_sum_odds,
                                        "doc": "discrete: sum of first n odds == n^2"},
    "euler_characteristic": {"fn": _measure_euler_characteristic, "params": ("of",),
                             "qualitative": _qualitative_euler,
                             "doc": "discrete: V - E + F == 2 on the 3D convex hull"},
}


def _constraint_min_volume(vars: dict, params: dict) -> bool:
    return geometry.simplex_volume(np.asarray(vars[params["of"]], dtype=float)) > float(
        params.get("threshold", 0.05)
    )


def _constraint_hull_valid(vars: dict, params: dict) -> bool:
    try:
        geometry.hull_counts(np.asarray(vars[params["of"]], dtype=float))
        return True
    except Exception:  # noqa: BLE001
        return False


def _constraint_expr_nonneg(vars: dict, params: dict) -> bool:
    """The general validity filter: sample only where an expression is >= 0.

    This is how an IMPLICATION is stated ("every graph with at least 5 edges
    has a triangle"): the hypothesis filters the domain, the measure carries
    the conclusion."""
    env = _recipe_env(params.get("_recipe") or [], vars)
    try:
        return bool(expr.evaluate(expr.parse(params["expr"]), env) >= 0)
    except expr.ExprError:
        return False


CONSTRAINTS = {
    "expr_nonneg": {"fn": _constraint_expr_nonneg, "params": ("expr",),
                    "doc": "valid only where a rational expression is >= 0; the "
                           "general way to state a hypothesis that filters the "
                           "domain (an implication's antecedent)"},
    "min_volume": {"fn": _constraint_min_volume, "params": ("of", "threshold"),
                   "doc": "simplex volume above a nondegeneracy threshold"},
    "hull_valid": {"fn": _constraint_hull_valid, "params": ("of",),
                   "doc": "the point cloud has a valid convex hull"},
}


def _certify_simplex_inside(exact: dict, recipe: list[dict], params: dict) -> bool:
    T = exact[params["of"]]
    c = certify_mod.exact_circumcenter(T)
    w = certify_mod.exact_barycentric(T, c)
    return all(x > 0 for x in w)


def _exact_recipe_env(recipe: list[dict], exact_vars: dict) -> dict:
    """Replay the recipe in exact arithmetic, so a margin may read derived
    entities (the whole geometry kit) and still be certified.

    Raises if a constructor has no exact counterpart — the run then stays
    numeric-only rather than certifying a float."""
    env = expr.exact_env(exact_vars)
    for step in recipe:
        spec = CONSTRUCTORS[step["ctor"]]
        fn = spec.get("exact")
        if fn is None:
            raise ValueError(f"constructor {step['ctor']!r} has no exact counterpart")
        env[step["name"]] = fn(*[env[a] for a in step["args"]])
    return env


def _certify_expr(exact: dict, recipe: list[dict], params: dict) -> bool:
    """Exact-rational sign of the same margin the sandbox measured, with the
    recipe replayed in exact arithmetic first."""
    env = _exact_recipe_env(recipe, exact)
    return bool(expr.evaluate(expr.parse(params["margin"]), env, exact=True) > 0)


CERTIFIERS = {
    "expr": {"fn": _certify_expr, "params": ("margin",),
             "doc": "exact-rational evaluation of the measure's margin "
                    "expression (must repeat it verbatim)"},
    "simplex_circumcenter_inside": {
        "fn": _certify_simplex_inside, "params": ("of",),
        "doc": "exact-rational: circumcenter strictly inside the simplex",
    },
}


def _lean_simplex(exact: dict, recipe: list[dict], params: dict) -> str:
    return leangen.lean_simplex_circumcenter(
        exact[params["of"]], theorem=params["theorem"], title=params["title"]
    )


def _lean_bounded_nat(exact: dict, recipe: list[dict], params: dict) -> str:
    return leangen.lean_bounded_nat(
        theorem=params["theorem"], title=params["title"],
        defs=params["defs"], statement=params["statement"],
    )


def _lean_expr(exact: dict, recipe: list[dict], params: dict) -> str:
    tree = expr.parse(params["margin"])
    env = _exact_recipe_env(recipe, exact)
    # only free variables may be Lean atoms: see expr.lean_form
    atoms, term = expr.lean_form(tree, env, free=set(exact))
    negative = not bool(expr.evaluate(tree, env, exact=True) > 0)
    return leangen.lean_expr_sign(
        atoms, term, theorem=params["theorem"], title=params["title"],
        negative=negative,
    )


def _atom_names(prefix: str, value) -> list:
    """Nested atom names mirroring a nested exact value."""
    if isinstance(value, (list, tuple)):
        return [_atom_names(f"{prefix}_{i}", v) for i, v in enumerate(value)]
    return prefix


def _flatten_atoms(names, values, out: dict) -> None:
    if isinstance(names, list):
        for n, v in zip(names, values):
            _flatten_atoms(n, v, out)
    else:
        out[names] = values


def _lean_recipe(exact: dict, recipe: list[dict], params: dict) -> str:
    """Certificate for a margin that reads DERIVED entities.

    Every recipe step must supply the equations that define its output from
    its arguments (leangen.RECIPE_PINS); without them the derived value would
    enter Lean as a bare number, proving nothing about its construction, so a
    missing pin raises and the sandbox verdict stands.
    """
    env = _exact_recipe_env(recipe, exact)
    names = {k: _atom_names(k, v) for k, v in env.items()}
    atoms: dict = {}
    for k, v in env.items():
        _flatten_atoms(names[k], v, atoms)

    pins: list[str] = []
    for step in recipe:
        pin = leangen.RECIPE_PINS.get(step["ctor"])
        if pin is None:
            raise ValueError(
                f"constructor {step['ctor']!r} has no Lean pinning equations; "
                "a certificate over its output would check a bare number"
            )
        pins.extend(pin(names[step["name"]], *[names[a] for a in step["args"]]))

    of = params["of"]
    T = names[of]
    edges = [[f"(qsub {T[i][j]} {T[0][j]})" for j in range(len(T[0]))]
             for i in range(1, len(T))]

    tree = expr.parse(params["margin"])
    value = expr.evaluate(tree, env, exact=True)
    negative = not bool(value > 0)
    src = params["margin"].replace(" ", "")
    if src.startswith("min(") and src.endswith(")") and src[4:-1] in env:
        # "min(W) < 0" is exactly "some W_k < 0", and that HAS a Q-term while
        # min itself does not. Same statement, encodable.
        vec = src[4:-1]
        comps = names[vec]
        k = min(range(len(comps)), key=lambda i: env[vec][i])
        conclusion = [f"qlt {comps[k]} {leangen._q(0)}"] if negative else [
            f"qlt {leangen._q(0)} {c}" for c in comps]
        return leangen.lean_recipe_witness(
            atoms, pins, edges, conclusion,
            theorem=params["theorem"], title=params["title"],
        )
    # derived atoms are legitimate HERE: the pins above tie them to the free
    # variables, which is exactly what expr.lean_form refuses to assume
    term_atoms, term = expr.lean_form(tree, env)
    for name, val in term_atoms.items():
        atoms.setdefault(name, val)
    zero = leangen._q(0)
    conclusion = [f"def margin : Q := {leangen._render_q(term)}",
                  f"qlt margin {zero}" if negative else f"qlt {zero} margin"]
    return leangen.lean_recipe_witness(
        atoms, pins, edges, conclusion[1:], theorem=params["theorem"],
        title=params["title"], extra_defs=[conclusion[0]],
    )


LEANS = {
    "recipe": {"fn": _lean_recipe, "params": ("margin", "of", "theorem", "title"),
               "doc": "certificate for a margin over DERIVED entities: pins each "
                      "construction to its defining equations, so the kernel "
                      "checks how the numbers were built (`of` names the point "
                      "set whose nondegeneracy makes the construction unique)"},
    "expr": {"fn": _lean_expr, "params": ("margin", "theorem", "title"),
             "doc": "kernel-checked sign of the margin expression at an exact "
                    "rational point (no dimension cap; rejects division)"},
    "simplex_circumcenter": {"fn": _lean_simplex,
                             "params": ("of", "theorem", "title"),
                             "doc": "counterexample certificate (d<=3)"},
    "bounded_nat": {"fn": _lean_bounded_nat,
                    "params": ("theorem", "title", "defs", "statement"),
                    "doc": "exhaustion certificate over a bounded Nat statement"},
}


# -- scene builders (views over the recipe) -----------------------------------

def _p3(v) -> list[float]:
    a = np.asarray(v, dtype=float).ravel()
    return a[:3].tolist() if a.size >= 3 else a.tolist()


def _scene_simplex(env: dict, params: dict) -> list[dict]:
    T = np.asarray(env[params["of"]], dtype=float)
    center_name = params.get("center", "circumcenter")
    c = np.asarray(env[center_name], dtype=float)
    w = np.asarray(env[params.get("weights", "barycentric")], dtype=float)
    inside = bool(w.min() > 0)
    m, d = T.shape
    projected = d > 3
    P = np.array([_p3(row) for row in T])
    c3 = _p3(c)
    r = float(np.linalg.norm(T[0] - c))  # true radius, full dimension
    prims = []
    if d == 2:
        prims.append(scene.polygon(T, color=scene.FACE, opacity=0.45))
    elif d >= 3:
        faces = [[i, j, k] for i in range(m) for j in range(i + 1, m)
                 for k in range(j + 1, m)]
        prims.append(scene.mesh(P.tolist(), faces, color=scene.FACE, opacity=0.25))
    edges = [(P[i], P[j]) for i in range(m) for j in range(i + 1, m)]
    prims.append(scene.segments(edges, color=scene.EDGE, width=2.0))
    # the sphere is the CIRCUMsphere: only honest when the centre is the
    # circumcentre, so a claim about another centre turns it off
    if not projected and params.get("circle", True):
        prims.append(scene.sphere(c3, r, color=scene.HALO, opacity=0.14))
    # The vertices ARE the free variable, so a picked one can be moved. The
    # centre is derived: it has no row of its own to change.
    prims.append(scene.points(P, color=scene.INK, radius=0.05,
                              binds=None if projected else params["of"]))
    prims.append(scene.points([c3], color=scene.GOOD if inside else scene.BAD,
                              radius=0.07, name=center_name))
    label = "circumcenter %s (min barycentric = %.3f)" % (
        "inside" if inside else "OUTSIDE", float(w.min()))
    if projected:
        label += f"  ·  projection ℝ^{d} → ℝ³ — trust the numbers over the picture"
    prims.append(scene.label(label))
    return prims


def _scene_hull3d(env: dict, params: dict) -> list[dict]:
    Pts = np.asarray(env[params["of"]], dtype=float)
    V, E, F = geometry.hull_counts(Pts)
    verts, faces = geometry.hull_mesh(Pts)
    edges, seen = [], set()
    for f in faces:
        for i in range(3):
            a, b = sorted((f[i], f[(i + 1) % 3]))
            if (a, b) not in seen:
                seen.add((a, b))
                edges.append((verts[a], verts[b]))
    return [
        scene.mesh(verts, faces, color=scene.FACE, opacity=0.25),
        scene.segments(edges, color=scene.EDGE, width=1.5),
        scene.points(Pts, color=scene.INK, radius=0.04, binds=params["of"]),
        scene.label("V=%d  E=%d  F=%d   V-E+F=%d" % (V, E, F, V - E + F)),
    ]


def _scene_gnomon(env: dict, params: dict) -> list[dict]:
    n = int(env[params["of"]])
    k = min(max(n, 1), 14)
    palette = ["#1a73e8", "#c8890a", "#137333", "#c5221f", "#7b3fa0", "#c05621", "#0f766e"]
    prims = []
    s = 2.4 / k
    for layer in range(k):
        pts = []
        for i in range(layer + 1):
            pts.append([i * s, layer * s])
            if i != layer:
                pts.append([layer * s, i * s])
        prims.append(scene.points(pts, color=palette[layer % len(palette)],
                                  radius=min(0.4 * s, 0.06)))
    prims.append(scene.label(
        "n=%d: gnomon layers 1,3,5,... tile the %dx%d square" % (n, k, k)))
    return prims


def _scene_graph(env: dict, params: dict) -> list[dict]:
    """Vertices on a circle, edges as segments. A graph is the one discrete
    object that draws itself, which is why graph theory suits this harness."""
    A = np.asarray(env[params["of"]], dtype=float)
    n = A.shape[0]
    ang = 2.0 * np.pi * np.arange(n) / max(n, 1)
    P = np.stack([np.cos(ang), np.sin(ang), np.zeros(n)], axis=1)
    edges = [(P[i], P[j]) for i in range(n) for j in range(i + 1, n) if A[i, j] > 0]
    prims = []
    if edges:
        prims.append(scene.segments(edges, color=scene.FACE, width=2.5))
    prims.append(scene.points(P, color=scene.INK, radius=0.06, name=params["of"]))
    deg = A.sum(axis=1).astype(int)
    prims.append(scene.label(
        "%d vertices, %d edges, degrees %s"
        % (n, int(A.sum() // 2), deg.tolist())))
    return prims


def _scene_point(env: dict, params: dict) -> list[dict]:
    """The configuration itself, plotted. Generic partner to the `expr`
    measure: the shape of an algebraic claim lives in the field view, so this
    only has to show honestly where the current point sits."""
    A = np.asarray(env[params["of"]], dtype=float)
    P = np.array([_p3(r) for r in A]) if A.ndim == 2 else np.array([_p3(A)])
    d = A.shape[-1] if A.ndim >= 1 else 1
    origin = [0.0] * P.shape[1]
    prims = [
        scene.segments([(origin, p) for p in P], color=scene.EDGE, width=1.5),
        scene.points(P, color=scene.HALO, radius=0.06, name=params["of"],
                     binds=params["of"] if A.ndim == 2 and A.shape[-1] <= 3 else None),
    ]
    label = "%s = %s" % (params["of"], np.array2string(A, precision=3))
    if d > 3:
        label += "  ·  projection ℝ^%d → ℝ³ — trust the numbers over the picture" % d
    prims.append(scene.label(label))
    return prims


SCENES = {
    "graph": {"fn": _scene_graph, "params": ("of",),
              "doc": "draw a graph: vertices on a circle, edges as segments"},
    "point": {"fn": _scene_point, "params": ("of",),
              "doc": "plot a free entity as a point (or points) in space; the "
                     "general scene for algebraic claims"},
    "simplex": {"fn": _scene_simplex, "params": ("of", "center", "weights"),
                "doc": "simplex + circumsphere + center; projects when d > 3"},
    "hull3d": {"fn": _scene_hull3d, "params": ("of",), "doc": "3D convex hull mesh"},
    "gnomon_square": {"fn": _scene_gnomon, "params": ("of",),
                      "doc": "picture proof of the odd-number square"},
}


# -- the native engine (CompiledSpec-compatible surface) ----------------------

class NativeEngine:
    """check/valid/build_scene/certify/lean_certificate over the registries —
    the exec-free replacement for CompiledSpec."""

    def __init__(self, claim: "Claim"):
        self.claim = claim
        self.has_certify = claim.certify is not None
        self.has_lean_certificate = claim.lean is not None
        # Parsed once: `valid` runs on every sample of every search.
        self._assumed = [expr.parse(a) for a in (claim.assume or [])]

    def check(self, **vars) -> NativeCheckResult:
        env = _recipe_env(self.claim.recipe, vars)
        m = MEASURES[self.claim.measure["kind"]]
        res = m["fn"](env, self.claim.recipe, self.claim.measure)
        if res.margin is not None and bool(res.holds) != (res.margin > 0):
            raise ValueError("measure inconsistency: holds must equal margin > 0")
        return res

    def valid(self, **vars) -> bool:
        # A claim's hypotheses say which points it is ABOUT, so a point where
        # one fails is a point the claim asserts nothing at and can never be
        # settled by. `assume` used to be read only by the proof path, which
        # left the checker and the prover disagreeing about the same claim:
        # `conditional-cubic` assumes x >= 0, and certifying it at x = -2
        # returned an exact witness with margin -5 and holds False, a checkable
        # "counterexample" to a claim that never covered that point.
        if self._assumed:
            env = _recipe_env(self.claim.recipe, vars)
            for tree in self._assumed:
                if float(expr.evaluate(tree, env)) < 0:
                    return False
        if self.claim.constraint is None:
            return True
        c = CONSTRAINTS[self.claim.constraint["kind"]]
        params = dict(self.claim.constraint)
        params.setdefault("_recipe", self.claim.recipe)
        return bool(c["fn"]({k: np.asarray(v, dtype=float) for k, v in vars.items()},
                            params))

    def build_scene(self, **vars) -> list[dict]:
        env = _recipe_env(self.claim.recipe, vars)
        s = SCENES[self.claim.scene["kind"]]
        return s["fn"](env, self.claim.scene)

    def certify(self, **exact) -> bool:
        if self.claim.certify is None:
            raise RuntimeError("claim has no exact certifier")
        c = CERTIFIERS[self.claim.certify["kind"]]
        return bool(c["fn"](exact, self.claim.recipe, self.claim.certify))

    def lean_certificate(self, **exact) -> str:
        if self.claim.lean is None:
            raise RuntimeError("claim has no lean certificate hook")
        entry = LEANS[self.claim.lean["kind"]]
        return entry["fn"](exact, self.claim.recipe, self.claim.lean)


@dataclass
class Claim:
    id: str
    title: str
    conjecture: str
    latex: str
    quantifier: str  # "forall" | "exists"
    spaces: dict[str, Space]
    # native engine: recipe of constructions + registry selections
    recipe: list[dict] = field(default_factory=list)
    measure: dict | None = None       # {"kind": ..., ...params}
    constraint: dict | None = None
    certify: dict | None = None
    lean: dict | None = None
    scene: dict | None = None
    # hypotheses: expressions the claim ASSUMES are >= 0. They are part of the
    # statement ("for all positive x"), which is why a proof may use them as
    # ingredients, and why the proved claim must repeat them.
    assume: list[str] = field(default_factory=list)
    lean_statement: str = ""
    notes: str = ""

    def compiled(self):
        if self.measure is None or self.scene is None:
            raise ValueError(f"claim {self.id!r} has no native measure/scene")
        return NativeEngine(self)

    @property
    def domain(self) -> list[FreeVar]:
        """Flat descriptions in the same insertion order as ``spaces``."""
        out = []
        for name, space in self.spaces.items():
            kind = "real"
            if isinstance(space, GraphSpace):
                kind = "graph_iso" if space.up_to_iso else "graph"
            elif isinstance(space, IntBox):
                kind = "int"
            out.append(FreeVar(name=name, shape=list(space.shape),
                               low=float(space.low), high=float(space.high), kind=kind))
        return out

    @property
    def max_coord_dim(self) -> int:
        """Largest trailing dimension across free entities (3 for tetrahedra,
        4 for the 4-simplex claim, 0 for scalars) — the d>3 honesty trigger."""
        dims = [s.shape[-1] if s.shape else 0 for s in self.spaces.values()]
        return max(dims, default=0)

    # -- persistence -----------------------------------------------------------

    def to_json(self) -> dict:
        return {
            "format": CLAIM_FORMAT,
            "id": self.id, "title": self.title, "conjecture": self.conjecture,
            "latex": self.latex, "quantifier": self.quantifier,
            "spaces": [
                {"name": n, "shape": list(s.shape), "low": s.low, "high": s.high,
                 "kind": (("graph_iso" if s.up_to_iso else "graph")
                          if isinstance(s, GraphSpace)
                          else "int" if isinstance(s, IntBox) else "real")}
                for n, s in self.spaces.items()
            ],
            "recipe": self.recipe,
            "measure": self.measure, "constraint": self.constraint,
            "certify": self.certify, "lean": self.lean, "scene": self.scene,
            "assume": list(self.assume),
            "lean_statement": self.lean_statement, "notes": self.notes,
        }

    def save(self, path) -> None:
        Path(path).write_text(json.dumps(self.to_json(), indent=2))

    @classmethod
    def from_json(cls, data: dict) -> "Claim":
        if data.get("format") != CLAIM_FORMAT:
            raise ValueError(f"not a {CLAIM_FORMAT} document")
        raw_spaces = data.get("spaces", [])
        if not isinstance(raw_spaces, list):
            raise ValueError("spaces must be a list")
        spaces: dict[str, Space] = {}
        for s in raw_spaces:
            if not isinstance(s, dict):
                raise ValueError(f"space entry must be an object, got {s!r}")
            name = s.get("name")
            if name in spaces:
                raise ValueError(f"duplicate space name {name!r}")
            raw_shape = s.get("shape")
            if not isinstance(raw_shape, list) or any(
                not isinstance(d, int) or isinstance(d, bool) or d < 0 for d in raw_shape
            ):
                raise ValueError(f"space {name!r} has an invalid shape: {raw_shape!r}")
            shape = tuple(raw_shape)
            kind = s.get("kind", "real")
            if kind in ("graph", "graph_iso"):
                if len(shape) != 2 or shape[0] < 1 or shape[0] != shape[1]:
                    raise ValueError(f"graph space {name!r} needs square shape [n, n]")
                spaces[name] = GraphSpace(
                    n=int(shape[0]), up_to_iso=kind == "graph_iso")
            elif kind == "int":
                low, high = s["low"], s["high"]
                if (
                    isinstance(low, bool) or isinstance(high, bool)
                    or not isinstance(low, (int, float))
                    or not isinstance(high, (int, float))
                    or float(low) != int(low) or float(high) != int(high)
                ):
                    raise ValueError(f"integer space {name!r} needs integer bounds")
                spaces[name] = IntBox(shape=shape, low=int(low), high=int(high))
            elif kind == "real":
                spaces[name] = Box(
                    shape=shape, low=float(s["low"]), high=float(s["high"])
                )
            else:
                raise ValueError(f"space {name!r} has unknown kind {kind!r}")
        return cls(
            id=data["id"], title=data["title"], conjecture=data["conjecture"],
            latex=data["latex"], quantifier=data["quantifier"], spaces=spaces,
            recipe=data.get("recipe") if data.get("recipe") is not None else [],
            measure=data.get("measure"), constraint=data.get("constraint"),
            certify=data.get("certify"), lean=data.get("lean"), scene=data.get("scene"),
            assume=data.get("assume") if data.get("assume") is not None else [],
            lean_statement=data.get("lean_statement", ""), notes=data.get("notes", ""),
        )

    @classmethod
    def load(cls, path) -> "Claim":
        data = json.loads(Path(path).read_text())
        if not isinstance(data, dict) or data.get("format") != CLAIM_FORMAT:
            raise ValueError(
                f"only {CLAIM_FORMAT} documents are supported; executable legacy specs "
                "are refused"
            )
        return require_valid_claim(cls.from_json(data))


# -- validation: the gate for every Claim ------------------------------------

def validate_claim(claim: Claim, samples: int = 8, seed: int = 0) -> list[str]:
    """Check the complete executable Claim contract without minting a verdict."""
    errors: list[str] = []
    if not isinstance(claim.id, str) or len(claim.id) > 80 or not _CLAIM_ID.fullmatch(claim.id):
        errors.append(
            "id must be 1-80 lowercase letters or digits joined by single hyphens"
        )
    for field_name in ("title", "conjecture", "latex"):
        value = getattr(claim, field_name)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field_name} must be a non-empty string")
    if claim.quantifier not in ("forall", "exists"):
        errors.append(f"quantifier must be forall/exists, got {claim.quantifier!r}")
    if not claim.spaces:
        errors.append("claim needs at least one free entity (a Space)")
    for name, space in claim.spaces.items():
        if not isinstance(name, str) or not _ENTITY_NAME.fullmatch(name):
            errors.append(f"space name must be an identifier, got {name!r}")
        if not isinstance(space, Space):
            errors.append(f"space {name!r} is not a Space")
            continue
        if any(not isinstance(d, int) or isinstance(d, bool) or d < 0 for d in space.shape):
            errors.append(f"space {name!r} has an invalid shape {space.shape!r}")
        try:
            low, high = float(space.low), float(space.high)
        except (TypeError, ValueError):
            errors.append(f"space {name!r} bounds must be numbers")
            continue
        if not math.isfinite(low) or not math.isfinite(high):
            errors.append(f"space {name!r} bounds must be finite")
        elif high < low:
            errors.append(f"space {name!r} low ({low}) must be <= high ({high})")

    selections = (
        ("measure", claim.measure, MEASURES, True),
        ("scene", claim.scene, SCENES, True),
        ("constraint", claim.constraint, CONSTRAINTS, False),
        ("certify", claim.certify, CERTIFIERS, False),
        ("lean", claim.lean, LEANS, False),
    )
    for slot, block, registry, required in selections:
        if block is None:
            if required:
                errors.append(f"missing {slot}")
            continue
        if not isinstance(block, dict):
            errors.append(f"{slot} must be an object, got {block!r}")
            continue
        kind = block.get("kind")
        if not isinstance(kind, str) or kind not in registry:
            errors.append(f"unknown {slot} kind: {kind!r}")
            continue
        for param in registry[kind]["params"]:
            if param not in block:
                errors.append(f"{slot} kind {kind!r} needs parameter {param!r}")
    if isinstance(claim.lean, dict):
        theorem = claim.lean.get("theorem")
        if theorem is not None and (
            not isinstance(theorem, str) or not _LEAN_NAME.fullmatch(theorem)
        ):
            errors.append(f"lean theorem must be an identifier, got {theorem!r}")

    known = set(claim.spaces)
    if not isinstance(claim.recipe, list):
        errors.append("recipe must be a list")
        recipe = []
    else:
        recipe = claim.recipe
    for step in recipe:
        if not isinstance(step, dict):
            errors.append(f"recipe step must be an object, got {step!r}")
            continue
        name, ctor, args = step.get("name"), step.get("ctor"), step.get("args")
        if not isinstance(name, str) or not _ENTITY_NAME.fullmatch(name):
            errors.append(f"recipe step name must be an identifier, got {name!r}")
        elif name in known:
            errors.append(f"recipe entity {name!r} is declared more than once")
        if not isinstance(ctor, str) or ctor not in CONSTRUCTORS:
            errors.append(f"unknown constructor {ctor!r}")
            continue
        if not isinstance(args, list):
            errors.append(f"recipe step {name!r}: args must be a list")
            continue
        if len(args) != CONSTRUCTORS[ctor]["arity"]:
            errors.append(
                f"recipe step {name!r}: {ctor} needs {CONSTRUCTORS[ctor]['arity']} "
                f"arguments, got {len(args)}"
            )
        for a in args:
            if not isinstance(a, str) or a not in known:
                errors.append(f"recipe step {name!r}: unknown argument {a!r}")
        if isinstance(name, str) and _ENTITY_NAME.fullmatch(name) and name not in known:
            known.add(name)
    if not isinstance(claim.assume, list):
        errors.append("assume must be a list")
        assumptions = []
    else:
        assumptions = claim.assume
    for src in assumptions:
        try:
            unknown = expr.names(expr.parse(src)) - known
        except (expr.ExprError, TypeError) as e:
            errors.append(f"assumption rejected: {e}")
            continue
        if unknown:
            errors.append(f"assumption reads unknown entities: {sorted(unknown)}")
    if isinstance(claim.measure, dict) and claim.measure.get("kind") == "expr":
        try:
            tree = expr.parse(claim.measure.get("margin"))
        except (expr.ExprError, TypeError) as e:
            errors.append(f"measure expression rejected: {e}")
        else:
            unknown = expr.names(tree) - known
            if unknown:
                errors.append(f"measure expression reads unknown entities: {sorted(unknown)}")
    # Certifying or Lean-stamping a *different* expression than the one measured
    # would prove nothing about this claim: fail closed. This binds EVERY hook
    # that carries a margin, not only `expr` ones. The test used to look at
    # `kind == "expr"`, so a `recipe` Lean hook (which takes a margin too) could
    # name any expression and still upgrade the stamp: setting only
    # lean["margin"] = "1" on a bundled claim passed validation with no errors.
    measured = claim.measure.get("margin") if isinstance(claim.measure, dict) else None
    for slot in ("certify", "lean"):
        block = getattr(claim, slot)
        if not isinstance(block, dict) or block.get("margin") is None:
            continue
        if measured is None:
            errors.append(
                f"{slot} declares a margin but the measure does not, so nothing "
                f"checks that the two describe the same quantity"
            )
        elif block.get("margin") != measured:
            errors.append(
                f"{slot} margin must repeat the measure's margin verbatim"
            )
    if errors:
        return errors

    engine = claim.compiled()
    rng = np.random.default_rng(seed)
    got = 0
    last_vars = None
    for _ in range(samples * 25):
        try:
            vars = {n: s.sample(rng) for n, s in claim.spaces.items()}
            if not engine.valid(**vars):
                continue
        except Exception as e:  # noqa: BLE001
            errors.append(f"constraint raised: {type(e).__name__}: {e}")
            return errors
        try:
            res = engine.check(**vars)
        except Exception as e:  # noqa: BLE001
            errors.append(f"check raised on a valid sample: {type(e).__name__}: {e}")
            return errors
        if res.margin is not None and bool(res.holds) != (res.margin > 0):
            errors.append("margin/holds inconsistency on a sample")
            return errors
        if got == 0:
            try:
                built = engine.build_scene(**vars)
                if not isinstance(built, list) or not built:
                    errors.append("scene builder must return a non-empty list")
            except Exception as e:  # noqa: BLE001
                errors.append(f"scene raised: {type(e).__name__}: {e}")
        got += 1
        last_vars = vars
        if got >= samples:
            break
    if got == 0:
        errors.append("could not draw any valid sample (constraint too strict?)")
    elif engine.has_certify and last_vars is not None:
        try:
            exact = {
                name: claim.spaces[name].exact(value)
                for name, value in last_vars.items()
            }
            engine.certify(**exact)
        except Exception as e:  # noqa: BLE001 - a broken exact hook invalidates the Claim
            errors.append(f"certifier raised: {type(e).__name__}: {e}")
    return errors


def require_valid_claim(claim: Claim, samples: int = 8, seed: int = 0) -> Claim:
    """Return ``claim`` or stop before any execution or artifact is created."""
    errors = validate_claim(claim, samples=samples, seed=seed)
    if errors:
        raise ClaimValidationError(
            f"claim {getattr(claim, 'id', '<unknown>')!r} failed validation:\n- "
            + "\n- ".join(errors)
        )
    return claim
