import pytest

from types import SimpleNamespace

from simagent import explain, lean_check
from simagent.library import get
from simagent.proof import (
    Method,
    deductive_proof,
    mechanized_proof,
    verification_rank,
)
from simagent.search import case_count, exhaustible, run_exhaustive, run_search

lean = pytest.mark.skipif(not lean_check.lean_available(), reason="no Lean toolchain")


def test_case_count_and_exhaustible():
    assert case_count(get("sum-of-odds-square")) == 201
    assert exhaustible(get("sum-of-odds-square"))
    assert case_count(get("circumcenter-in-triangle")) is None
    assert not exhaustible(get("circumcenter-in-triangle"))


def test_exhaustion_proves_bounded_statement(tmp_path):
    spec = get("sum-of-odds-square")
    report = run_exhaustive(spec)
    assert report.verdict == "holds_on_domain"
    assert report.valid_trials == 201
    assert report.certified is True

    proof = mechanized_proof(spec, report, out_dir=tmp_path)
    assert proof is not None
    assert proof.method is Method.EXHAUSTION
    assert proof.verified_by in ("sandbox", "sandbox+lean")


def test_counterexample_proof(tmp_path):
    spec = get("circumcenter-in-triangle")
    report = run_search(spec, trials=300, seed=0)
    proof = mechanized_proof(spec, report, out_dir=tmp_path)
    assert proof is not None
    assert proof.method is Method.COUNTEREXAMPLE
    assert proof.claim.startswith("NOT[")
    assert proof.witness is not None
    # a certificate source was generated regardless of toolchain availability
    assert (tmp_path / "certificate.lean").exists()
    source = (tmp_path / "certificate.lean").read_text()
    assert "by\n  decide" in source and "#print axioms" in source


def test_evidence_is_not_a_proof(tmp_path):
    spec = get("euler-characteristic-hull")
    report = run_search(spec, trials=60, seed=0)
    assert report.verdict == "no_counterexample"
    assert mechanized_proof(spec, report, out_dir=tmp_path) is None


@pytest.mark.parametrize(
    ("method", "stamp", "verdict", "expected", "not_expected"),
    [
        ("counterexample", "sandbox", "counterexample", "violates", "satisfies"),
        ("construction", "sandbox", "witness", "satisfies", "violation"),
        ("exhaustion", "sandbox", "holds_on_domain", "every valid case", "witness"),
        ("direct", "sandbox+lean", "no_counterexample", "deductive certificate", "witness"),
        ("cases", "sandbox+lean", "no_counterexample", "both certified cases", "witness"),
        ("induction", "sandbox+lean", "no_counterexample", "base case and step", "witness"),
    ],
)
def test_result_summary_names_what_the_method_actually_checked(
    method, stamp, verdict, expected, not_expected
):
    summary = explain.result_summary(
        {"method": method, "verified_by": stamp}, {"verdict": verdict}
    ).lower()
    assert expected in summary
    assert not_expected not in summary


def test_sandbox_outranks_untrusted_lean_and_exists_margin_is_not_a_forall_claim():
    assert verification_rank("sandbox+lean") > verification_rank("sandbox")
    assert verification_rank("sandbox") > verification_rank("lean")
    rows = explain.result_rows(
        SimpleNamespace(quantifier="exists"), None, None, {"margin": -1.0}
    )
    margin = next(row for row in rows if row["label"] == "Margin")
    assert "does not settle" in margin["why"]
    assert "for all" not in margin["why"]


def test_deductive_attempt_without_lean_is_unverified(tmp_path):
    spec = get("euler-characteristic-hull")
    proof = deductive_proof(spec, "induction", "hand-waving", lean_code=None, out_dir=tmp_path)
    assert proof.method is Method.INDUCTION
    assert proof.verified_by == "none"


@lean
def test_lean_rejects_sorry_and_bad_proofs(tmp_path):
    bad = "theorem nope : 1 + 1 = 3 := by decide\n#print axioms nope\n"
    result = lean_check.check_source(bad, workdir=tmp_path)
    assert result["ok"] is False

    sorried = "theorem nope : 1 + 1 = 2 := by sorry\n#print axioms nope\n"
    result = lean_check.check_source(sorried, workdir=tmp_path)
    assert result["ok"] is False

    good = "theorem yep : 1 + 1 = 2 := by decide\n#print axioms yep\n"
    result = lean_check.check_source(good, workdir=tmp_path)
    assert result["ok"] is True and result["axiom_clean"] is True

    no_print = "theorem yep : 1 + 1 = 2 := by decide\n"
    result = lean_check.check_source(no_print, workdir=tmp_path)
    assert result["ok"] is True and result["axiom_clean"] is False  # fail-closed


@lean
def test_lean_kernel_verifies_counterexample_certificate(tmp_path):
    spec = get("circumcenter-in-triangle")
    report = run_search(spec, trials=300, seed=0)
    proof = mechanized_proof(spec, report, out_dir=tmp_path)
    assert proof is not None
    assert proof.verified_by == "sandbox+lean", proof.lean_report
    assert proof.lean_report["axiom_clean"] is True


@lean
def test_lean_kernel_verifies_exhaustion_certificate(tmp_path):
    spec = get("sum-of-odds-square")
    report = run_exhaustive(spec)
    proof = mechanized_proof(spec, report, out_dir=tmp_path)
    assert proof is not None
    assert proof.verified_by == "sandbox+lean", proof.lean_report
