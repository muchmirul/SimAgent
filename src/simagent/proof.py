"""The proof kernel: what this harness is willing to call a proof.

Responsibility split: the LLM (or the human) reasons; the harness only records
what it can *execute or check*. Every answer names one of the ten
classical proof methods, and carries a `verified_by` stamp that only this
module assigns:

  "sandbox"        complete mechanical check by the harness itself
                   (exact rational arithmetic, or full enumeration)
  "sandbox+lean"   sandbox check AND a generated Lean certificate accepted by
                   the Lean kernel with no axioms
  "lean"           a Lean proof (e.g. LLM-written) accepted by the Lean
                   kernel; the *statement's* faithfulness to the conjecture
                   still needs human review
  "none"           an argument on record, nothing verified

Method taxonomy (the mechanized set is exactly what a simulation harness can
soundly establish on its own; every deductive method requires a proof
assistant, so those are Lean-or-nothing here):

  mechanized: counterexample, construction, exhaustion
  deductive:  direct, contradiction, contrapositive, induction, cases,
              combinatorial, infinite_descent
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

import sympy as sp

from . import lean_check
from .sandbox import certify as certify_mod
from .search import SearchReport
from .spec import ProblemSpec


class Method(str, Enum):
    DIRECT = "direct"
    CONTRADICTION = "contradiction"
    CONTRAPOSITIVE = "contrapositive"
    INDUCTION = "induction"
    CASES = "cases"
    CONSTRUCTION = "construction"
    COUNTEREXAMPLE = "counterexample"
    EXHAUSTION = "exhaustion"
    COMBINATORIAL = "combinatorial"
    INFINITE_DESCENT = "infinite_descent"


MECHANIZED: frozenset[Method] = frozenset(
    {Method.COUNTEREXAMPLE, Method.CONSTRUCTION, Method.EXHAUSTION}
)
DEDUCTIVE: frozenset[Method] = frozenset(Method) - MECHANIZED


@dataclass
class Proof:
    method: Method
    claim: str  # exactly what is proved (may be the negation, or a bounded form)
    verified_by: str  # "sandbox" | "sandbox+lean" | "lean" | "none"
    argument: str  # human-readable core of the argument
    witness: dict | None = None  # exact 'p/q' witness values, when witness-based
    lean_file: str | None = None
    lean_report: dict | None = None
    statement_review: str = "bundled-trusted"  # or "llm-generated-review-needed"

    def to_json(self) -> dict:
        d = asdict(self)
        d["method"] = self.method.value
        return d


def _exact_from_repr(rep) -> sp.Matrix | sp.Rational:
    """Parse the report's exact witness ('p/q' strings) back into sympy."""
    if isinstance(rep, str):
        return sp.Rational(rep)
    return sp.Matrix([[sp.Rational(x) for x in row] for row in rep])


def _attach_lean(proof: Proof, spec: ProblemSpec, report: SearchReport, out_dir) -> None:
    """Generate + kernel-check a Lean certificate, if the spec provides one.

    Only a clean, axiom-free `lean` run upgrades verified_by. Any failure
    leaves the sandbox verdict intact and records why.
    """
    comp = spec.compiled()
    if not comp.has_lean_certificate:
        return
    try:
        if report.exact_witness:
            exact = {k: _exact_from_repr(v) for k, v in report.exact_witness.items()}
            source = comp.lean_certificate(**exact)
        else:  # exhaustion-style certificate, no witness needed
            source = comp.lean_certificate()
    except Exception as e:  # noqa: BLE001 - generation failure must not hide the sandbox result
        proof.lean_report = {"available": None, "ok": False, "error": f"{type(e).__name__}: {e}"}
        return
    path = None
    if out_dir is not None:
        path = Path(out_dir) / "certificate.lean"
        path.write_text(source)
        proof.lean_file = str(path)
    result = lean_check.check_source(source, workdir=out_dir)
    proof.lean_report = result
    if result["ok"] and result["axiom_clean"]:
        proof.verified_by = "sandbox+lean"


