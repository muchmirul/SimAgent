"""Ground truth: FALSE — flat ("sliver") tetrahedra push the circumsphere's
center outside the hull. Same recipe as the triangle claim, one dimension up:
the ONLY difference is the Space's shape — the point of the dimension-blind
core."""
from ..core.claim import Claim
from ..core.space import Box

CLAIM = Claim(
    id="circumcenter-in-tetrahedron",
    title="Circumcenter lies inside every tetrahedron",
    conjecture=(
        "For every (nondegenerate) tetrahedron in space, the center of its "
        "circumscribed sphere lies in the interior of the tetrahedron."
    ),
    latex=(
        r"\forall\, A,B,C,D \in \mathbb{R}^3 \text{ affinely independent},\quad "
        r"O(A,B,C,D) \in \operatorname{int}\,\mathrm{conv}\{A,B,C,D\}"
    ),
    quantifier="forall",
    spaces={"T": Box(shape=(4, 3), low=-1.2, high=1.2)},
    recipe=[
        {"name": "circumcenter", "ctor": "circumcenter", "args": ["T"]},
        {"name": "barycentric", "ctor": "barycentric", "args": ["T", "circumcenter"]},
    ],
    measure={"kind": "min_coord", "of": "barycentric"},
    constraint={"kind": "min_volume", "of": "T", "threshold": 0.02},
    certify={"kind": "simplex_circumcenter_inside", "of": "T"},
    lean={
        "kind": "simplex_circumcenter",
        "of": "T",
        "theorem": "circumcenter_in_tetrahedron_disproof_witness",
        "title": (
            "Witness tetrahedron whose circumcenter lies outside it "
            "(disproves: the circumcenter lies inside every tetrahedron)"
        ),
    },
    scene={"kind": "simplex", "of": "T", "center": "circumcenter", "weights": "barycentric"},
    lean_statement=(
        "theorem circumcenter_in_tetrahedron\n"
        "    (T : Affine.Simplex ℝ (EuclideanSpace ℝ (Fin 3)) 3) :\n"
        "    T.circumcenter ∈ interior (convexHull ℝ (Set.range T.points)) := by\n"
        "  sorry"
    ),
    notes="False: sliver tetrahedra near a common sphere throw the center out.",
)
