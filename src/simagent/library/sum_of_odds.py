"""1 + 3 + 5 + ... + (2n-1) = n² over a finite range — proof by exhaustion.

The domain is deliberately finite (n in 0..200), so the harness can check
every single case and honestly claim the *bounded* statement as proved; the
Lean certificate re-decides all cases in the kernel. The unbounded statement
needs induction (a deductive method) — the notes say so. The scene shows the
classic picture proof: each odd number is an L-shaped gnomon completing the
next square. Native claim: no exec'd code."""
from ..core.claim import Claim
from ..core.space import IntBox

_LEAN_DEFS = """
def soddSum : Nat → Nat
  | 0 => 0
  | n + 1 => soddSum n + (2 * n + 1)
"""

CLAIM = Claim(
    id="sum-of-odds-square",
    title="Sum of the first n odd numbers equals n² (n ≤ 200)",
    conjecture=(
        "For every integer n with 0 ≤ n ≤ 200, the sum of the first n odd "
        "numbers equals n²."
    ),
    latex=r"\forall\, n \in \{0,\dots,200\}:\quad \sum_{i=1}^{n} (2i-1) = n^2",
    quantifier="forall",
    spaces={"n": IntBox(shape=(), low=0, high=200)},
    recipe=[],
    measure={"kind": "sum_of_first_odds_equals_square", "of": "n"},
    constraint=None,
    certify=None,
    lean={
        "kind": "bounded_nat",
        "theorem": "sum_of_first_n_odds_eq_square",
        "title": "For every n <= 200, 1 + 3 + ... + (2n-1) = n^2 (checked case by case)",
        "defs": _LEAN_DEFS,
        "statement": "∀ n : Nat, n < 201 → soddSum n = n * n",
    },
    scene={"kind": "gnomon_square", "of": "n"},
    lean_statement=(
        "∀ n : Nat, n ≤ 200 → (Finset.range n).sum (fun i => 2 * i + 1) = n ^ 2"
    ),
    notes=(
        "True — and provable for ALL n by induction (a deductive method). The "
        "harness proves only the bounded statement, by exhaustion over every "
        "case in the declared domain."
    ),
)
