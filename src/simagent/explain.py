"""Say, in plain English, what the kernel actually established.

A verdict is a stamp and a witness is a list of fractions. Neither tells a
reader what happened, and asking them to reconstruct it from raw numbers is
asking them to do the harness's job: perception is calibrated compression, and
a number without its meaning is not compressed, only shortened.

So every result and every state carries an explanation built HERE, from kernel
state only: `proof.json`, the search report, and the per-step check the sandbox
recorded. Nothing in this module decides anything. `proof.py` remains the only
module that stamps `verified_by`; this one restates that stamp in words and can
never raise it.

One exception, stated so nobody has to discover it: `handoff_markdown` quotes
the strings the model itself supplied to `plan` and `expect`, because what a
run *declared it was doing* is part of the record the next run needs. They are
quoted as declarations, never as findings, and no branch here reads them.
"""
from __future__ import annotations

from typing import Any

# What each rung of the ladder MEANS, not just what it is called.
STAMP_WORDS = {
    "sandbox+lean": "the harness checked it in exact fractions AND the Lean "
                    "kernel accepted a generated certificate with no axioms",
    "sandbox": "exact fractions, checked by the harness — sound, but not "
               "independently re-checked by Lean",
    "lean": "a Lean proof the kernel accepted; whether the Lean statement says "
            "what you meant still needs a human",
    "none": "an argument on record, checked by nothing. Not a proof",
}

VERDICT_WORDS = {
    "counterexample": "the claim is FALSE, and here is the case that breaks it",
    "witness": "the claim is TRUE for at least one case, and here it is",
    "no_counterexample": "no case broke it. That is evidence, never a proof",
    "exhausted": "every case in a finite domain was checked",
    "incomplete": "the search could not finish, so nothing is settled",
}


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Read a field from either a dataclass or the JSON it was saved as.

    The CLI holds Proof and SearchReport objects; the notebook has only
    proof.json on disk. One reader for both keeps the explanation identical in
    both places, which matters: two wordings would be two claims.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _num(x: Any) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    if abs(v) >= 1000 or (v and abs(v) < 0.001):
        return f"{v:+.4g}"
    return f"{v:+.3f}"


def _point(vals: Any) -> str:
    if isinstance(vals, (list, tuple)) and vals and not isinstance(vals[0], (list, tuple)):
        return "(" + ", ".join(_num(v) for v in vals) + ")"
    if isinstance(vals, (int, float)):
        return _num(vals)  # a scalar is a number, not a raw float repr
    return str(vals)


def result_rows(spec, proof, report, final_check: dict | None = None) -> list[dict]:
    """Fact rows for the end of a run: label, value, and why it matters.

    Every row is read off kernel artifacts. A claim-specific row (the volume
    floor, say) appears only when the claim declares that constraint, because
    inventing a row the claim never made would be describing a different claim.
    """
    rows: list[dict] = []
    verdict = _get(report, "verdict")
    if verdict:
        rows.append({
            "label": "What was found",
            "value": verdict.replace("_", " "),
            "why": VERDICT_WORDS.get(verdict, "see the verdict line above"),
        })
    if proof is not None:
        stamp = _get(proof, "verified_by") or "none"
        rows.append({
            "label": "Verified by",
            "value": stamp,
            "why": STAMP_WORDS.get(stamp, "see ARCHITECTURE.md for the ladder"),
        })
        review = _get(proof, "statement_review")
        if review and review != "bundled-trusted":
            rows.append({
                "label": "Statement review",
                "value": review,
                "why": "the arithmetic is kernel-checked, but the Lean statement "
                       "came from an untrusted spec, so a human must confirm it "
                       "says what the conjecture says",
            })

    exact = _get(report, "exact_witness") or _get(proof, "witness")
    if exact:
        for name, rowsv in exact.items():
            rows.append({
                "label": f"The witness `{name}`",
                "value": "; ".join("(" + ", ".join(str(c) for c in r) + ")" for r in rowsv)
                         if rowsv and isinstance(rowsv[0], (list, tuple))
                         else ", ".join(str(c) for c in rowsv),
                "why": "exact fractions, not decimals, so no floating point is "
                       "trusted anywhere in the verdict",
            })

    data = (final_check or {}).get("data") or {}
    for name, value in data.items():
        rows.append({
            "label": f"Derived `{name}`",
            "value": _point(value),
            "why": "computed from the witness by the claim's own recipe",
        })

    margin = (final_check or {}).get("margin")
    if margin is None and report is not None:
        margin = (_get(report, "witness_check") or {}).get("margin")
    if margin is not None:
        holds = float(margin) > 0
        rows.append({
            "label": "Margin",
            "value": _num(margin),
            "why": ("positive, so the property HOLDS here" if holds
                    else "not positive, so the property FAILS here — and one "
                         "failing case is all a `for all` claim can survive"),
        })
    return rows


