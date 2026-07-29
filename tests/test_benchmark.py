"""The benchmark, and the kernel bug its first run caught.

One number says whether the harness still works. It must stay at 100%: every
bundled Claim is a known-answer test, so anything less is a regression, not a
judgement call.
"""
import sympy as sp

from simagent import benchmark, lean_check, library
from simagent.sandbox import certify as certify_mod

lean_ok = lean_check.lean_available()


def test_every_bundled_claim_has_a_stated_expectation():
    """A claim with no expectation is a claim nothing is checking."""
    assert set(benchmark.EXPECTED) == {c.id for c in library.all_specs()}
    for cid, (verdict, strength, truth) in benchmark.EXPECTED.items():
        assert verdict and truth, cid
        assert strength in ("sandbox+lean", "sandbox", "lean", "none"), cid


def test_benchmark_is_green():
    """Two different things are checked, and only one of them needs Lean.

    The VERDICT is what the machine concluded, and it is judged on every
    machine: a claim flipping from `counterexample` to `no_counterexample` is
    wrong whether or not a toolchain is installed. The STRENGTH is how well
    that conclusion was checked, and only the top rung is out of reach without
    Lean.

    Dropping the whole row on a no-Lean machine used to excuse both at once, so
    8 of the 11 known-answer claims were checked for nothing at all in the CI
    job that has no toolchain, verdicts included.
    """
    rows = benchmark.run_all(trials=400, seed=0)
    failures = []
    for r in rows:
        if r.got_verdict != r.expected_verdict:
            failures.append(
                f"{r.id}: verdict {r.got_verdict} (want {r.expected_verdict})")
        elif r.got_strength != r.expected_strength and not (
                not lean_ok and r.expected_strength.endswith("lean")):
            failures.append(
                f"{r.id}: strength {r.got_strength} (want {r.expected_strength})")
    assert not failures, "benchmark regressed:\n" + "\n".join(failures)


def test_exact_barycentric_stays_rational():
    """The bug the benchmark found on its first run.

    `sp.nsimplify` searches for a "nicer" closed form, and on this rational
    triangle it returned an irrational surd that was merely CLOSE to the true
    coordinate. Exact arithmetic had silently left the rationals, and the Lean
    step then crashed on a value it could not encode. Never point nsimplify at
    something already exact.
    """
    T = sp.Matrix([[sp.Rational(1, 4), sp.Rational(-7, 13)],
                   [sp.Rational(-6, 7), sp.Rational(-6, 5)],
                   [sp.Rational(8, 15), sp.Rational(6, 5)]])
    c = certify_mod.exact_circumcenter(T)
    assert all(x.is_rational for x in c)
    w = certify_mod.exact_barycentric(T, c)
    assert all(x.is_rational for x in w), f"left the rationals: {w}"
    # the coordinates of a point relative to its own simplex still sum to one
    assert sum(w) == 1
