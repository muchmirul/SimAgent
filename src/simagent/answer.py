"""Turn a search report into human/mathematical outputs.

Three artifacts, honest about their epistemic status:
  answer.md        — readable summary of what the machine actually established
  answer.tex       — classical write-up (statement, verdict, witness, method)
  conjecture.lean  — Lean 4 skeleton (statement or its negation + witness);
                     always flagged unchecked unless a Lean toolchain verified it
"""
from __future__ import annotations

import re
from pathlib import Path

from . import explain
from .search import SearchReport
from .spec import ProblemSpec

_VERDICT_TEXT = {
    ("counterexample", True): "DISPROVED — certified counterexample (exact rational arithmetic)",
    ("counterexample", False): "counterexample candidate (numeric only; certification failed)",
    ("counterexample", None): "counterexample candidate (numeric; no exact certifier on spec)",
    ("witness", True): "EXISTENCE ESTABLISHED — certified witness (exact rational arithmetic)",
    ("witness", False): "witness candidate (numeric only; certification failed)",
    ("witness", None): "witness candidate (numeric; no exact certifier on spec)",
    ("holds_on_domain", True): "PROVED on the declared finite domain — every case checked",
    ("no_witness_on_domain", True): "DISPROVED on the declared finite domain — every case checked, no witness",
    ("no_counterexample", None): "no counterexample found — evidence for the conjecture, not a proof",
    ("no_witness", None): "no witness found — evidence against existence, not a disproof",
}


def verdict_text(report: SearchReport, proof=None) -> str:
    """The one upgrade allowed here: 'no counterexample found' is evidence
    until a kernel-checked proof exists, and then it is a proof. The upgrade
    is driven by proof.verified_by, which only proof.py ever sets."""
    if (report.verdict in ("no_counterexample", "no_witness")
            and proof is not None and proof.verified_by in ("sandbox+lean", "lean")):
        return (f"PROVED for every configuration — {proof.method.value} proof, "
                "checked by the Lean kernel")
    key = (report.verdict, report.certified)
    return _VERDICT_TEXT.get(key, _VERDICT_TEXT.get((report.verdict, None), report.verdict))


def _lean_ident(s: str) -> str:
    ident = re.sub(r"[^0-9a-zA-Z_]", "_", s)
    return ident if ident and not ident[0].isdigit() else f"p_{ident}"


def _witness_rows(report: SearchReport) -> dict[str, list[list[str]]]:
    """name -> matrix of printable entries (exact 'p/q' if certified, else floats)."""
    out: dict[str, list[list[str]]] = {}
    source = report.exact_witness if report.exact_witness else report.witness
    if not source:
        return out
    for name, val in source.items():
        if isinstance(val, str):
            out[name] = [[val]]
            continue
        rows = val if (val and isinstance(val[0], list)) else [val]
        out[name] = [
            [x if isinstance(x, str) else f"{float(x):.4f}" for x in row] for row in rows
        ]
    return out


def _md_witness(report: SearchReport) -> str:
    rows = _witness_rows(report)
    if not rows:
        return ""
    lines = []
    exact = bool(report.exact_witness)
    lines.append(f"**Witness** ({'exact rationals' if exact else 'floating point'}):\n")
    for name, mat in rows.items():
        lines.append(f"- `{name}` =")
        for row in mat:
            lines.append(f"    - ({', '.join(row)})")
    return "\n".join(lines) + "\n"


def _proof_lines(proof) -> list[str]:
    if proof is None:
        return [
            "**Proof method:** none — the result above is evidence, not a proof. "
            "Closing it needs one of the deductive methods (direct, contradiction, "
            "contrapositive, induction, cases, combinatorial, infinite descent), "
            "checked in Lean.",
            "",
        ]
    lines = [
        f"**Proof method:** {proof.method.value.replace('_', ' ')}",
        f"**Verified by:** {proof.verified_by}",
        f"**Claim proved:** {proof.claim}",
        "",
        proof.argument,
        "",
    ]
    if proof.lean_file:
        checked = bool(proof.lean_report and proof.lean_report.get("ok"))
        axioms = bool(proof.lean_report and proof.lean_report.get("axiom_clean"))
        lines.append(
            f"Lean certificate: `{Path(proof.lean_file).name}` — "
            + (
                "accepted by the Lean kernel, axiom-free."
                if checked and axioms
                else f"NOT verified ({(proof.lean_report or {}).get('output', 'no toolchain')[:200]})"
            )
        )
        lines.append("")
    if proof.statement_review != "bundled-trusted":
        lines.append(
            "> Statement review needed: the Lean statement was machine-generated "
            "from an untrusted source; check it says what the conjecture says."
        )
        lines.append("")
    return lines