def result_summary(proof, report) -> str:
    """One paragraph: is this an answer, or is it evidence?"""
    stamp = _get(proof, "verified_by")
    verdict = _get(report, "verdict")
    if stamp in ("sandbox", "sandbox+lean"):
        lean = " and re-proved by the Lean kernel with no axioms" if stamp == "sandbox+lean" else ""
        return (
            "This is a real, checkable answer, not evidence. The witness is written "
            f"in exact fractions and the violation was re-decided in exact rational arithmetic{lean}, "
            "so nothing here rests on floating point."
        )
    if stamp == "lean":
        return (
            "The Lean kernel accepted the proof, so the arithmetic is settled. What is "
            "not settled is whether the Lean statement says what you meant: that still "
            "needs a human to read it."
        )
    if verdict == "no_counterexample":
        return (
            "Nothing was proved. The search looked and did not find a counterexample, "
            "which is evidence the claim may be true and nothing more. Proving a `for "
            "all` over a continuous domain needs a certificate, not a search."
        )
    return (
        "Nothing reached a kernel-grade result. Whatever was said above is narrative, "
        "and the harness does not grade narrative."
    )


ENDED_WORDS = {
    "finish": "The model called `finish`, so it decided the run was over.",
    "stop": "The run was stopped before the model called `finish`",
    "open": "The run ended without `finish` and without a stop, so nothing "
            "marked it complete.",
}


def _config_lines(config: dict | None) -> list[str]:
    """The exact coordinates the run stopped on, plus what the margin says."""
    lines: list[str] = []
    for name, value in ((config or {}).get("vars") or {}).items():
        rows = value if isinstance(value, (list, tuple)) else [value]
        if rows and isinstance(rows[0], (list, tuple)):
            lines.append(f"- `{name}` = " + "; ".join(_point(r) for r in rows))
        else:
            lines.append(f"- `{name}` = {_point(rows)}")
    check = (config or {}).get("check") or {}
    for name, value in (check.get("data") or {}).items():
        lines.append(f"- derived `{name}` = {_point(value)}")
    if check.get("error"):
        lines.append(f"- the configuration is degenerate here: {check['error']}")
    margin = check.get("margin")
    if margin is not None:
        state = "HOLDS" if float(margin) > 0 else "FAILS"
        lines.append(
            f"- margin = {_num(margin)}, so the property {state} at this configuration"
        )
    return lines or ["- the run recorded no configuration"]


