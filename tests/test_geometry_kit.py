"""The geometry kit: named constructors, their exact counterparts, and the
recipe replay that lets a margin read a DERIVED entity and still certify.

Each constructor is checked against an independently-known value, and each
exact counterpart against its own numeric one — a constructor whose exact
twin disagrees would certify the wrong thing.
"""
import numpy as np
import pytest
import sympy as sp

from simagent.core import expr
from simagent.core.claim import _exact_recipe_env, validate_claim
from simagent.core.derive import CONSTRUCTORS
from simagent.library import get
from simagent.sandbox import certify as certify_mod
from simagent.search import run_search

# a 3-4-5 right triangle: every classical centre is known by hand
RIGHT = np.array([[0.0, 0.0], [4.0, 0.0], [0.0, 3.0]])


def test_every_constructor_has_an_exact_counterpart():
    missing = [k for k, v in CONSTRUCTORS.items() if v.get("exact") is None]
    assert missing == [], f"no exact replay for {missing}"


def test_geometry_constructors_hit_known_values():
    c = CONSTRUCTORS
    # right angle at the origin, so the orthocenter IS that vertex
    assert c["orthocenter"]["fn"](RIGHT) == pytest.approx([0.0, 0.0])
    # circumcentre of a right triangle is the hypotenuse midpoint
    assert c["circumcenter"]["fn"](RIGHT) == pytest.approx([2.0, 1.5])
    # incircle radius of a 3-4-5 triangle is 1, so the incentre is (1, 1)
    assert c["incenter"]["fn"](RIGHT) == pytest.approx([1.0, 1.0])
    assert float(c["distance_sq"]["fn"](RIGHT[1], RIGHT[2])) == pytest.approx(25.0)
    assert float(c["cross2"]["fn"](RIGHT[1], RIGHT[2])) == pytest.approx(12.0)
    assert float(c["dot"]["fn"](RIGHT[1], RIGHT[2])) == pytest.approx(0.0)
    assert c["foot"]["fn"](np.array([2.0, 5.0]), RIGHT[0], RIGHT[1]) == pytest.approx([2.0, 0.0])
    assert c["reflect"]["fn"](np.array([2.0, 5.0]), RIGHT[0], RIGHT[1]) == pytest.approx([2.0, -5.0])
    assert c["intersect_lines"]["fn"](
        np.array([0.0, 0.0]), np.array([2.0, 2.0]),
        np.array([0.0, 2.0]), np.array([2.0, 0.0]),
    ) == pytest.approx([1.0, 1.0])


GRAPH_CTORS = {"degrees", "edge_count", "triangle_count"}


@pytest.mark.parametrize("name", sorted(set(CONSTRUCTORS) - GRAPH_CTORS))
def test_exact_counterpart_agrees_with_the_numeric_one(name):
    """Rational inputs, so the two paths must agree to the last bit.

    Graph constructors take an adjacency matrix rather than a point set, so
    they are checked against known graphs in test_graph_space.py instead."""
    entry = CONSTRUCTORS[name]
    P, Q = np.array([1.0, 2.0]), np.array([3.0, -1.0])
    args = {
        1: [RIGHT],
        2: [P, Q] if name not in ("vertex",) else [RIGHT, 1.0],
        3: [P, RIGHT[0], RIGHT[1]],
        4: [RIGHT[0], RIGHT[1], P, Q],
    }[entry["arity"]]
    if name == "barycentric":
        args = [RIGHT, np.array([1.0, 1.0])]
    numeric = np.asarray(entry["fn"](*args), dtype=float).ravel()
    exact = entry["exact"](*[a.tolist() if isinstance(a, np.ndarray) else a for a in args])
    flat = np.array([float(x) for x in np.array(exact, dtype=object).ravel()])
    assert flat == pytest.approx(numeric)


