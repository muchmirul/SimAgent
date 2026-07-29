"""Ground truth: FALSE — the orthocenter escapes every obtuse triangle.

The altitudes of an obtuse triangle meet outside it (the orthocenter is
inside exactly when the triangle is acute), so any obtuse triangle is a
counterexample.

This is the known-answer test for the GEOMETRY KIT: the margin reads a
DERIVED entity (`min(W)`, the smallest barycentric weight of a constructed
point), which means certification has to replay the whole recipe -
orthocenter, then barycentric - in exact rational arithmetic. Lean may only
take free variables as atoms, so the certificate PINS each construction to
its defining equations: without that, a certificate over a derived value
would check a bare number and prove nothing about how it was built. With the
pins the verdict reaches "sandbox+lean".
"""
from ..core.claim import Claim
from ..core.space import Box

MARGIN = "min(W)"

CLAIM = Claim(
    id="orthocenter-in-triangle",
    title="Orthocenter lies inside every triangle",
    conjecture=(
        "For every (nondegenerate) triangle in the plane, the orthocenter - "
        "the common point of the three altitudes - lies in the interior of "
        "the triangle."
    ),
    latex=(
        r"\forall\, A,B,C \in \mathbb{R}^2 \text{ affinely independent},\quad "
        r"H(A,B,C) \in \operatorname{int}\,\triangle ABC"
    ),
    quantifier="forall",
    spaces={"T": Box(shape=(3, 2), low=-1.2, high=1.2)},
    recipe=[
        {"name": "H", "ctor": "orthocenter", "args": ["T"]},
        {"name": "W", "ctor": "barycentric", "args": ["T", "H"]},
    ],
    measure={"kind": "expr", "margin": MARGIN},
    constraint={"kind": "min_volume", "of": "T", "threshold": 0.05},
    certify={"kind": "expr", "margin": MARGIN},
    lean={
        "kind": "recipe",
        "margin": MARGIN,
        "of": "T",
        "theorem": "orthocenter_in_triangle_disproof_witness",
        "title": (
            "Witness triangle whose orthocentre lies outside it "
            "(disproves: the orthocentre lies inside every triangle)"
        ),
    },
    scene={"kind": "simplex", "of": "T", "center": "H", "weights": "W",
           "circle": False},
    lean_statement=(
        "theorem orthocenter_in_triangle\n"
        "    (A B C : EuclideanSpace ℝ (Fin 2)) (h : AffineIndependent ℝ ![A, B, C]) :\n"
        "    orthocenter A B C ∈ interior (convexHull ℝ {A, B, C}) := by\n"
        "  sorry"
    ),
    notes=(
        "False: the orthocenter lies inside iff the triangle is acute. Any "
        "obtuse triangle is a counterexample (at a right angle it sits on a "
        "vertex)."
    ),
)
