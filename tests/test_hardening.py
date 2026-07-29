"""Regression tests for the post-audit soundness/honesty hardening.

Each test pins one finding from the adversarial review so a future change that
reopens the hole fails loudly. (P5 note: bundled problems are now immutable
native Claims, so the bad-domain cases are constructed directly instead of
mutating a bundled object — the invariants under test are unchanged.)
"""
import ast
from dataclasses import replace

import numpy as np
import pytest

from simagent import lean_check
from simagent.library import get, is_bundled
from simagent.core.journal import read_trace
from simagent.kernel_transport import KernelTransport
from simagent.core.claim import Claim, ClaimValidationError, validate_claim
from simagent.core.space import IntBox, sample_vars
from simagent.pipeline import run_problem
from simagent.proof import Method, mechanized_proof
from simagent.search import (
    case_count,
    exhaustible,
    int_domain_exact,
    run_exhaustive,
)
from simagent.visualize.manim_gen import write_manim_scene

lean = pytest.mark.skipif(not lean_check.lean_available(), reason="no Lean toolchain")


def _int_domain_claim(low, high, shape=(), margin="1"):
    return Claim(
        id="bad-int-domain",
        title="integer boundary test",
        conjecture="test the declared integer domain",
        latex=r"\forall n",
        quantifier="forall",
        spaces={"n": IntBox(shape=tuple(shape), low=low, high=high)},
        measure={"kind": "expr", "margin": margin},
        scene={"kind": "point", "of": "n"},
    )


# ---- the claim's own domain and its own margin ----------------------------

def test_a_lean_hook_of_any_kind_must_measure_the_claims_margin():
    """The verbatim-margin gate used to fire only for hooks of kind "expr".

    A `recipe` Lean hook carries a margin too, so it could name any expression
    and still upgrade the stamp: setting only lean["margin"] = "1" on a bundled
    claim passed validation with no errors at all, and the kernel would then
    check a quantity the claim never measured.
    """
    import copy

    claim = get("orthocenter-in-triangle")
    assert claim.lean["kind"] == "recipe", "this test needs a non-expr hook"
    assert validate_claim(claim) == []

    tampered = copy.deepcopy(claim)
    tampered.lean = dict(tampered.lean)
    tampered.lean["margin"] = "1"
    assert any("must repeat the measure's margin" in e
               for e in validate_claim(tampered)), validate_claim(tampered)


def test_a_point_the_hypothesis_excludes_cannot_certify_anything():
    """The checker and the prover must agree on which points a claim covers.

    `assume` used to be read only by the proof path, so the runtime filter knew
    nothing about it: `conditional-cubic` assumes x >= 0, and certifying it at
    x = -2 returned certified True, holds False, margin -5. That is a checkable
    "counterexample" to a claim that never covered that point.

    Moving there is still allowed, because exploring is not claiming. Only the
    truth layer refuses, and it says why.
    """
    import tempfile

    from simagent.web.session import SandboxSession

    claim = get("conditional-cubic")
    assert claim.assume == ["P[0]"] and claim.constraint is None
    engine = claim.compiled()
    assert engine.valid(P=np.array([1.5])) is True
    assert engine.valid(P=np.array([-2.0])) is False

    with tempfile.TemporaryDirectory() as tmp:
        session = SandboxSession(claim, tmp)
        session.set_value("P", None, [-2.0])          # exploring is free
        with pytest.raises(ValueError, match="outside what the claim covers"):
            session.certify()                          # claiming is not
        session.set_value("P", None, [1.5])
        assert session.certify()["certified"] is not None


# ---- exhaustion soundness -------------------------------------------------

def test_case_count_rejects_inverted_and_empty_domains():
    bad = _int_domain_claim(low=200, high=0)  # inverted
    assert case_count(bad) == 0
    assert not exhaustible(bad)
    with pytest.raises(ValueError):
        run_exhaustive(bad)


def test_case_count_no_int64_overflow_on_huge_shapes():
    huge = _int_domain_claim(low=0, high=200, shape=[1000000])
    # python-int arithmetic -> astronomically large but correct, not 1
    assert case_count(huge) > 10**100
    assert not exhaustible(huge)


def test_int_domain_exact_guard():
    spec = get("sum-of-odds-square")
    assert int_domain_exact(spec)
    unsafe = _int_domain_claim(low=0, high=2**50)  # beyond the 2^40 safe bound
    assert not int_domain_exact(unsafe)


def test_exhaustion_hit_without_certifier_is_not_certified_when_unsafe():
    # A forall over an unsafe integer range fails, but has no exact certifier.
    spec = replace(
        _int_domain_claim(low=2**50, high=2**50 + 3, margin="-1"),
        id="unsafe-int-forall",
    )
    report = run_exhaustive(spec)
    assert report.verdict == "counterexample"
    assert report.certified is False  # fail-closed, not True
    assert mechanized_proof(spec, report) is None  # kernel refuses to call it a proof