def test_parallel_lines_and_degenerate_input_raise():
    c = CONSTRUCTORS
    with pytest.raises(ValueError):
        c["intersect_lines"]["fn"](np.array([0.0, 0.0]), np.array([1.0, 0.0]),
                                   np.array([0.0, 1.0]), np.array([1.0, 1.0]))
    with pytest.raises(ValueError):
        c["foot"]["fn"](np.array([1.0, 1.0]), np.array([0.0, 0.0]), np.array([0.0, 0.0]))
    with pytest.raises(ValueError):
        c["orthocenter"]["fn"](np.array([[0.0, 0.0], [1.0, 0.0]]))


def test_recipe_replays_in_exact_arithmetic():
    claim = get("orthocenter-in-triangle")
    exact_vars = {"T": certify_mod.rationalize_array(RIGHT)}
    env = _exact_recipe_env(claim.recipe, exact_vars)
    # right angle at vertex 0 puts the orthocenter exactly on it: weights (1,0,0)
    assert [sp.nsimplify(w) for w in env["W"]] == [1, 0, 0]
    assert all(isinstance(sp.nsimplify(v), sp.Rational) for v in env["H"])


def test_orthocenter_claim_is_a_known_answer():
    """Ground truth: the orthocenter is inside iff the triangle is acute."""
    claim = get("orthocenter-in-triangle")
    assert validate_claim(claim) == []
    comp = claim.compiled()
    acute = np.array([[-1.0, 0.0], [1.0, 0.0], [0.0, 1.4]])
    obtuse = np.array([[-1.0, 0.0], [1.0, 0.0], [0.0, 0.3]])
    assert comp.check(T=acute).holds is True
    assert comp.check(T=obtuse).holds is False

    report = run_search(claim, trials=400, seed=5)
    assert report.verdict == "counterexample"
    assert report.certified is True, "exact replay of the recipe must certify"


def test_lean_refuses_a_derived_entity_as_an_atom():
    """A certificate over a computed number would prove nothing about how it
    was computed, so the encoder must refuse rather than downgrade quietly."""
    claim = get("orthocenter-in-triangle")
    env = _exact_recipe_env(claim.recipe, {"T": certify_mod.rationalize_array(RIGHT)})
    with pytest.raises(expr.ExprError):
        expr.lean_form(expr.parse("min(W)"), env, free={"T"})


# -- Lean stamps for recipe claims --------------------------------------------

# Imported by name, not via __import__("simagent").lean_check: the attribute
# form only resolves once some OTHER module has imported the submodule, so this
# file could not be collected on its own and passed only by running order.
from simagent import lean_check  # noqa: E402

lean = pytest.mark.skipif(not lean_check.lean_available(),
                          reason="no Lean toolchain")


@lean
def test_recipe_certificate_pins_the_construction(tmp_path):
    """A certificate over a derived VALUE proves nothing about how it was
    built. This one states the equations that define the orthocentre and the
    barycentric weights, so the kernel checks the construction itself."""
    from simagent.pipeline import run_problem

    out = run_problem(get("orthocenter-in-triangle"), tmp_path, trials=400,
                      seed=5, render_manim=False)
    assert out.proof.verified_by == "sandbox+lean"
    assert out.proof.lean_report["axiom_clean"] is True
    source = (tmp_path / "certificate.lean").read_text()
    # two altitude conditions define H; sum-to-one plus recombination define W
    assert source.count("qeq") >= 5
    assert "edgeDet" in source, "the construction must be shown to be unique"


@lean
def test_a_tampered_recipe_certificate_is_rejected():
    """If the certificate cannot fail, it proves nothing. Move the orthocentre
    off the altitudes and the kernel must refuse."""
    from simagent import lean_check
    from simagent.core.claim import CLAIM_FORMAT  # noqa: F401  (import guard)
    from simagent.core.claim import _lean_recipe

    claim = get("orthocenter-in-triangle")
    obtuse = np.array([[-1.0, 0.0], [1.0, 0.0], [0.0, 0.3]])
    exact = {"T": certify_mod.rationalize_array(obtuse)}
    params = dict(claim.lean)
    good = _lean_recipe(exact, claim.recipe, params)
    assert lean_check.check_source(good)["ok"] is True
    # shift H by one: it is no longer the orthocentre, so the pins must fail
    bad = good.replace("def H_0 : Q := ", "def H_0 : Q := qadd ((1 : Int), 1) ", 1)
    assert lean_check.check_source(bad)["ok"] is False


