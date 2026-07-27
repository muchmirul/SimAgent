"""Claim — atom #6 (hypothesis under test), with the native engine (P5).

A Claim = quantifier + free Spaces + a recipe of constructions + a
distinguished measure, all drawn from CLOSED REGISTRIES — no exec'd code
anywhere on the native path (decision D3: typed vocabulary replaces
LLM-emitted code strings; AlphaGeometry-proven). A native Claim is
"spec-like": it duck-types every surface the search/proof/answer machinery
consumes (`domain`, `quantifier`, `compiled()`, `save()`, …), so the truth
layer runs on Claims unchanged.

Engines:
- **native**: recipe + registry keys (bundled library, LLM formalizer output)
- **legacy**: wraps a historical ProblemSpec via `claim_from_spec`
  (kept one release for old disk specs; the exec path is deprecated)

Only the truth layer decides claims; a Claim carries no verdict state.
"""
from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..sandbox import geometry, leangen, scene
from ..sandbox import certify as certify_mod
from . import expr
from .derive import CONSTRUCTORS
from .space import Box, GraphSpace, IntBox, Space, spaces_for

CLAIM_FORMAT = "claim/1"


@dataclass(frozen=True)
class FreeVar:
    """Duck-typed VarSpec: what samplers/search need to know about a free
    entity (core cannot import spec.py — layering)."""

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
    prims.append(scene.points(P, color=scene.INK, radius=0.05))
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
        scene.points(Pts, color=scene.INK, radius=0.04),
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
        scene.points(P, color=scene.HALO, radius=0.06, name=params["of"]),
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

    def check(self, **vars) -> NativeCheckResult:
        env = _recipe_env(self.claim.recipe, vars)
        m = MEASURES[self.claim.measure["kind"]]
        res = m["fn"](env, self.claim.recipe, self.claim.measure)
        if res.margin is not None and bool(res.holds) != (res.margin > 0):
            raise ValueError("measure inconsistency: holds must equal margin > 0")
        return res

    def valid(self, **vars) -> bool:
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
    # legacy engine (adapter): the wrapped spec
    _spec: object | None = None

    # -- engines -------------------------------------------------------------

    @property
    def is_native(self) -> bool:
        return self._spec is None

    def to_speclike(self):
        """What search/proof machinery consumes. Native claims ARE spec-like;
        legacy claims defer to their wrapped spec."""
        return self if self._spec is None else self._spec

    def compiled(self):
        if self._spec is not None:
            return self._spec.compiled()
        if self.measure is None or self.scene is None:
            raise ValueError(f"claim {self.id!r} has no native measure/scene")
        return NativeEngine(self)

    # -- spec-like surface (duck-typed VarSpec list) ---------------------------

    @property
    def domain(self) -> list[FreeVar]:
        if self._spec is not None:
            return self._spec.domain
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
        if self._spec is not None:
            return self._spec.to_json()
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
        spaces: dict[str, Space] = {}
        for s in data["spaces"]:
            shape = tuple(s["shape"])
            if s.get("kind") in ("graph", "graph_iso"):
                spaces[s["name"]] = GraphSpace(
                    n=int(shape[0]), up_to_iso=s.get("kind") == "graph_iso")
            elif s.get("kind") == "int":
                spaces[s["name"]] = IntBox(shape=shape, low=int(s["low"]), high=int(s["high"]))
            else:
                spaces[s["name"]] = Box(shape=shape, low=float(s["low"]), high=float(s["high"]))
        return cls(
            id=data["id"], title=data["title"], conjecture=data["conjecture"],
            latex=data["latex"], quantifier=data["quantifier"], spaces=spaces,
            recipe=list(data.get("recipe") or []),
            measure=data.get("measure"), constraint=data.get("constraint"),
            certify=data.get("certify"), lean=data.get("lean"), scene=data.get("scene"),
            assume=list(data.get("assume") or []),
            lean_statement=data.get("lean_statement", ""), notes=data.get("notes", ""),
        )

    @classmethod
    def load(cls, path) -> "Claim":
        return cls.from_json(json.loads(Path(path).read_text()))


