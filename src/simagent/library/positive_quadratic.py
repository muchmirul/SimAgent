"""Ground truth: TRUE — x² + y² + 1 > x + y for every real x and y.

Completing the square gives margin = (x−1/2)² + (y−1/2)² + 1/2, so the margin
never drops below 1/2. Deliberately the twin of `sum-of-squares-vs-linear`:
same shape, one constant changed (x + y instead of 2(x + y)), opposite truth
value. The machine disproves that one and PROVES this one.

This is the known-answer test for the PROVING side. No amount of sampling can
establish a `forall` over a continuous domain, so the verdict here comes from
a sum-of-squares certificate: the margin minus 1/2 is written as a sum of
squares with nonnegative rational coefficients, which makes it nonnegative at
every real point at once. The identity is expanded exactly and then checked by
the Lean kernel; without that check the claim stays evidence (a direct proof
is deductive, and deductive means Lean-or-nothing).
"""
from ..core.claim import Claim
from ..core.space import Box

MARGIN = "P[0]**2 + P[1]**2 + 1 - P[0] - P[1]"

CLAIM = Claim(
    id="positive-quadratic",
    title="x² + y² + 1 exceeds x + y for all real x, y",
    conjecture=(
        "For all real numbers x and y, x^2 + y^2 + 1 is strictly greater "
        "than x + y."
    ),
    latex=r"\forall\, x,y \in \mathbb{R}:\quad x^2 + y^2 + 1 > x + y",
    quantifier="forall",
    spaces={"P": Box(shape=(2,), low=-2.0, high=2.0)},
    recipe=[],
    measure={"kind": "expr", "margin": MARGIN},
    certify={"kind": "expr", "margin": MARGIN},
    scene={"kind": "point", "of": "P"},
    lean_statement=(
        "theorem positive_quadratic (x y : ℚ) :\n"
        "    x^2 + y^2 + 1 > x + y := by\n"
        "  sorry"
    ),
    notes=(
        "True: the margin is (x-1/2)^2 + (y-1/2)^2 + 1/2, whose minimum is "
        "1/2 at (1/2, 1/2). Proved by a sum-of-squares certificate, not by "
        "sampling."
    ),
)
