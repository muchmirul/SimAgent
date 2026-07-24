"""Ground truth: TRUE for every natural n, without any upper bound.

n^2 + 1 > n holds for all n >= 0, and the point of this claim is the word
ALL. The declared integer range is astronomically large, so exhaustion is out
of reach; and no finite check could settle an unbounded statement anyway.

This is the known-answer test for INDUCTION. The margin is n^2 - n + 1:

    base   margin(0) = 1 > 0
    step   margin(n+1) - margin(n) = 2n, which is a sum of squares once n >= 0
           is admitted as a hypothesis

A non-decreasing margin that starts positive stays positive, forever. That is
a statement about infinitely many n, reached by checking two finite things.
"""
from ..core.claim import Claim
from ..core.space import IntBox

MARGIN = "P[0]**2 + 1 - P[0]"

CLAIM = Claim(
    id="unbounded-quadratic",
    title="n² + 1 exceeds n for every natural number n",
    conjecture="For every integer n >= 0, n^2 + 1 is strictly greater than n.",
    latex=r"\forall\, n \in \mathbb{N}:\quad n^2 + 1 > n",
    quantifier="forall",
    # the range is a sampling window only; the claim itself has no upper bound
    spaces={"P": IntBox(shape=(1,), low=0, high=10**9)},
    recipe=[],
    measure={"kind": "expr", "margin": MARGIN},
    certify={"kind": "expr", "margin": MARGIN},
    assume=["P[0]"],
    scene={"kind": "point", "of": "P"},
    lean_statement=(
        "theorem unbounded_quadratic (n : ℕ) :\n"
        "    n^2 + 1 > n := by\n"
        "  sorry"
    ),
    notes=(
        "True for every n >= 0. Base margin(0) = 1; the step increase is 2n, "
        "nonnegative for n >= 0, so the margin never decreases. Proved by "
        "induction, which reaches every n; exhaustion could only reach the "
        "declared window."
    ),
)

SPEC = CLAIM