def _margin_polynomial(spec) -> tuple | None:
    """The claim's margin as a symbolic polynomial, or None if it is not one.

    Only native `expr` claims with no recipe qualify: a derived entity has no
    symbolic form here, so its margin cannot be turned into a polynomial.
    """
    from .core import expr
    from .core.space import spaces_for

    measure = getattr(spec, "measure", None)
    if not isinstance(measure, dict) or measure.get("kind") != "expr":
        return None
    if getattr(spec, "recipe", None):
        return None
    try:
        shapes = {n: tuple(s.shape) for n, s in spaces_for(spec).items()}
        env = expr.symbol_env(shapes)
        poly = expr.evaluate(expr.parse(measure["margin"]), env, exact=True)
        # the claim's hypotheses, as polynomials assumed >= 0
        assumptions = [expr.evaluate(expr.parse(a), env, exact=True)
                       for a in getattr(spec, "assume", ())]
    except Exception:  # noqa: BLE001 - not a polynomial margin is a normal outcome
        return None
    used = set(poly.free_symbols).union(*[a.free_symbols for a in assumptions]) \
        if assumptions else set(poly.free_symbols)
    return poly, sorted(used, key=lambda s: s.name), assumptions


def _attach_sos_lean(proof: Proof, spec: ProblemSpec, cert: dict, out_dir) -> None:
    """Generate + kernel-check the sum-of-squares certificate.

    A direct proof is DEDUCTIVE, so the kernel's rule applies with no
    exception: Lean or nothing. Sympy having expanded the identity is not a
    verdict on its own.
    """
    from .sandbox import leangen

    theorem = re.sub(r"\W+", "_", f"{spec.id}_sos_certificate").strip("_")
    try:
        source = leangen.lean_sos(
            cert, theorem=theorem,
            title=f"Sum-of-squares certificate for: {spec.title}",
        )
    except Exception as e:  # noqa: BLE001
        proof.lean_report = {"available": None, "ok": False,
                             "error": f"{type(e).__name__}: {e}"}
        return
    if out_dir is not None:
        path = Path(out_dir) / "certificate.lean"
        path.write_text(source)
        proof.lean_file = str(path)
    result = lean_check.check_source(source, workdir=out_dir)
    proof.lean_report = result
    if result["ok"] and result["axiom_clean"]:
        proof.verified_by = "sandbox+lean"


