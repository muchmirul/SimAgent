"""The benchmark: one number that says whether the harness works.

Every bundled Claim is a known-answer test, so the ground truth is already
decided and written down. This module states the EXPECTED outcome for each
one and checks the machine reaches it, giving a single pass rate that any
later change can be judged against.

An expectation is a pair: the search verdict, and the strongest verdict the
honesty ladder should reach. Both must match. A run that reaches the right
answer with the wrong strength is a failure here, because the strength is
the product.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import library
from . import proof as proof_mod
from .search import exhaustible, run_exhaustive, run_search

# claim id -> (search verdict, verified_by, one-line ground truth)
EXPECTED: dict[str, tuple[str, str, str]] = {
    "circumcenter-in-triangle": (
        "counterexample", "sandbox+lean",
        "false: the circumcenter is inside iff the triangle is acute (Thales)",
    ),
    "circumcenter-in-tetrahedron": (
        "counterexample", "sandbox+lean",
        "false: same escape one dimension up",
    ),
    "circumcenter-in-4simplex": (
        "counterexample", "sandbox",
        "false in R^4; no Lean above d=3, so the verdict stops at sandbox",
    ),
    "orthocenter-in-triangle": (
        "counterexample", "sandbox",
        "false: the orthocenter is inside iff the triangle is acute; the "
        "margin reads a derived entity, so no Lean atom exists",
    ),
    "euler-characteristic-hull": (
        "no_counterexample", "none",
        "true, but V-E+F=2 is a discrete invariant with no margin: evidence only",
    ),
    "sum-of-odds-square": (
        "holds_on_domain", "sandbox+lean",
        "true and finite: proved by exhaustion over n <= 200",
    ),
    "sum-of-squares-vs-linear": (
        "counterexample", "sandbox+lean",
        "false: the margin is (x-1)^2+(y-1)^2-1, negative on the unit disc at (1,1)",
    ),
    "positive-quadratic": (
        "no_counterexample", "sandbox+lean",
        "true: proved by a sum-of-squares certificate, minimum margin 1/2",
    ),
}


@dataclass
class Row:
    id: str
    expected_verdict: str
    got_verdict: str
    expected_strength: str
    got_strength: str
    truth: str

    @property
    def ok(self) -> bool:
        return (self.got_verdict == self.expected_verdict
                and self.got_strength == self.expected_strength)


def run_one(claim_id: str, trials: int = 400, seed: int = 0, out_dir=None) -> Row:
    claim = library.get(claim_id)
    want_verdict, want_strength, truth = EXPECTED[claim_id]
    if exhaustible(claim):
        report = run_exhaustive(claim)
    else:
        report = run_search(claim, trials=trials, seed=seed)
    proof = proof_mod.mechanized_proof(claim, report, out_dir=out_dir, spec_trusted=True)
    if proof is None:
        proof = proof_mod.sos_proof(claim, report, out_dir=out_dir, spec_trusted=True)
    return Row(
        id=claim_id,
        expected_verdict=want_verdict, got_verdict=report.verdict,
        expected_strength=want_strength,
        got_strength=proof.verified_by if proof is not None else "none",
        truth=truth,
    )


def run_all(trials: int = 400, seed: int = 0, out_dir=None) -> list[Row]:
    return [run_one(cid, trials=trials, seed=seed, out_dir=out_dir)
            for cid in EXPECTED]


def format_report(rows: list[Row]) -> str:
    passed = sum(1 for r in rows if r.ok)
    lines = [f"{'':2} {'problem':34} {'verdict':18} {'strength':14}"]
    for r in rows:
        mark = "ok" if r.ok else "XX"
        verdict = r.got_verdict if r.got_verdict == r.expected_verdict \
            else f"{r.got_verdict}!={r.expected_verdict}"
        strength = r.got_strength if r.got_strength == r.expected_strength \
            else f"{r.got_strength}!={r.expected_strength}"
        lines.append(f"{mark:2} {r.id:34} {verdict:18} {strength:14}")
    lines.append("")
    lines.append(f"pass rate: {passed}/{len(rows)} ({100 * passed // max(len(rows), 1)}%)")
    return "\n".join(lines)
