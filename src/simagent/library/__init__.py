"""Bundled native Claims — runnable offline, known-answer tests for the whole
machine, and few-shot examples for the LLM formalizer.

Three deliberately false classics (the machine disproves them with certified
rational counterexamples — in ℝ², ℝ³, and ℝ⁴), one true invariant (the
evidence path), and one exhaustion-provable arithmetic identity. Zero exec'd
code strings anywhere: every claim is recipe + registry keys (decision D3).
"""
from __future__ import annotations

from ..core.claim import Claim
from . import (
    circumcenter_4simplex,
    conditional_cubic,
    circumcenter_tetrahedron,
    circumcenter_triangle,
    euler_polyhedron,
    graph_triangle,
    orthocenter_triangle,
    positive_quadratic,
    sum_of_odds,
    sum_of_squares,
)

_MODULES = [
    circumcenter_triangle,
    circumcenter_tetrahedron,
    circumcenter_4simplex,
    orthocenter_triangle,
    euler_polyhedron,
    sum_of_odds,
    sum_of_squares,
    positive_quadratic,
    conditional_cubic,
    graph_triangle,
]

REGISTRY: dict[str, Claim] = {m.CLAIM.id: m.CLAIM for m in _MODULES}


def get(problem_id: str) -> Claim:
    if problem_id not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        raise KeyError(f"unknown problem {problem_id!r}; bundled problems: {known}")
    return REGISTRY[problem_id]


def all_specs() -> list[Claim]:
    return list(REGISTRY.values())


def is_bundled(spec) -> bool:
    """True only for the in-process bundled claim objects (reviewed, trusted).

    Identity, not id-string: a disk-loaded claim carrying a bundled id is a
    different object and is correctly treated as untrusted.
    """
    return REGISTRY.get(spec.id) is spec