def sos_proof(
    spec: ProblemSpec, report: SearchReport | None = None, out_dir=None,
    spec_trusted: bool = False, notes: list | None = None,
) -> Proof | None:
    """Prove a universal claim outright with a sum-of-squares certificate.

    This is the harness's only route to PROVING a `forall` over a continuous
    domain: search can refute one but never establish one. Returns None
    unless the certificate is strict (p >= eps > 0) AND the Lean kernel
    accepts it — fail closed at both steps.
    """
    from .sandbox import sos

    say = notes.append if notes is not None else (lambda _m: None)
    if getattr(spec, "quantifier", None) != "forall":
        say("a sum-of-squares certificate proves a 'forall' claim; this claim is not one")
        return None
    # A search is NOT a prerequisite: a certificate stands on its own, and
    # forcing hunt-then-prove would make the harness dictate the workflow.
    # A search that already found a counterexample is a real contradiction
    # and is the one case worth refusing.
    if report is not None and report.verdict not in ("no_counterexample", "no_witness"):
        say(f"the search verdict is {report.verdict!r}: settle that before trying to prove it")
        return None
    got = _margin_polynomial(spec)
    if got is None:
        say("the margin is not a symbolic polynomial in the free variables "
            "(an `expr` measure with no recipe is what this needs)")
        return None
    poly, symbols, assumptions = got
    hint = None
    if report is not None and report.margin_min is not None and report.margin_min > 0:
        hint = sp.Rational(report.margin_min).limit_denominator(64) / 2
    try:
        cert = sos.prove_positive(poly, symbols, eps_hint=hint,
                                  constraints=assumptions, notes=notes)
    except sos.SOSError as e:
        say(str(e))
        return None
    if cert is None:
        return None
    if not cert["strict"]:
        return None  # eps == 0 proves p >= 0, which does not settle a strict claim

    eps = cert["eps"]
    proof = Proof(
        method=Method.DIRECT,
        claim=spec.latex,
        verified_by="none",
        argument=(
            "The claim's margin is a polynomial, and it was written as a sum of "
            f"squares with nonnegative rational coefficients after subtracting {eps}. "
            "Every square is nonnegative at every real point, so the margin is at "
            f"least {eps} > 0 EVERYWHERE — a proof for all configurations, not "
            "evidence from samples.\n\n"
            "    " + sos.identity_text(cert) + "\n\n"
            "Expand the right-hand side and compare: that check settles the claim "
            "by hand, without Lean and without trusting this program. The identity "
            "was also expanded in exact rational arithmetic and re-checked by the "
            "Lean kernel."
        ),
        statement_review="bundled-trusted" if spec_trusted else "spec-generated-review-needed",
    )
    _attach_sos_lean(proof, spec, cert, out_dir)
    if proof.verified_by != "sandbox+lean":
        # deductive means Lean-or-nothing, with no exception for a certificate
        # sympy is happy with
        say("a sum-of-squares decomposition was found, but the Lean kernel did "
            f"not accept the certificate: {(proof.lean_report or {}).get('output', '')[:200]}")
        return None
    say(f"certificate accepted by the Lean kernel: margin >= {eps} everywhere")
    return proof


def cases_proof(
    spec: ProblemSpec, var: str, index: int, at, out_dir=None,
    spec_trusted: bool = False, notes: list | None = None,
) -> Proof | None:
    """Prove a claim by splitting its domain in two and certifying each half.

    The MODEL chooses where to split; the harness only executes the split and
    checks both halves. Splitting one coordinate at a value covers the whole
    domain (x_i <= at and x_i >= at overlap at the cut), so both certificates
    together settle the claim.
    """
    from .sandbox import leangen, sos

    say = notes.append if notes is not None else (lambda _m: None)
    got = _margin_polynomial(spec)
    if got is None:
        say("the margin is not a symbolic polynomial in the free variables")
        return None
    poly, symbols, assumptions = got
    name = f"{var}_{index}" if index is not None else var
    target = next((s_ for s_ in symbols if s_.name == name), None)
    if target is None:
        say(f"no free coordinate named {name!r} to split on; "
            f"the margin uses {[s_.name for s_ in symbols]}")
        return None
    cut = sp.Rational(sp.nsimplify(at, rational=True))
    halves = [(f"{name} >= {cut}", target - cut), (f"{name} <= {cut}", cut - target)]

    certs, hint = [], None
    for label, extra in halves:
        cert = sos.prove_positive(poly, symbols, eps_hint=hint,
                                  constraints=assumptions + [extra], notes=notes)
        if cert is None:
            say(f"no certificate for the half where {label}")
            return None
        if not cert["strict"]:
            say(f"the half where {label} is not STRICTLY positive (it touches "
                "equality), so a strict claim is not settled there")
            return None
        certs.append(cert)

    eps = min(c["eps"] for c in certs)
    proof = Proof(
        method=Method.CASES,
        claim=spec.latex,
        verified_by="none",
        argument=(
            f"The domain was split at {name} = {cut} into two cases that cover "
            "it, and each was certified separately: the margin is a sum of "
            "squares plus the case hypothesis times sums of squares, so it is "
            f"at least {eps} > 0 on each half, hence everywhere.\n\n"
            + "\n\n".join(
                f"    [{label}]  " + sos.identity_text(cert)
                for (label, _), cert in zip(halves, certs))
        ),
        statement_review="bundled-trusted" if spec_trusted else "spec-generated-review-needed",
    )
    theorem = re.sub(r"\W+", "_", f"{spec.id}_cases").strip("_")
    try:
        source = leangen.lean_sos_cases(
            certs, theorem=theorem,
            title=f"Proof by cases for: {spec.title}",
            case_notes=[label for label, _ in halves],
        )
    except Exception as e:  # noqa: BLE001
        proof.lean_report = {"available": None, "ok": False,
                             "error": f"{type(e).__name__}: {e}"}
        return None
    if out_dir is not None:
        path = Path(out_dir) / "certificate.lean"
        path.write_text(source)
        proof.lean_file = str(path)
    result = lean_check.check_source(source, workdir=out_dir)
    proof.lean_report = result
    if not (result["ok"] and result["axiom_clean"]):
        say("the Lean kernel did not accept both cases: "
            + str(result.get("output", ""))[:200])
        return None  # cases is deductive: Lean or nothing
    proof.verified_by = "sandbox+lean"
    say(f"both cases accepted by the Lean kernel: margin >= {eps} everywhere")
    return proof


