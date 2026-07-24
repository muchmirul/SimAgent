"""Discrete spaces: the first object that is not a point in a box.

A combinatorialist's object is a graph, and until now the harness could not
state one at all. These tests check the Space contract, the composable graph
vocabulary, and the known-answer claim that exercises the lot.
"""
import numpy as np
import pytest

from simagent.core.claim import Claim, validate_claim
from simagent.core.derive import CONSTRUCTORS
from simagent.core.space import GraphSpace, spaces_for
from simagent.library import get
from simagent.search import exhaustible, run_exhaustive

C5 = np.array([[0., 1, 0, 0, 1], [1, 0, 1, 0, 0], [0, 1, 0, 1, 0],
               [0, 0, 1, 0, 1], [1, 0, 0, 1, 0]])
K5 = np.ones((5, 5)) - np.eye(5)


def test_graph_space_obeys_the_space_contract():
    g = GraphSpace(n=5)
    rng = np.random.default_rng(0)
    A = g.sample(rng)
    assert g.valid(A) and A.shape == (5, 5)
    assert g.count() == 1 << 10  # full enumeration is the sound default
    cases = g.enumerate_cases()
    assert len(cases) == 1024
    assert all(g.valid(c) for c in cases)
    assert len({c.tobytes() for c in cases}) == 1024, "enumeration must not repeat"
    assert g.int_exact is True


def test_a_move_flips_edges_and_stays_a_graph():
    g = GraphSpace(n=6)
    rng = np.random.default_rng(1)
    A = g.sample(rng)
    cold = g.perturb(rng, A, 0.01)
    assert g.valid(cold)
    assert int(np.abs(cold - A).sum()) == 2, "coldest move flips exactly one edge"
    hot = g.perturb(rng, A, 0.5)
    assert g.valid(hot) and np.abs(hot - A).sum() > 2


def test_graph_constructors_hit_known_values():
    c = CONSTRUCTORS
    assert float(c["edge_count"]["fn"](C5)) == 5.0
    assert float(c["triangle_count"]["fn"](C5)) == 0.0
    assert float(c["edge_count"]["fn"](K5)) == 10.0
    assert float(c["triangle_count"]["fn"](K5)) == 10.0  # C(5,3)
    assert c["degrees"]["fn"](C5).tolist() == [2, 2, 2, 2, 2]


def test_exact_graph_constructors_agree_with_numeric():
    c = CONSTRUCTORS
    for name in ("edge_count", "triangle_count"):
        numeric = float(c[name]["fn"](C5))
        assert float(c[name]["exact"](C5.tolist())) == numeric


def test_graph_space_survives_the_domain_round_trip(tmp_path):
    """spec.domain rebuilds Spaces from name/shape/kind, so a graph that comes
    back as a plain integer box would silently lose its symmetry."""
    claim = get("graph-triangle-threshold")
    assert isinstance(spaces_for(claim)["G"], GraphSpace)
    path = tmp_path / "c.json"
    claim.save(path)
    again = Claim.load(path)
    assert isinstance(again.spaces["G"], GraphSpace)
    assert validate_claim(again) == []


def test_graph_claim_is_a_known_answer():
    """False: C5 has five edges and no triangle. K5 obviously has both."""
    claim = get("graph-triangle-threshold")
    comp = claim.compiled()
    assert comp.valid(G=C5) and comp.check(G=C5).holds is False
    assert comp.check(G=K5).holds is True

    assert exhaustible(claim), "1024 graphs must be enumerable"
    report = run_exhaustive(claim)
    assert report.verdict == "counterexample"
    assert report.certified is True
    A = np.array(report.witness["G"])
    assert A.sum() // 2 >= 5 and np.trace(A @ A @ A) == 0


def test_graph_scene_draws_the_edges():
    claim = get("graph-triangle-threshold")
    prims = claim.compiled().build_scene(G=C5)
    segments = [p for p in prims if p.get("type") == "segments"]
    assert segments, "a graph with edges must render them"
    assert any(p.get("type") == "points" for p in prims)


def test_enumeration_is_reduced_by_symmetry():
    """Vertex names carry no mathematical content, so relabellings are the same
    object. The class counts are the known sequence (OEIS A000088), which is a
    sharp check that the reduction is exact: neither lossy nor redundant."""
    known = {2: 2, 3: 4, 4: 11, 5: 34, 6: 156}
    for n, classes in known.items():
        g = GraphSpace(n=n, up_to_iso=True)
        assert len(g.enumerate_cases()) == classes, n
        assert g.count() == classes, n
        # and it is OPT-IN: the sound default still checks every labelling
        assert GraphSpace(n=n).count() == 1 << (n * (n - 1) // 2), n


def test_reduction_loses_no_graph():
    """Completeness: every labelled graph must be isomorphic to exactly one
    representative, or the enumeration would silently skip cases."""
    import itertools

    g = GraphSpace(n=4, up_to_iso=True)
    reps = g.enumerate_cases()
    perms = list(itertools.permutations(range(4)))
    covered = set()
    for A in reps:
        for p in perms:
            covered.add(A[np.ix_(p, p)].astype(np.int8).tobytes())
    pairs = [(i, j) for i in range(4) for j in range(i + 1, 4)]
    for mask in range(1 << len(pairs)):
        B = np.zeros((4, 4))
        for b, (i, j) in enumerate(pairs):
            B[i, j] = B[j, i] = float((mask >> b) & 1)
        assert B.astype(np.int8).tobytes() in covered, f"missed graph {mask}"


def test_symmetry_reduction_refuses_a_label_sensitive_claim():
    """The reduction is sound only for a property that cannot see labels. A
    claim about vertex 0 and vertex 1 by name must not be reduced, and saying
    so is the harness's job - silently skipping cases would be a false proof."""
    import dataclasses

    from simagent.search import run_exhaustive

    claim = get("graph-triangle-threshold")
    # "is there an edge between vertices 0 and 1" is about the LABELS
    label_sensitive = dataclasses.replace(
        claim,
        measure={"kind": "expr", "margin": "G[0][1] - 0.5"},
        certify=None, constraint=None,
    )
    with pytest.raises(ValueError, match="distinguishes relabelled copies"):
        run_exhaustive(label_sensitive)