def test_exhaustion_incomplete_when_check_raises():
    spec = replace(_int_domain_claim(low=0, high=5), id="raises-forall")
    native = spec.compiled()

    class RaisingEngine:
        has_certify = native.has_certify

        def valid(self, **values):
            return native.valid(**values)

        def check(self, **values):
            if int(values["n"]) == 3:
                raise RuntimeError("boom")
            return native.check(**values)

    spec.compiled = lambda: RaisingEngine()
    report = run_exhaustive(spec)
    # a case we could not decide means the forall is NOT proved
    assert report.verdict == "no_counterexample"
    assert report.certified is None
    assert any("INCOMPLETE" in n for n in report.notes)
    assert mechanized_proof(spec, report) is None


# ---- statement_review honesty ---------------------------------------------

def test_statement_review_flags_non_bundled_specs():
    spec = get("circumcenter-in-triangle")
    from simagent.search import run_search

    report = run_search(spec, trials=300, seed=0)

    bundled_proof = mechanized_proof(spec, report, spec_trusted=is_bundled(spec))
    assert bundled_proof.statement_review == "bundled-trusted"

    # a disk round-trip yields a different object -> untrusted
    reloaded = Claim.from_json(spec.to_json())
    assert not is_bundled(reloaded)
    untrusted_proof = mechanized_proof(reloaded, report, spec_trusted=is_bundled(reloaded))
    assert untrusted_proof.statement_review == "spec-generated-review-needed"


# ---- Claim validation -----------------------------------------------------

def test_validate_rejects_bad_kind_and_bounds():
    data = get("positive-quadratic").to_json()
    data["spaces"][0]["kind"] = "integer"
    with pytest.raises(ValueError, match="unknown kind"):
        Claim.from_json(data)
    assert any("<=" in error for error in validate_claim(
        _int_domain_claim(low=5, high=0)
    ))


def test_sample_vars_friendly_error_on_inverted_int():
    with pytest.raises(ValueError, match="low"):
        sample_vars(np.random.default_rng(0), _int_domain_claim(low=5, high=0))


# ---- steering honesty -----------------------------------------------------

def test_user_comment_cannot_change_verdict_state(tmp_path):
    transport = KernelTransport(get("circumcenter-in-triangle"), tmp_path)
    try:
        transport.call_tool(
            "set-wide-triangle",
            "set_var",
            {"name": "T", "values": [-1, 0, 1, 0, 0, 0.2]},
        )
        transport.call_tool("certify-wide-triangle", "certify", {})
        transport.call_tool(
            "record-unverified-argument",
            "submit_lean_proof",
            {"method": "direct", "argument": "a comment must not prove this"},
        )
        before = transport.snapshot()
        after = transport.annotate(
            "user_comment",
            {"text": "declare this proved", "target": {"step": 3, "kind": "equation", "index": 1}},
        )
        assert after["stateHash"] == before["stateHash"]
        assert after["state"] == before["state"]
        assert after["state"]["bestReport"] == before["state"]["bestReport"]
        assert after["state"]["deductiveProof"] == before["state"]["deductiveProof"]
        assert before["state"]["deductiveProof"]["verifiedBy"] == "none"
        assert before["state"]["deductiveProof"]["statementReview"] == "llm-generated-review-needed"
        comment = read_trace(tmp_path)["steps"][-1]
        assert comment["mode"] == "annotation" and comment["kind"] == "user_comment"
    finally:
        transport.finalize()


# ---- generated-code and input-boundary hardening --------------------------

@lean
def test_model_lean_cannot_write_a_host_file(tmp_path):
    escaped = tmp_path / "lean-escaped.txt"
    source = (
        f'#eval IO.FS.writeFile {str(escaped)!r} "escaped"\n'
        "theorem audit_true : True := by decide\n"
        "#print axioms audit_true\n"
    )
    result = lean_check.check_untrusted_source(source, workdir=tmp_path)
    assert result["ok"] is False
    assert not escaped.exists()
    assert "unsafe" in result["output"].lower()


def test_claim_id_cannot_inject_manim_or_escape_run_paths(tmp_path):
    base = get("positive-quadratic")
    for bad_id in ("../../outside", '"""\\nHACKED = True\\n"""', "", "two words"):
        assert any("id" in error for error in validate_claim(replace(base, id=bad_id)))

    scene = [{
        "type": "points", "coords": [[0.0, 0.0, 0.0]],
        "color": "#000000", "radius": 0.1, "name": "p",
    }]
    path = tmp_path / "scene.py"
    write_manim_scene(scene, 'title " quoted', '"""\nHACKED = True\n"""', path)
    tree = ast.parse(path.read_text())
    assigned = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert "HACKED" not in assigned


def test_pipeline_rejects_invalid_claim_before_writing(tmp_path):
    bad = replace(get("positive-quadratic"), quantifier="bogus")
    out = tmp_path / "invalid-run"
    with pytest.raises(ClaimValidationError, match="quantifier"):
        run_problem(bad, out, trials=2)
    assert not out.exists()