def induction_proof(
    spec: ProblemSpec, out_dir=None, spec_trusted: bool = False,
    notes: list | None = None,
) -> Proof | None:
    """Prove an UNBOUNDED claim over the naturals by monotone induction.

    Base case: the margin is positive at the start. Step: the margin never
    decreases, certified for every n >= 0 at once by a sum-of-squares
    argument on margin(n+1) - margin(n). Together those give margin(n) >=
    margin(0) > 0 for every n, which no amount of enumeration could reach.
    """
    from .sandbox import leangen, sos

    say = notes.append if notes is not None else (lambda _m: None)
    got = _margin_polynomial(spec)
    if got is None:
        say("the margin is not a symbolic polynomial in the free variables")
        return None
    poly, symbols, assumptions = got
    if len(symbols) != 1:
        say(f"induction here needs exactly one variable to induct on; the margin "
            f"uses {[s_.name for s_ in symbols]}")
        return None
    n = symbols[0]
    base = sp.cancel(poly.subs({n: 0}))
    if not base.is_rational or base <= 0:
        say(f"the base case fails: the margin at {n.name} = 0 is {base}, "
            "which is not positive")
        return None
    step = sp.expand(poly.subs({n: n + 1}) - poly)
    cert = sos.find_sos(step, [n], constraints=assumptions + [n], notes=notes)
    if cert is None:
        say("the step case is not certifiable: the margin was not shown to be "
            f"non-decreasing in {n.name}")
        return None

    proof = Proof(
        method=Method.INDUCTION,
        claim=spec.latex,
        verified_by="none",
        argument=(
            f"Base case: the margin at {n.name} = 0 is {base} > 0. Step: the "
            f"increase margin({n.name}+1) - margin({n.name}) is a sum of squares "
            f"(using {n.name} >= 0), so the margin never decreases. By induction "
            f"it is at least {base} > 0 for every {n.name} >= 0 — an UNBOUNDED "
            "statement, which enumeration could never reach.\n\n"
            "    step increase: " + sos.identity_text(cert, margin_label="increase")
        ),
        statement_review="bundled-trusted" if spec_trusted else "spec-generated-review-needed",
    )
    theorem = re.sub(r"\W+", "_", f"{spec.id}_induction_step").strip("_")
    try:
        source = leangen.lean_sos(
            cert, theorem=theorem,
            title=(f"Induction step for: {spec.title} — the increase "
                   f"margin(n+1) - margin(n) is a sum of squares for n >= 0 "
                   f"(base case margin(0) = {base} > 0)"),
        )
    except Exception as e:  # noqa: BLE001
        proof.lean_report = {"available": None, "ok": False,
                             "error": f"{type(e).__name__}: {e}"}
        return None
    if out_dir is not None:
        path = Path(out_dir) / "certificate.lean"
        path.write_text(source)
        proof.lean_file = str(path)
    result = lean_check.check_source(source, workdir=out_dir)
    proof.lean_report = result
    if not (result["ok"] and result["axiom_clean"]):
        say("the Lean kernel did not accept the induction step")
        return None  # induction is deductive: Lean or nothing
    proof.verified_by = "sandbox+lean"
    say(f"induction step accepted by the Lean kernel; base case {base} > 0")
    return proof


