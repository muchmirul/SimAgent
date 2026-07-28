"""Euler's polyhedron formula V - E + F = 2 on random convex hulls — TRUE, so
this exercises the evidence path: the search fails to falsify, and the answer
honestly reports accumulated evidence plus a formalization skeleton. Native
claim: discrete measure over the hull counts, no exec'd code."""
from ..core.claim import Claim
from ..core.space import Box

CLAIM = Claim(
    id="euler-characteristic-hull",
    title="Euler characteristic of convex polyhedra (V - E + F = 2)",
    conjecture=(
        "For the boundary of the convex hull of any finite set of points in "
        "general position in R^3, the vertex, edge and face counts satisfy "
        "V - E + F = 2."
    ),
    latex=(
        r"\forall\, P \subset \mathbb{R}^3 \text{ finite, in general position:}\quad "
        r"V(\mathrm{conv}\,P) - E(\mathrm{conv}\,P) + F(\mathrm{conv}\,P) = 2"
    ),
    quantifier="forall",
    spaces={"P": Box(shape=(10, 3), low=-1.0, high=1.0)},
    recipe=[],
    measure={"kind": "euler_characteristic", "of": "P"},
    constraint={"kind": "hull_valid", "of": "P"},
    certify=None,
    lean=None,
    scene={"kind": "hull3d", "of": "P"},
    lean_statement=(
        "-- No off-the-shelf Mathlib statement; Euler's polyhedron formula for\n"
        "-- convex polytopes is itself a formalization target.\n"
        "True"
    ),
    notes=(
        "True (Euler, 1758). Discrete check (no margin): the search can only "
        "accumulate evidence, never a proof — the honest output is "
        "'no counterexample found' plus a proof obligation."
    ),
)
