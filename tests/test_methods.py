"""Instruments for two more of the ten methods: cases and induction.

The model picks the method; these only check that when it reaches for one,
the harness can actually execute it — and refuses honestly when it cannot.
Both are deductive, so both are Lean-or-nothing.
"""
import json

import pytest

from simagent import lean_check
from simagent.agent import TOOLS, AgentRun
from simagent.library import get
from simagent.proof import Method, cases_proof, induction_proof

lean = pytest.mark.skipif(not lean_check.lean_available(), reason="no Lean toolchain")


def test_both_instruments_are_reachable_by_the_model():
    names = [t["name"] for t in TOOLS]
    assert "prove_by_cases" in names
    assert "prove_by_induction" in names


@lean
def test_cases_splits_the_domain_and_certifies_both_halves(tmp_path):
    proof = cases_proof(get("positive-quadratic"), "P", 0, 0.0,
                        out_dir=tmp_path, spec_trusted=True)
    assert proof is not None
    assert proof.method is Method.CASES
    assert proof.verified_by == "sandbox+lean"
    # both halves must appear as readable identities, not just a claim of success
    assert proof.argument.count("**2") >= 2
    assert "P_0 >= 0" in proof.argument and "P_0 <= 0" in proof.argument
    # one file, one theorem per case, every one axiom-clean
    source = (tmp_path / "certificate.lean").read_text()
    assert source.count("#print axioms") == 2


def test_cases_refuses_a_coordinate_that_does_not_exist():
    notes = []
    assert cases_proof(get("positive-quadratic"), "Zz", 0, 0.0, notes=notes) is None
    assert any("no free coordinate" in n for n in notes)


@lean
def test_induction_settles_every_n_not_just_the_window(tmp_path):
    """The claim's integer range is 10^9 wide, so exhaustion cannot reach it,
    and no finite check settles an unbounded statement anyway."""
    proof = induction_proof(get("unbounded-quadratic"), out_dir=tmp_path,
                            spec_trusted=True)
    assert proof is not None
    assert proof.method is Method.INDUCTION
    assert proof.verified_by == "sandbox+lean"
    assert "Base case" in proof.argument and "never decreases" in proof.argument


def test_induction_refuses_a_multivariable_margin():
    notes = []
    assert induction_proof(get("positive-quadratic"), notes=notes) is None
    assert any("exactly one variable" in n for n in notes)


def _induction_claim(cid, space, margin, assume=()):
    """A one-variable expr claim, so induction is the instrument under test."""
    from simagent.core.claim import Claim

    return Claim(
        id=cid, title=cid, conjecture=cid, latex=cid, quantifier="forall",
        spaces={"P": space}, recipe=[],
        measure={"kind": "expr", "margin": margin},
        certify={"kind": "expr", "margin": margin},
        assume=list(assume), scene={"kind": "point", "of": "P"},
    )


def test_induction_refuses_a_domain_it_cannot_walk():
    """Induction steps from one integer to the next, so a real interval has
    points it never lands on. The margin here dips below zero at x = 0.5, which
    no step visits, and the whole claim used to be stamped sandbox+lean anyway.
    """
    from simagent.core.space import Box

    notes = []
    claim = _induction_claim("real-domain", Box(shape=(1,), low=0.0, high=3.0),
                             "4*P[0]**2 - 4*P[0] + 1/2")
    assert induction_proof(claim, notes=notes) is None
    assert any("integer domain" in n for n in notes)


def test_induction_anchors_the_base_at_the_declared_start():
    """The base case was pinned at n = 0 whatever the claim declared, so a
    domain reaching below 0 was stamped from a case outside it. Here the margin
    is n + 1, which is false at n = -10, the domain's own first point."""
    from simagent.core.space import IntBox

    notes = []
    claim = _induction_claim("starts-below-zero",
                             IntBox(shape=(1,), low=-10, high=10), "P[0] + 1")
    assert induction_proof(claim, notes=notes) is None
    assert any("P_0 = -10" in n for n in notes), notes


def test_induction_does_not_borrow_the_claims_hypothesis():
    """A hypothesis can be false at a point the chain still has to cross, so
    using it as a step multiplier certifies a step the induction never earns.
    This margin is false at n = 1 and n = 2, both inside the declared domain,
    and the hypothesis n >= 1 used to certify the step regardless."""
    from simagent.core.space import IntBox

    notes = []
    claim = _induction_claim("hypothesis-gap",
                             IntBox(shape=(1,), low=1, high=10 ** 9),
                             "P[0]**2 + 1 - 3*P[0]", assume=["P[0] - 1"])
    assert induction_proof(claim, notes=notes) is None


def test_induction_refuses_a_failing_base_case():
    import dataclasses

    notes = []
    claim = get("unbounded-quadratic")
    # margin(0) = -1: the base case is false, so nothing may be stamped
    broken = dataclasses.replace(claim, measure={"kind": "expr", "margin": "P[0] - 1"},
                                 certify={"kind": "expr", "margin": "P[0] - 1"})
    assert induction_proof(broken, notes=notes) is None
    assert any("base case fails" in n for n in notes)


@lean
def test_instruments_record_the_proof_for_the_run(tmp_path):
    run = AgentRun(get("positive-quadratic"), out_dir=tmp_path)
    out = json.loads(run._t_prove_by_cases(var="P", at=0.0, index=0))
    assert out["proved"] is True and out["verified_by"] == "sandbox+lean"
    assert run.deductive is not None and run.deductive.method is Method.CASES