def mechanized_proof(
    spec: ProblemSpec, report: SearchReport, out_dir=None, spec_trusted: bool = False
) -> Proof | None:
    """Build a Proof from a search/enumeration report — or refuse.

    Returns None whenever the report does not meet the kernel's bar
    (uncertified numeric findings and sampling evidence are not proofs).
    `spec_trusted` marks a bundled/reviewed spec; otherwise the Lean
    statement is spec-controlled and flagged for human review.
    """
    review = "bundled-trusted" if spec_trusted else "spec-generated-review-needed"
    proof: Proof | None = None
    if report.verdict == "counterexample" and report.certified:
        proof = Proof(
            method=Method.COUNTEREXAMPLE,
            claim=f"NOT[ {spec.latex} ]",
            verified_by="sandbox",
            argument=(
                "A single explicit instance violates the universally quantified "
                "statement. The instance was found by sandbox search, snapped to "
                "rational coordinates, and the violation re-decided in exact "
                "arithmetic."
            ),
            witness=report.exact_witness,
            statement_review=review,
        )
    elif report.verdict == "witness" and report.certified:
        proof = Proof(
            method=Method.CONSTRUCTION,
            claim=spec.latex,
            verified_by="sandbox",
            argument=(
                "The existential statement is proved by exhibiting an explicit "
                "rational instance and re-deciding the property in exact arithmetic."
            ),
            witness=report.exact_witness,
            statement_review=review,
        )
    elif report.verdict in ("holds_on_domain", "no_witness_on_domain") and report.certified:
        polarity = "holds" if report.verdict == "holds_on_domain" else "has no witness"
        proof = Proof(
            method=Method.EXHAUSTION,
            claim=f"{spec.latex}  (over the declared finite domain)",
            verified_by="sandbox",
            argument=(
                f"Every one of the {report.valid_trials} cases in the declared "
                f"finite domain was checked individually; the property {polarity} "
                "in all of them. This proves exactly the bounded statement — "
                "nothing beyond the domain."
            ),
            statement_review=review,
        )
    if proof is not None:
        _attach_lean(proof, spec, report, out_dir)
    return proof


def deductive_proof(
    spec: ProblemSpec,
    method: Method | str,
    argument: str,
    lean_code: str | None,
    out_dir=None,
    statement_review: str = "llm-generated-review-needed",
) -> Proof:
    """Record a deductive proof attempt; verified only if Lean accepts it.

    The harness never evaluates prose. Without Lean code — or with Lean code
    the kernel rejects — the attempt is stored with verified_by="none".
    """
    method = Method(method)
    proof = Proof(
        method=method,
        claim=spec.latex,
        verified_by="none",
        argument=argument,
        statement_review=statement_review,
    )
    if lean_code:
        path = None
        if out_dir is not None:
            path = Path(out_dir) / "proof_attempt.lean"
            path.write_text(lean_code)
            proof.lean_file = str(path)
        result = lean_check.check_source(lean_code, workdir=out_dir)
        proof.lean_report = result
        if result["ok"] and result["axiom_clean"]:
            proof.verified_by = "lean"
    return proof


def save_proof(proof: Proof, out_dir) -> str:
    path = Path(out_dir) / "proof.json"
    path.write_text(json.dumps(proof.to_json(), indent=2))
    return str(path)
