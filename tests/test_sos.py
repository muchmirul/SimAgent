"""Sum-of-squares: the harness's first way to PROVE a universal claim over a
continuous domain.

The tests that matter most here are the refusals. A proving path that says
"proved" when it should not is worse than no proving path at all, so: false
inequalities must fail, non-strict ones must not be upgraded to strict, and
nothing is stamped unless the Lean kernel accepts the certificate.
"""
import numpy as np
import pytest
import sympy as sp

from simagent import lean_check
from simagent.library import get
from simagent.pipeline import run_problem
from simagent.proof import Method, sos_proof
from simagent.sandbox import leangen, sos
from simagent.search import run_search

lean = pytest.mark.skipif(not lean_check.lean_available(), reason="no Lean toolchain")
x, y, z = sp.symbols("x y z")


@pytest.mark.parametrize(
    "name, poly, syms",
    [
        ("AM-GM", x**2 + y**2 - 2 * x * y, [x, y]),
        ("Cauchy-Schwarz, sharp constant", 3 * (x**2 + y**2 + z**2) - (x + y + z) ** 2, [x, y, z]),
        ("quartic (x^2-y^2)^2", x**4 - 2 * x**2 * y**2 + y**4, [x, y]),
        ("shifted, strictly positive", (x - 1) ** 2 + (y - 1) ** 2 + 1, [x, y]),
    ],
)
def test_true_inequalities_get_a_certificate(name, poly, syms):
    found = sos.find_sos(poly, syms)
    assert found is not None, name
    assert sos._verify(sp.expand(poly), syms, found["basis"], found["squares"])
    assert all(d >= 0 for d, _ in found["squares"])


@pytest.mark.parametrize(
    "name, poly, syms",
    [
        ("Cauchy-Schwarz with too small a constant",
         2 * (x**2 + y**2 + z**2) - (x + y + z) ** 2, [x, y, z]),
        ("odd degree is negative somewhere", x**3, [x]),
        ("plainly negative region", x * y, [x, y]),
    ],
)
def test_false_inequalities_get_nothing(name, poly, syms):
    assert sos.find_sos(poly, syms) is None, name


def test_non_polynomial_and_oversized_margins_are_refused():
    with pytest.raises(sos.SOSError):
        sos.find_sos(1 / x, [x])
    with pytest.raises(sos.SOSError):
        sos.find_sos(sum(s**2 for s in sp.symbols("a0:9")), list(sp.symbols("a0:9")))


def test_equality_case_is_not_upgraded_to_strict():
    """x^2+y^2 >= 2xy is true but touches zero at x=y, so a STRICT claim about
    it is not proved. The certificate must report that, not round it up."""
    found = sos.prove_positive(x**2 + y**2 - 2 * x * y, [x, y], eps_hint=sp.Rational(1, 10))
    assert found is not None
    assert found["eps"] == 0
    assert found["strict"] is False


def test_monomial_list_covers_every_product():
    """The Lean check can only force coefficients it is given, so products the
    polynomial never mentions (here x*y) must still appear, with coefficient 0."""
    found = sos.find_sos((x - 1) ** 2 + (y - 1) ** 2 + 1, [x, y])
    assert (1, 1) in found["monomials"]
    assert found["coefficients"][found["monomials"].index((1, 1))] == 0


@lean
def test_certificate_is_kernel_checked():
    found = sos.find_sos((x - 1) ** 2 + (y - 1) ** 2 + 1, [x, y], eps=sp.Rational(1, 2))
    src = leangen.lean_sos(found["basis"], found["gram"], found["squares"],
                           found["monomials"], found["coefficients"],
                           theorem="t_ok", title="ok")
    result = lean_check.check_source(src)
    assert result["ok"] and result["axiom_clean"]


@lean
@pytest.mark.parametrize("tamper", ["overclaim", "negative_coefficient"])
def test_lean_rejects_a_tampered_certificate(tamper):
    """The certificate has to have teeth: if it cannot fail, it proves nothing."""
    poly = (x - 1) ** 2 + (y - 1) ** 2 + 1  # true minimum is 1
    found = sos.find_sos(poly, [x, y], eps=sp.Rational(1, 2))
    coeffs, squares = found["coefficients"], found["squares"]
    if tamper == "overclaim":  # pretend the minimum is 5
        P = sp.Poly(sp.expand(poly - 5), x, y).as_dict()
        coeffs = [sp.nsimplify(P.get(m, 0)) for m in found["monomials"]]
    else:  # not a sum of squares any more
        squares = [(-d, v) for d, v in squares]
    src = leangen.lean_sos(found["basis"], found["gram"], squares,
                           found["monomials"], coeffs, theorem="t_bad", title="bad")
    assert lean_check.check_source(src)["ok"] is False


def test_every_failure_mode_tells_the_model_something_actionable():
    """A dead end with no reason is a dead end the model cannot act on. Each
    failure must state a DIFFERENT fact about why the instrument stopped.

    Facts, not advice: naming the next method to try would be the harness
    doing the model's thinking (see test_harness_never_picks_the_method)."""
    cases = {
        "tight": (x**2 + y**2 - 2 * x * y, [x, y], "TIGHT"),
        "not_psd": (2 * (x**2 + y**2 + z**2) - (x + y + z) ** 2, [x, y, z],
                    "cannot tell those two cases apart"),
        "odd_degree": (x**3, [x], "odd total degree"),
    }
    for name, (poly, syms, expected) in cases.items():
        notes = []
        sos.prove_positive(poly, syms, eps_hint=sp.Rational(1, 10), notes=notes)
        assert notes, f"{name} returned no reason"
        assert any(expected in n for n in notes), f"{name}: {notes}"


