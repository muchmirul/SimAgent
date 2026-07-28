"""Ground truth: TRUE for x >= 0 — and FALSE without that hypothesis.

x^3 + 1 > x holds for every nonnegative x (the margin bottoms out near 0.615
at x = 1/sqrt3), but fails at x = -2, where it reads -5. So the hypothesis is
not decoration: it is the difference between a theorem and a false statement.

This is the known-answer test for CONDITIONAL proving. An unconstrained
sum-of-squares search refuses this margin immediately and correctly - odd
total degree means the polynomial goes negative somewhere - and that refusal
is useless, because it answers a question nobody asked. With the hypothesis
admitted as an ingredient the certificate exists:

    x^3 + 1 - x  =  sigma_0  +  x * sigma_1     (both sigma sums of squares)

Every term is nonnegative wherever x >= 0, which is exactly where the claim
is made. The harness finds its own decomposition (the coefficients will not
be the tidy hand-written ones) and the Lean kernel checks it.
"""
from ..core.claim import Claim
from ..core.space import Box

MARGIN = "P[0]**3 + 1 - P[0]"

CLAIM = Claim(
    id="conditional-cubic",
    title="x³ + 1 exceeds x for every nonnegative x",
    conjecture=(
        "For every real number x with x >= 0, x^3 + 1 is strictly greater than x."
    ),
    latex=r"\forall\, x \in \mathbb{R},\ x \ge 0:\quad x^3 + 1 > x",
    quantifier="forall",
    spaces={"P": Box(shape=(1,), low=0.0, high=3.0)},
    recipe=[],
    measure={"kind": "expr", "margin": MARGIN},
    certify={"kind": "expr", "margin": MARGIN},
    assume=["P[0]"],  # the hypothesis x >= 0, usable inside the proof
    scene={"kind": "point", "of": "P"},
    lean_statement=(
        "theorem conditional_cubic (x : ℚ) (hx : 0 ≤ x) :\n"
        "    x^3 + 1 > x := by\n"
        "  sorry"
    ),
    notes=(
        "True on x >= 0 (minimum margin 1 - 2/(3*sqrt 3) ~ 0.615 at x = 1/sqrt 3), "
        "false at x = -2 where the margin is -5. Provable only because the "
        "hypothesis is declared and used."
    ),
)
