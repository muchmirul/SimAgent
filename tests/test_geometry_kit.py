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
