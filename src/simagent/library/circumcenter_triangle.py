"""Ground truth: FALSE — the circumcenter escapes every obtuse triangle
(Thales: it lies inside iff the triangle is acute). The search finds an
obtuse triangle, exact rationals certify it, Lean kernel-checks the
certificate. Native claim: no exec'd code — recipe + registries only.
This claim doubles as the LLM formalizer's few-shot example."""
from ..core.claim import Claim
from ..core.space import Box

CLAIM = Claim(
    id="circumcenter-in-triangle",
    title="Circumcenter lies inside every triangle",
    conjecture=(
        "For every (nondegenerate) triangle in the plane, the circumcenter "
        "lies in the interior of the triangle."
    ),
    latex=(
        r"\forall\, A,B,C \in \mathbb{R}^2 \text{ affinely independent},\quad "
        r"O(A,B,C) \in \operatorname{int}\,\triangle ABC"
    ),
    quantifier="forall",
    spaces={"T": Box(shape=(3, 2), low=-1.2, high=1.2)},
    recipe=[
        {"name": "circumcenter", "ctor": "circumcenter", "args": ["T"]},
        {"name": "barycentric", "ctor": "barycentric", "args": ["T", "circumcenter"]},
    ],
    measure={"kind": "min_coord", "of": "barycentric"},
    constraint={"kind": "min_volume", "of": "T", "threshold": 0.05},
    certify={"kind": "simplex_circumcenter_inside", "of": "T"},
    lean={
        "kind": "simplex_circumcenter",
        "of": "T",
        "theorem": "circumcenter_in_triangle_disproof_witness",
        "title": (
            "Witness triangle whose circumcenter lies outside it "
            "(disproves: the circumcenter lies inside every triangle)"
        ),
    },
    scene={"kind": "simplex", "of": "T", "center": "circumcenter", "weights": "barycentric"},
    lean_statement=(
        "theorem circumcenter_in_triangle\n"
        "    (T : Affine.Simplex ℝ (EuclideanSpace ℝ (Fin 2)) 2) :\n"
        "    T.circumcenter ∈ interior (convexHull ℝ (Set.range T.points)) := by\n"
        "  sorry"
    ),
    notes=(
        "False: the circumcenter lies inside iff the triangle is acute "
        "(Thales). Any obtuse triangle is a counterexample."
    ),
)
