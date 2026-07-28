"""P1 gate: Space is the input boundary — behavior-identical to the historical
sampler/perturber/enumerator, and dimension-agnostic (d=5 works like d=2)."""
import numpy as np
import pytest

from simagent.core.space import Box, IntBox, sample_vars
from simagent.library import get
from simagent.sandbox.certify import exact_repr, rationalize_array, to_float
from simagent.search import _int_repr, case_count, int_domain_exact


def test_sample_vars_bitwise_matches_historical_formula():
    spec = get("circumcenter-in-triangle")
    a = sample_vars(np.random.default_rng(7), spec)
    rng = np.random.default_rng(7)  # the exact pre-refactor call sequence
    b = {v.name: rng.uniform(v.low, v.high, size=tuple(v.shape)) for v in spec.domain}
    for k in b:
        assert np.array_equal(a[k], b[k]), "Space.sample must not change RNG draws"


def test_intbox_sample_matches_historical_formula():
    a = IntBox(shape=(), low=0, high=200).sample(np.random.default_rng(3))
    b = np.random.default_rng(3).integers(0, 201, size=()).astype(float)
    assert np.array_equal(a, b)


def test_box_is_dimension_agnostic_d5():
    box = Box(shape=(6, 5), low=-2.0, high=2.0)
    rng = np.random.default_rng(0)
    x = box.sample(rng)
    assert x.shape == (6, 5) and box.valid(x)
    y = box.perturb(rng, x, sigma=0.5)
    assert y.shape == (6, 5) and box.valid(y)  # perturb clips to the box


def test_intbox_enumeration_order_and_count():
    ib = IntBox(shape=(2,), low=0, high=2)
    cases = ib.enumerate_cases()
    assert len(cases) == ib.count() == 9
    # historical itertools.product order: last entry varies fastest
    assert np.array_equal(cases[0], [0.0, 0.0])
    assert np.array_equal(cases[1], [0.0, 1.0])
    assert np.array_equal(cases[-1], [2.0, 2.0])
    scalar = IntBox(shape=(), low=1, high=3)
    assert [float(c) for c in scalar.enumerate_cases()] == [1.0, 2.0, 3.0]
    assert IntBox(shape=(), low=5, high=4).count() == 0  # inverted -> empty


def test_case_count_and_int_exact_via_spaces():
    odds = get("sum-of-odds-square")
    assert case_count(odds) == 201
    assert int_domain_exact(odds) is True
    tri = get("circumcenter-in-triangle")
    assert case_count(tri) is None  # continuous domain
    assert int_domain_exact(tri) is False
    big = IntBox(shape=(), low=0, high=2**41)
    assert big.int_exact is False  # beyond the 2^40 exactness guard


def test_rationalize_any_ndim_roundtrip():
    arr3 = np.array([[[0.5, -0.25], [1.0, 0.2]], [[0.75, 0.0], [-1.5, 2.0]]])
    exact = rationalize_array(arr3, max_den=16)
    assert isinstance(exact, list) and len(exact) == 2
    back = np.asarray(to_float(exact), dtype=float)
    assert back.shape == arr3.shape
    assert np.allclose(back, arr3)
    rep = exact_repr(exact)
    assert rep[0][0][0] == "1/2" and rep[1][1][0] == "-3/2"
    # historical ndim<=2 conventions unchanged
    assert rationalize_array(np.array([0.5, 1.5])).shape == (1, 2)
    assert str(rationalize_array(np.float64(0.25))) == "1/4"


def test_int_repr_any_ndim():
    assert _int_repr(np.array(3.0)) == "3"
    assert _int_repr(np.array([1.0, 2.0])) == [["1", "2"]]
    a3 = np.arange(8, dtype=float).reshape(2, 2, 2)
    rep = _int_repr(a3)
    assert rep[1][1] == ["6", "7"]


def test_perturb_matches_historical_refine_move():
    spec = get("circumcenter-in-triangle")
    spaces = spec.spaces
    v = spec.domain[0]
    cur = np.zeros(tuple(v.shape))
    a = spaces[v.name].perturb(np.random.default_rng(11), cur, 0.15)
    rng = np.random.default_rng(11)
    b = np.clip(cur + rng.normal(0.0, 0.15, size=cur.shape), v.low, v.high)
    assert np.array_equal(a, b), "Space.perturb must not change the annealing move"