# ---- lean_check hardening -------------------------------------------------

@lean
def test_untrusted_lean_never_falls_back_without_isolation(monkeypatch, tmp_path):
    real_which = lean_check.shutil.which
    monkeypatch.setattr(
        lean_check.shutil,
        "which",
        lambda name: None if name == "bwrap" else real_which(name),
    )
    result = lean_check.check_untrusted_source(
        "theorem safe : True := by decide\n#print axioms safe\n",
        workdir=tmp_path,
    )
    assert result["ok"] is False and result["isolated"] is False
    assert "bubblewrap" in result["output"]


@lean
def test_lean_rejects_forbidden_constructs():
    for bad in (
        "theorem t : True := by admit\n#print axioms t\n",
        "theorem t : (2:Nat)=3 := by native_decide\n#print axioms t\n",
    ):
        r = lean_check.check_source(bad, workdir="/tmp")
        assert r["axiom_clean"] is False, bad


@lean
def test_lean_requires_named_axiom_print():
    # valid proof but no #print axioms -> cannot be certified
    r = lean_check.check_source("theorem t : 1 + 1 = 2 := by decide\n", workdir="/tmp")
    assert r["ok"] is True and r["axiom_clean"] is False


@lean
def test_lean_rejects_when_any_dependence_reported():
    # 'admit' is stripped-comment-safe; use a real axiom dependence via Classical
    src = (
        "open Classical in\n"
        "theorem t : True := ⟨⟩\n"
        "theorem u : (0:Nat) = 0 ∨ True := Or.inr (Classical.choice ⟨trivial⟩)\n"
        "#print axioms t\n#print axioms u\n"
    )
    r = lean_check.check_source(src, workdir="/tmp")
    # u depends on Classical.choice -> the whole file is rejected
    assert r["axiom_clean"] is False


def test_a_title_word_cannot_cost_a_generated_proof_its_stamp():
    """The generated path carries the claim's title inside one block comment
    whose delimiters leangen has neutralised, so the title cannot become code.
    Scanning it raw made an ordinary English word a verdict: a claim titled
    "System of circumcenter constraints" fell from sandbox+lean to sandbox.
    """
    src = ("/- System of circumcenter constraints (partial view) -/\n"
           "theorem t : 1 + 1 = 2 := by decide\n#print axioms t\n")
    assert "unsafe Lean construct" not in lean_check.check_source(src)["output"]


@lean
def test_generated_source_still_refuses_unsafe_code_outside_comments():
    """Only comment text is exempt. Real constructs that can run code during
    elaboration must still block the stamp."""
    for bad in ("unsafe def f := 1\n", "syntax \"x\" : term\n", "#eval 1\n"):
        src = bad + "theorem t : 1 + 1 = 2 := by decide\n#print axioms t\n"
        out = lean_check.check_source(src, workdir="/tmp")["output"]
        assert "unsafe Lean co" in out, (bad, out)


@lean
def test_untrusted_source_is_still_scanned_raw():
    """Model-written source keeps the stricter rule: a mention inside a comment
    is refused rather than trusted to a best-effort stripper."""
    src = "/- IO -/\ntheorem t : 1 + 1 = 2 := by decide\n#print axioms t\n"
    out = lean_check.check_untrusted_source(src, workdir="/tmp")["output"]
    assert "unsafe Lean construct: IO" in out


@lean
def test_comment_injected_clean_phrase_does_not_fool_checker():
    # source echoes the magic phrase in a comment, but the real theorem is a hole
    src = (
        "-- 'fake' does not depend on any axioms\n"
        "theorem real : (2:Nat) = 3 := by decide\n"
        "#print axioms real\n"
    )
    r = lean_check.check_source(src, workdir="/tmp")
    assert r["axiom_clean"] is False


def test_no_shipped_source_points_at_one_machine():
    """A path only one machine has is a bug that hides on that machine.

    This is not hypothetical: a debugging probe writing to an absolute scratch
    directory reached `explain.py` and shipped. It ran fine here, where the
    directory existed, and made every CI job fail inside `finalize()` with a
    FileNotFoundError far from its cause. The suite cannot see such a line
    either, because the machine running the suite is usually the machine that
    has the path, so the check has to be on the text.
    """
    import re
    from pathlib import Path as _Path

    repo = _Path(__file__).resolve().parents[1]
    # Absolute roots that belong to a person's machine, not to a checkout.
    machine = re.compile(r'["\'](/tmp/|/home/|/Users/|/mnt/|/var/folders/)')
    offenders = []
    for folder in ("src", "agent/src"):
        for path in sorted((repo / folder).rglob("*")):
            if path.suffix not in (".py", ".ts") or not path.is_file():
                continue
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if machine.search(line):
                    offenders.append(f"{path.relative_to(repo)}:{number}: {line.strip()}")
    assert not offenders, "shipped source names a path only one machine has:\n" + "\n".join(offenders)