def test_a_constructor_without_pins_refuses_a_certificate():
    """Fail closed: a construction the kernel cannot verify must not be
    smuggled in as a bare number."""
    import dataclasses

    from simagent.core.claim import _lean_recipe

    claim = get("orthocenter-in-triangle")
    unpinnable = dataclasses.replace(
        claim, recipe=[{"name": "H", "ctor": "incenter", "args": ["T"]},
                       {"name": "W", "ctor": "barycentric", "args": ["T", "H"]}])
    exact = {"T": certify_mod.rationalize_array(RIGHT)}
    with pytest.raises(ValueError, match="no Lean pinning equations"):
        _lean_recipe(exact, unpinnable.recipe, dict(claim.lean))


# -- pins for the rest of the kit ---------------------------------------------
# Before these, 5 of 19 constructors could be pinned, so a claim built from a
# foot, a reflection or a line intersection topped out at `sandbox`: correct,
# but capped. Each case below is a real certificate the Lean kernel accepts,
# and each is tampered afterwards, because a certificate that cannot fail
# proves nothing.

def _probe_claim(name, spaces, recipe, margin, of=None):
    from simagent.core.claim import Claim
    from simagent.core.space import Box

    lean = {"kind": "recipe", "margin": margin,
            "theorem": f"{name}_probe", "title": f"{name} pin probe"}
    if of is not None:
        lean["of"] = of
    return Claim(
        id=f"{name.replace('_', '-')}-probe", title="probe", conjecture="probe",
        latex="probe", quantifier="forall", spaces=spaces, recipe=recipe,
        measure={"kind": "expr", "margin": margin},
        certify={"kind": "expr", "margin": margin}, lean=lean,
        scene={"kind": "point", "of": next(iter(spaces))},
    )


def _pt(*xy):
    return [sp.Rational(v) for v in xy]


def _vec_space():
    from simagent.core.space import Box
    return Box(shape=(2,), low=-6.0, high=6.0)


# name, extra entities, recipe step, margin, exact values, `of`
PIN_CASES = [
    ("sub", ["A", "B"], {"name": "D", "ctor": "sub", "args": ["A", "B"]}, "D[0]",
     {"A": _pt(1, 2), "B": _pt(4, 6)}, None),
    ("dot", ["A", "B"], {"name": "S", "ctor": "dot", "args": ["A", "B"]}, "S",
     {"A": _pt(1, 2), "B": _pt(3, -5)}, None),
    ("cross2", ["A", "B"], {"name": "S", "ctor": "cross2", "args": ["A", "B"]}, "S",
     {"A": _pt(1, 2), "B": _pt(3, -5)}, None),
    ("distance_sq", ["A", "B"],
     {"name": "S", "ctor": "distance_sq", "args": ["A", "B"]}, "S",
     {"A": _pt(1, 2), "B": _pt(3, 5)}, None),
    ("segment", ["A", "B"],
     {"name": "S", "ctor": "segment", "args": ["A", "B"]}, "S[0][1]",
     {"A": _pt(1, 2), "B": _pt(3, 5)}, None),
    ("foot", ["A", "B", "P"],
     {"name": "F", "ctor": "foot", "args": ["P", "A", "B"]}, "F[1]",
     {"A": _pt(0, 0), "B": _pt(2, -2), "P": _pt(2, 0)}, None),
    ("reflect", ["A", "B", "P"],
     {"name": "F", "ctor": "reflect", "args": ["P", "A", "B"]}, "F[1]",
     {"A": _pt(0, 0), "B": _pt(2, 0), "P": _pt(1, 3)}, None),
    ("intersect_lines", ["A", "B", "C", "D"],
     {"name": "X", "ctor": "intersect_lines", "args": ["A", "B", "C", "D"]},
     "X[1]",
     {"A": _pt(0, -2), "B": _pt(4, -2), "C": _pt(1, -5), "D": _pt(1, 5)}, None),
]


