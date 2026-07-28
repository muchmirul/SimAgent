"""Ground truth: FALSE in every dimension — obtuse simplices exist for all d.
This is the DIMENSION-AGNOSTIC known-answer test (plan.md P5 gate): the same
recipe as the triangle, in ℝ⁴. The counterexample is certified in exact
rational arithmetic (sandbox). NO Lean certificate exists above d = 3 — the
determinant encoding caps there — and the harness says so explicitly rather
than pretending (decision D6). The scene is an honest projection ℝ⁴ → ℝ³."""
from ..core.claim import Claim
from ..core.space import Box

CLAIM = Claim(
    id="circumcenter-in-4simplex",
    title="Circumcenter lies inside every 4-simplex (ℝ⁴)",
    conjecture=(
        "For every nondegenerate 4-simplex (5 points in R^4), the center of "
        "its circumscribed 3-sphere lies in the interior of the simplex."
    ),
    latex=(
        r"\forall\, P_0,\dots,P_4 \in \mathbb{R}^4 \text{ affinely independent},\quad "
        r"O(P_0,\dots,P_4) \in \operatorname{int}\,\mathrm{conv}\{P_0,\dots,P_4\}"
    ),
    quantifier="forall",
    spaces={"T": Box(shape=(5, 4), low=-1.2, high=1.2)},
    recipe=[
        {"name": "circumcenter", "ctor": "circumcenter", "args": ["T"]},
        {"name": "barycentric", "ctor": "barycentric", "args": ["T", "circumcenter"]},
    ],
    measure={"kind": "min_coord", "of": "barycentric"},
    constraint={"kind": "min_volume", "of": "T", "threshold": 0.005},
    certify={"kind": "simplex_circumcenter_inside", "of": "T"},
    lean={
        # Honest cap: generation raises "capped at d<=3" and the proof keeps
        # its sandbox stamp with the failure recorded — never silently.
        "kind": "simplex_circumcenter",
        "of": "T",
        "theorem": "circumcenter_in_4simplex_disproof_witness",
        "title": "Witness 4-simplex whose circumcenter lies outside it",
    },
    scene={"kind": "simplex", "of": "T", "center": "circumcenter", "weights": "barycentric"},
    lean_statement=(
        "-- d = 4: no generated core certificate yet (determinant encoding caps\n"
        "-- at d <= 3; the LU-witness encoding is the planned extension).\n"
        "True"
    ),
    notes=(
        "False in every dimension d >= 2: obtuse simplices exist for all d. "
        "Above d = 3 the verdict tops out at verified_by='sandbox' (exact "
        "rational arithmetic) — no Lean certificate is generated, and the "
        "answer states this explicitly."
    ),
)