def test_certificate_is_printed_as_checkable_mathematics():
    """The identity IS the proof. A reader must be able to expand it by hand
    and settle the claim without Lean and without trusting this code."""
    cert = sos.find_sos((x - 1) ** 2 + (y - 1) ** 2 + 1, [x, y], eps=sp.Rational(1, 2))
    text = sos.identity_text(cert, margin_label="m")
    lhs, rhs = text.split(" = ", 1)
    assert lhs == "m - (1/2)"
    # the printed right-hand side really does equal the margin minus eps
    margin_minus_eps = sp.expand((x - 1) ** 2 + (y - 1) ** 2 + 1 - sp.Rational(1, 2))
    assert sp.expand(sp.sympify(rhs) - margin_minus_eps) == 0


@lean
def test_the_proof_record_carries_the_identity(tmp_path):
    out = run_problem(get("positive-quadratic"), tmp_path, trials=300, seed=1,
                      render_manim=False)
    assert "=" in out.proof.argument and "**2" in out.proof.argument
    assert "sum_i d_i" not in out.proof.argument, "the placeholder must be gone"
    assert "**2" in (tmp_path / "answer.md").read_text()


def test_harness_never_picks_the_method_for_the_model():
    """SimAgent is a harness: it supplies capability, perception and facts,
    never the strategy. An instrument reporting its own limits is doing its
    job; an instrument telling the model which of the ten methods to reach
    for next has taken over the model's thinking."""
    advice = ("hunting", "you should", "try instead", "next, ", "we recommend")
    for poly, syms in [(2 * (x**2 + y**2 + z**2) - (x + y + z) ** 2, [x, y, z]),
                       (x**3, [x]),
                       (x**2 + y**2 - 2 * x * y, [x, y])]:
        notes = []
        sos.prove_positive(poly, syms, eps_hint=sp.Rational(1, 10), notes=notes)
        for n in notes:
            lowered = n.lower()
            assert not any(a in lowered for a in advice), f"harness is steering: {n}"


def test_the_model_can_actually_reach_the_instrument(tmp_path):
    """The harness exists to serve the model: a capability it cannot invoke is
    a capability it does not have."""
    from simagent.agent import TOOLS

    assert "sum_of_squares" in [t["name"] for t in TOOLS]


@lean
def test_instrument_proves_and_explains(tmp_path):
    import json

    from simagent.agent import AgentRun

    run = AgentRun(get("positive-quadratic"), out_dir=tmp_path)
    run._t_hunt(trials=300)
    out = json.loads(run._t_sum_of_squares())
    assert out["proved"] is True
    assert out["verified_by"] == "sandbox+lean"
    assert run.deductive is not None and run.deductive.method is Method.DIRECT

    # a later failed attempt must NOT clobber the verified certificate
    run._t_submit_lean_proof(method="direct", argument="hand-waving", lean_code=None)
    assert run.deductive.verified_by == "sandbox+lean"


def test_instrument_refuses_when_a_counterexample_is_on_the_table(tmp_path):
    import json

    from simagent.agent import AgentRun

    run = AgentRun(get("sum-of-squares-vs-linear"), out_dir=tmp_path)
    run._t_hunt(trials=300)
    out = json.loads(run._t_sum_of_squares())
    assert out["proved"] is False
    assert any("counterexample" in n for n in out["notes"])
    assert run.deductive is None


@lean
def test_instrument_needs_no_search_first(tmp_path):
    """Found in the first live session: the model reached for the proof, was
    told to search first, and burned a turn repeating itself. A certificate
    stands on its own; the harness must not dictate the order of work."""
    import json

    from simagent.agent import AgentRun

    run = AgentRun(get("positive-quadratic"), out_dir=tmp_path)
    out = json.loads(run._t_sum_of_squares())  # no hunt beforehand
    assert out["proved"] is True
    assert out["verified_by"] == "sandbox+lean"


def test_sos_proof_refuses_a_claim_it_should_not_touch():
    claim = get("sum-of-squares-vs-linear")  # FALSE: a counterexample exists
    report = run_search(claim, trials=300, seed=3)
    assert sos_proof(claim, report) is None


@lean
def test_bundled_true_claim_is_proved_not_merely_unrefuted(tmp_path):
    """The whole point: sampling never proves a `forall`, a certificate does."""
    claim = get("positive-quadratic")
    comp = claim.compiled()
    # ground truth: margin = (x-1/2)^2 + (y-1/2)^2 + 1/2, minimum 1/2
    assert comp.check(P=np.array([0.5, 0.5])).margin == pytest.approx(0.5)

    out = run_problem(claim, tmp_path, trials=400, seed=1, render_manim=False)
    assert out.report.verdict == "no_counterexample"
    proof = out.proof
    assert proof is not None, "search alone leaves this unproved; SOS must close it"
    assert proof.method is Method.DIRECT
    assert proof.verified_by == "sandbox+lean"
    assert proof.lean_report["axiom_clean"] is True
    answer = (tmp_path / "answer.md").read_text()
    assert "PROVED for every configuration" in answer