@lean
@pytest.mark.parametrize("name, ents, step, margin, exact, of", PIN_CASES)
def test_every_pinned_constructor_reaches_the_lean_kernel(
        name, ents, step, margin, exact, of):
    import re

    from simagent import lean_check

    claim = _probe_claim(name, {e: _vec_space() for e in ents}, [step], margin, of)
    assert validate_claim(claim) == []
    src = claim.compiled().lean_certificate(**exact)
    result = lean_check.check_source(src)
    assert result["ok"] and result["axiom_clean"], result.get("output")

    # teeth: move the derived value and the pins must stop holding
    hit = re.search(rf"^def ({step['name']}(?:_\d+)*) : Q := "
                    r"\(\((-?\d+) : Int\), (\d+)\)$", src, re.M)
    assert hit, "no derived atom to tamper with"
    tampered = src.replace(
        hit.group(0),
        f"def {hit.group(1)} : Q := (({int(hit.group(2)) + 7} : Int), {hit.group(3)})")
    assert lean_check.check_source(tampered)["ok"] is False


@lean
def test_simplex_volume_is_pinned_to_its_determinant():
    from simagent.core.space import Box
    from simagent import lean_check

    claim = _probe_claim(
        "simplex_volume", {"T": Box(shape=(3, 2), low=-6.0, high=6.0)},
        [{"name": "V", "ctor": "simplex_volume", "args": ["T"]}], "V", of="T")
    exact = {"T": [_pt(0, 0), _pt(2, 0), _pt(0, 2)]}
    result = lean_check.check_source(claim.compiled().lean_certificate(**exact))
    assert result["ok"] and result["axiom_clean"]


def test_a_line_pin_states_that_the_line_exists():
    """A and B coinciding makes 'F is on line AB, perpendicular to it' true of
    EVERY point. Without the nondegeneracy conjunct the certificate would hold
    while establishing nothing, which is the fail-open this guards."""
    from simagent.sandbox import leangen

    pins = leangen.RECIPE_PINS["foot"](["F_0", "F_1"], ["P_0", "P_1"],
                                       ["A_0", "A_1"], ["B_0", "B_1"])
    assert any(p.startswith("¬ qeq") for p in pins), pins
    lines = leangen.RECIPE_PINS["intersect_lines"](
        ["X_0", "X_1"], ["A_0", "A_1"], ["B_0", "B_1"],
        ["C_0", "C_1"], ["D_0", "D_1"])
    assert any(p.startswith("¬ qeq") for p in lines), lines


def test_a_simplex_construction_still_demands_its_point_set():
    """`of` became optional so claims with no simplex can be certified. A
    circumcenter equidistant from three COLLINEAR points is not unique, so for
    those constructions the point set must still be named."""
    import dataclasses

    from simagent.core.claim import _lean_recipe

    claim = get("orthocenter-in-triangle")
    params = {k: v for k, v in claim.lean.items() if k != "of"}
    exact = {"T": certify_mod.rationalize_array(RIGHT)}
    with pytest.raises(ValueError, match="nondegenerate"):
        _lean_recipe(exact, claim.recipe, params)


def test_an_unpinnable_constructor_says_why():
    """Three different walls hide behind 'no pin': permanent mathematics, a
    missing encoding, and a limit of this term language. A reader who cannot
    tell them apart cannot tell a gap worth fixing from one that is not."""
    from simagent.sandbox import leangen

    assert "square roots" in leangen.UNPINNABLE["incenter"]
    assert set(leangen.UNPINNABLE) & {"incenter", "vertex"}
    assert not set(leangen.UNPINNABLE) & set(leangen.RECIPE_PINS)
