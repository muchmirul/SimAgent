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

lean = pytest.mark.skipif(not __import__("simagent").lean_check.lean_available(),
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
