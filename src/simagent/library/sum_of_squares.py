"""Ground truth: FALSE — x² + y² + 1 > 2(x + y) fails on a disc.

Completing the square rewrites the margin as (x−1)² + (y−1)² − 1, so the
claim fails exactly on the open unit disc centred at (1, 1); the worst point
is (1, 1) with margin −1. The zero-contour is that circle, which makes this
the algebraic echo of the triangle claim's Thales circle: search becomes
perception.

First bundled claim built on the GENERAL vocabulary — an `expr` margin, an
`expr` certifier, an `expr` Lean certificate, and the generic `point` scene.
Nothing here is specific to this problem: any rational inequality over a
finite-dimensional box is now expressible the same way, at any dimension
(the Q-term encoding has no d<=3 cap).
"""
from ..core.claim import Claim
from ..core.space import Box

# One string, three uses: the sandbox measures it, sympy certifies it, and
# Lean checks it. validate_claim() rejects any claim whose certifier or Lean
# hook quietly names a different expression.
MARGIN = "P[0]**2 + P[1]**2 + 1 - 2*P[0] - 2*P[1]"

CLAIM = Claim(
    id="sum-of-squares-vs-linear",
    title="x² + y² + 1 exceeds 2(x + y) for all real x, y",
    conjecture=(
        "For all real numbers x and y, x^2 + y^2 + 1 is strictly greater "
        "than 2*(x + y)."
    ),
    latex=r"\forall\, x,y \in \mathbb{R}:\quad x^2 + y^2 + 1 > 2(x + y)",
    quantifier="forall",
    spaces={"P": Box(shape=(2,), low=-2.0, high=2.0)},
    recipe=[],
    measure={"kind": "expr", "margin": MARGIN},
    certify={"kind": "expr", "margin": MARGIN},
    lean={
        "kind": "expr",
        "margin": MARGIN,
        "theorem": "sum_of_squares_vs_linear_disproof_witness",
        "title": (
            "Witness point where x² + y² + 1 - 2(x + y) is negative "
            "(disproves: x² + y² + 1 > 2(x + y) for all real x, y)"
        ),
    },
    scene={"kind": "point", "of": "P"},
    lean_statement=(
        "theorem sum_of_squares_vs_linear (x y : ℚ) :\n"
        "    x^2 + y^2 + 1 > 2 * (x + y) := by\n"
        "  sorry"
    ),
    notes=(
        "False: the margin is (x-1)^2 + (y-1)^2 - 1, negative on the open "
        "unit disc centred at (1,1). Worst case (1,1) with margin -1."
    ),
)