def claim_from_spec(spec) -> Claim:
    """Adapter: run any historical ProblemSpec as a Claim (legacy engine)."""
    return Claim(
        id=spec.id,
        title=spec.title,
        conjecture=spec.conjecture,
        latex=spec.latex,
        quantifier=spec.quantifier,
        spaces=spaces_for(spec),
        _spec=spec,
    )


# -- validation (the gate for LLM-formalized claims) --------------------------

def validate_claim(claim: Claim, samples: int = 8, seed: int = 0) -> list[str]:
    """Sandbox-check a native claim: registry keys exist, the recipe resolves,
    margin/holds are consistent on real samples, the scene renders. Mirrors
    the historical validate_spec contract — the LLM's output passes this gate
    or is sent back for repair."""
    errors: list[str] = []
    if claim.quantifier not in ("forall", "exists"):
        errors.append(f"quantifier must be forall/exists, got {claim.quantifier!r}")
    if not claim.spaces:
        errors.append("claim needs at least one free entity (a Space)")
    if claim.measure is None or claim.measure.get("kind") not in MEASURES:
        errors.append(f"unknown or missing measure: {claim.measure!r}")
    if claim.scene is None or claim.scene.get("kind") not in SCENES:
        errors.append(f"unknown or missing scene: {claim.scene!r}")
    if claim.constraint is not None and claim.constraint.get("kind") not in CONSTRAINTS:
        errors.append(f"unknown constraint: {claim.constraint!r}")
    if claim.certify is not None and claim.certify.get("kind") not in CERTIFIERS:
        errors.append(f"unknown certifier: {claim.certify!r}")
    if claim.lean is not None and claim.lean.get("kind") not in LEANS:
        errors.append(f"unknown lean hook: {claim.lean!r}")
    known = set(claim.spaces)
    for step in claim.recipe:
        if step.get("ctor") not in CONSTRUCTORS:
            errors.append(f"unknown constructor {step.get('ctor')!r}")
            continue
        for a in step.get("args", ()):
            if a not in known:
                errors.append(f"recipe step {step.get('name')!r}: unknown argument {a!r}")
        known.add(step.get("name"))
    for src in claim.assume:
        try:
            unknown = expr.names(expr.parse(src)) - known
        except expr.ExprError as e:
            errors.append(f"assumption rejected: {e}")
            continue
        if unknown:
            errors.append(f"assumption reads unknown entities: {sorted(unknown)}")
    if claim.measure is not None and claim.measure.get("kind") == "expr":
        try:
            tree = expr.parse(claim.measure.get("margin"))
        except expr.ExprError as e:
            errors.append(f"measure expression rejected: {e}")
        else:
            unknown = expr.names(tree) - known
            if unknown:
                errors.append(f"measure expression reads unknown entities: {sorted(unknown)}")
        # Certifying or Lean-stamping a *different* expression than the one
        # measured would prove nothing about this claim: fail closed.
        for slot in ("certify", "lean"):
            block = getattr(claim, slot)
            if block is not None and block.get("kind") == "expr":
                if block.get("margin") != claim.measure.get("margin"):
                    errors.append(
                        f"{slot} margin must repeat the measure's margin verbatim"
                    )
    if errors:
        return errors

    engine = claim.compiled()
    rng = np.random.default_rng(seed)
    got = 0
    for _ in range(samples * 25):
        vars = {n: s.sample(rng) for n, s in claim.spaces.items()}
        try:
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
                if not engine.build_scene(**vars):
                    errors.append("scene builder returned an empty scene")
            except Exception as e:  # noqa: BLE001
                errors.append(f"scene raised: {type(e).__name__}: {e}")
        got += 1
        if got >= samples:
            break
    if got == 0:
        errors.append("could not draw any valid sample (constraint too strict?)")
    return errors