def _dim_cap_notice(spec, proof) -> list[str]:
    """The D6 honesty line: above d = 3 no Lean certificate is generated —
    say so explicitly wherever a verdict is presented."""
    dims = [list(v.shape)[-1] if list(v.shape) else 0 for v in getattr(spec, "domain", [])]
    if max(dims, default=0) <= 3:
        return []
    if proof is not None and "lean" in (proof.verified_by or ""):
        return []
    return [
        "> **Dimension note:** this claim lives above ℝ³. No Lean certificate is "
        "generated above d = 3 (the certificate encoding caps there), so the "
        "strongest available verdict is exact rational arithmetic "
        "(`verified_by: sandbox`). This is stated rather than hidden.",
        "",
    ]


def write_markdown(spec: ProblemSpec, report: SearchReport, path: Path, proof=None) -> None:
    check = report.witness_check or {}
    lines = [
        f"# {spec.title}",
        "",
        f"**Conjecture.** {spec.conjecture}",
        "",
        f"$${spec.latex}$$",
        "",
        f"## Verdict: {verdict_text(report, proof)}",
        "",
        *_dim_cap_notice(spec, proof),
        *_proof_lines(proof),
        _md_witness(report),
    ]
    if check:
        lines += [f"Witness check: holds={check.get('holds')} margin={check.get('margin')}", ""]
        if check.get("data"):
            lines += ["```json", str(check["data"]), "```", ""]
    # In plain English, before the method section: a reader must not have to
    # reconstruct what happened from a stamp and a list of fractions.
    rows = explain.result_rows(spec, proof, report, check)
    if rows:
        lines += ["## What this means", "", "| | | |", "|---|---|---|"]
        lines += [f"| {r['label']} | {r['value']} | {r['why']} |" for r in rows]
        lines += ["", explain.result_summary(proof, report), ""]
    lines += [
        "## Method",
        "",
        f"- Sandbox search over the declared domain: {report.trials} trials "
        f"({report.valid_trials} valid), seed {report.seed}, "
        f"{report.refine_steps} annealing steps.",
    ]
    if report.margin_min is not None:
        lines.append(f"- Observed margin range: [{report.margin_min:.4f}, {report.margin_max:.4f}].")
    for note in report.notes:
        lines.append(f"- {note}")
    if spec.notes:
        lines += ["", f"> Spec notes: {spec.notes}"]
    path.write_text("\n".join(lines) + "\n")


def _tex_escape(s: str) -> str:
    return re.sub(r"([&%#_{}])", r"\\\1", s)


def _tex_matrix(mat: list[list[str]]) -> str:
    body = r" \\ ".join(" & ".join(_tex_escape(x) if "/" not in x else x for x in row) for row in mat)
    return r"\begin{pmatrix}" + body + r"\end{pmatrix}"


def write_latex(spec: ProblemSpec, report: SearchReport, path: Path, proof=None) -> None:
    rows = _witness_rows(report)
    witness_tex = ""
    if rows:
        kind = "exact rational coordinates" if report.exact_witness else "floating-point coordinates"
        parts = [rf"{_tex_escape(name)} = {_tex_matrix(mat)}" for name, mat in rows.items()]
        witness_tex = (
            rf"\paragraph{{Witness ({kind}).}}" + "\n" + r"\[" + r",\qquad ".join(parts) + r"\]"
        )
    method = (
        f"Sandbox search over the declared domain: {report.trials} random trials "
        f"({report.valid_trials} valid, seed {report.seed}) followed by "
        f"{report.refine_steps} margin-guided annealing steps. "
    )
    if report.certified:
        method += (
            "The candidate was snapped to rational coordinates and the property was "
            "re-decided with exact arithmetic (sympy), so the verdict is a certificate, "
            "not a numerical observation. "
        )
    notes = " ".join(_tex_escape(n) for n in report.notes)
    content = rf"""\documentclass[11pt]{{article}}
\usepackage{{amsmath, amssymb}}
\usepackage[margin=1in]{{geometry}}
\title{{{_tex_escape(spec.title)}}}
\author{{SimAgent}}
\date{{\today}}
\begin{{document}}
\maketitle

\paragraph{{Conjecture.}} {_tex_escape(spec.conjecture)}
\[
{spec.latex}
\]

\paragraph{{Verdict.}} \textbf{{{_tex_escape(verdict_text(report, proof))}}}

{_proof_tex(proof)}

{witness_tex}

\paragraph{{Method.}} {method} {notes}

\paragraph{{Status.}} Machine-generated by the SimAgent sandbox harness. A Lean
skeleton accompanies this document (\texttt{{conjecture.lean}}); it is unchecked
unless a Lean toolchain has verified it.

\end{{document}}
"""
    path.write_text(content)