def handoff_markdown(spec, proof, report, digest, *, config, ending,
                     provenance: str = "", refusals=()) -> str:
    """What one run leaves for whoever picks the claim up next.

    A run that hits its turn budget stops mid-thought: the model never writes a
    summary, and everything the kernel recorded sits in a journal that the next
    run cannot read. This restates that journal in English so work can continue
    from what was found rather than from nothing. Like everything else here it
    only RESTATES: it cannot stamp a verdict, and it never names a next move.
    """
    ending = ending or {}
    how = ENDED_WORDS.get(ending.get("by", "open"), ENDED_WORDS["open"])
    if ending.get("by") == "stop":
        how = f"{how}: {ending.get('note') or 'no reason recorded'}."

    out: list[str] = [
        f"# Handoff — {getattr(spec, 'title', '') or getattr(spec, 'id', 'run')}",
        "",
        "State this run reached, written from kernel records only. Nothing here "
        "is a verdict and nothing here says what to do next.",
        "",
    ]
    if provenance:
        out += [provenance, ""]
    for earlier in digest.get("continues") or []:
        # Without this the reader counts inherited steps as this run's work.
        out += [
            f"Continues `{earlier['run']}`: steps 1-{earlier['throughStep']} "
            f"below are that run's acts, replayed here exactly.",
            "",
        ]
    out += ["## How this run ended", "", how, ""]

    out += ["## What was established", "", result_summary(proof, report), ""]
    for row in digest.get("established") or []:
        out.append(f"- **{row['label']}**: {row['value']} — {row['why']}")
    out.append("")

    out += ["## Where the configuration stands", "", *_config_lines(config), ""]

    seen = digest.get("margin_seen")
    if seen:
        low, high = seen["lowest"], seen["highest"]
        out += [
            "## The margins this run actually saw",
            "",
            f"- lowest {_num(low['margin'])} at step {low['step']} (`{low['tool']}`)",
            f"- highest {_num(high['margin'])} at step {high['step']} (`{high['tool']}`)",
            "",
        ]

    plans = digest.get("approaches_declared") or []
    built = digest.get("constructed") or []
    predictions = digest.get("predictions") or {}
    scored = predictions.get("scored") or []
    still_open = predictions.get("still_open") or []
    tried: list[str] = []
    for plan in plans:
        tried.append(f"- declared `{plan['method']}`: {plan['idea']}")
    for entity in built:
        tried.append(f"- constructed `{entity['name']}` = {entity['ctor']}({', '.join(entity['args'])})")
    if scored:
        right = sum(1 for s in scored if s.get("ok"))
        tried.append(f"- {len(scored)} prediction(s) scored, {right} right")
        for s in scored:
            if not s.get("ok"):
                tried.append(
                    f"  - wrong: expected margin {s['relation']} {s['value']}, "
                    f"got {s['actual']}"
                )
    for s in still_open:
        tried.append(
            f"- prediction #{s['id']} is still open: margin {s['relation']} {s['value']}"
        )
    if tried:
        out += ["## What this run tried", "", *tried, ""]

    if refusals:
        out += [
            "## Where an instrument refused",
            "",
            "Each line is the instrument's own report of its limit, copied as it "
            "was recorded.",
            "",
        ]
        for refusal in refusals:
            out.append(f"- step {refusal['step']} `{refusal['tool']}`: {refusal['why']}")
        out.append("")

    out += [
        "## What is still open",
        "",
        f"{digest.get('steps_taken', 0)} step(s) are on record in `trace.jsonl`, "
        "and `kernel-journal.jsonl` replays every one of them exactly.",
        "",
    ]
    stamp = _get(proof, "verified_by") or "none"
    if stamp == "none":
        out.append(
            "No kernel-grade result was established, so the claim is exactly as "
            "open as it was before this run."
        )
    else:
        import os as _os_probe
        with open("/tmp/claude-1000/-mnt-Tforce-dev-SimAgent/b5b7447d-9a4c-4118-b355-d44a9d3528e3/scratchpad/BRANCH_HIT.txt", "a") as _fh:
            _fh.write(f"HIT stamp={stamp} pid={_os_probe.getpid()} test={_os_probe.environ.get('PYTEST_CURRENT_TEST','?')}\n")
        out.append(
            f"A `{stamp}` result is on record; {STAMP_WORDS.get(stamp, 'see ARCHITECTURE.md')}."
        )
    return "\n".join(out) + "\n"


def step_line(current: dict, previous: dict | None) -> str:
    """One sentence on what a single state actually did.

    Facts only: which variables moved, and what that did to the margin. The
    reader should never have to diff two lists of coordinates by eye.
    """
    tool = current.get("tool") or "narrative"
    check = current.get("check") or {}
    margin = check.get("margin")
    prev_margin = ((previous or {}).get("check") or {}).get("margin")

    changed = [c for c in (current.get("diff") or {}).get("changed", [])]
    where = ", ".join(
        (c["var"] if c.get("row") is None else f"{c['var']}[{c['row']}]") for c in changed
    )

    if previous is None:
        head = f"`{tool}` — the starting configuration"
    elif where:
        head = f"`{tool}` moved {where}"
    else:
        head = f"`{tool}` left the configuration where it was"

    if margin is None:
        return head + "."
    if prev_margin is None or prev_margin == margin:
        state = "holds" if float(margin) > 0 else "FAILS"
        return f"{head}; margin {_num(margin)}, so the property {state} here."

    delta = float(margin) - float(prev_margin)
    direction = "closer to breaking" if delta < 0 else "further from breaking"
    crossed = ""
    if float(prev_margin) > 0 >= float(margin):
        crossed = " This is the state that breaks the claim: the margin crossed zero."
    elif float(prev_margin) <= 0 < float(margin):
        crossed = " The margin came back above zero, so this state no longer breaks it."
    return (
        f"{head}; margin {_num(prev_margin)} → {_num(margin)}, "
        f"a move of {_num(delta)}, {direction}.{crossed}"
    )