def _proof_tex(proof) -> str:
    if proof is None:
        return (
            r"\paragraph{Proof method.} None --- the verdict above is evidence, "
            r"not a proof; a deductive method checked in Lean is still required."
        )
    method = _tex_escape(proof.method.value.replace("_", " "))
    lean_note = ""
    if proof.lean_file:
        ok = bool(proof.lean_report and proof.lean_report.get("ok") and proof.lean_report.get("axiom_clean"))
        lean_note = (
            " A Lean certificate accompanies this document and was accepted by the "
            "Lean kernel with no axioms."
            if ok
            else " A Lean certificate accompanies this document but has NOT been verified."
        )
    return (
        rf"\paragraph{{Proof method.}} Proof by \textbf{{{method}}}, verified by "
        rf"\texttt{{{_tex_escape(proof.verified_by)}}}. {_tex_escape(proof.argument)}{lean_note}"
    )


def _lean_witness_comment(report: SearchReport) -> str:
    rows = _witness_rows(report)
    if not rows:
        return ""
    lines = ["-- Witness found by SimAgent:" if report.exact_witness else "-- Numeric witness (uncertified):"]
    for name, mat in rows.items():
        for i, row in enumerate(mat):
            lines.append(f"--   {name}[{i}] = ({', '.join(row)})")
    return "\n".join(lines)


def write_lean(spec: ProblemSpec, report: SearchReport, path: Path, proof=None) -> None:
    ident = _lean_ident(spec.id)
    stmt = spec.lean_statement.strip() or "True  -- TODO: formal statement"
    cert_note = ""
    if proof is not None and proof.lean_file and proof.verified_by.endswith("lean"):
        cert_note = (
            f"   A kernel-checked, axiom-free certificate of the verdict lives in\n"
            f"   {Path(proof.lean_file).name} (Lean core, `decide`). This file is the\n"
            f"   Mathlib-flavoured statement of the same result, left as an exercise\n"
            f"   in connecting the two formulations.\n"
        )
    header = (
        f"/- Auto-generated by SimAgent — Mathlib-flavoured skeleton (UNCHECKED).\n"
        f"   Problem: {spec.title}\n"
        f"   Verdict: {verdict_text(report, proof)}\n"
        f"{cert_note}-/\n"
        "import Mathlib\n"
    )
    witness = _lean_witness_comment(report)
    if spec.quantifier == "forall" and report.verdict == "counterexample":
        body = (
            f"{witness}\n"
            f"-- The original conjecture is false; prove its negation from the witness\n"
            f"-- (route: plug in the rational witness, decide by norm_num).\n"
            f"theorem {ident}_disproved :\n"
            f"    ¬ ({stmt}) := by\n"
            f"  sorry\n"
        )
    elif spec.quantifier == "exists" and report.verdict == "witness":
        body = (
            f"{witness}\n"
            f"theorem {ident} :\n"
            f"    {stmt} := by\n"
            f"  sorry\n"
        )
    else:
        body = (
            f"-- Search evidence only ({report.valid_trials} valid trials, no decisive instance).\n"
            f"theorem {ident} :\n"
            f"    {stmt} := by\n"
            f"  sorry\n"
        )
    path.write_text(header + "\n" + body)


def write_answers(spec: ProblemSpec, report: SearchReport, out_dir, proof=None) -> dict[str, str]:
    out = Path(out_dir)
    md, tex, lean = out / "answer.md", out / "answer.tex", out / "conjecture.lean"
    write_markdown(spec, report, md, proof=proof)
    write_latex(spec, report, tex, proof=proof)
    write_lean(spec, report, lean, proof=proof)
    return {"answer_md": str(md), "answer_tex": str(tex), "lean": str(lean)}
