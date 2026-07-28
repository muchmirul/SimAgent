"""The contract between what a person asked and what the harness will run.

A kernel can prove a generated Claim perfectly while that Claim says something
the user never asked. Nothing downstream can catch that: `verified_by` reports
how well the machine checked the Claim it was given, not whether the Claim is
the question. So the translation gets its own record and its own review.

This module holds no mathematics. It hashes the executable Claim, restates its
parts in plain English from the Claim's own fields, and records who translated
the text. Approval here confirms the TRANSLATION; it never touches a verdict.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

INTAKE_FILE = "intake.json"
INTAKE_FORMAT = "intake/1"

# What a review can say. "not-required" is for input that was never natural
# language (a bundled id or a hand-written spec): there is no translation to
# approve, so demanding approval would be theatre.
REVIEW_STATES = ("not-required", "pending", "approved")


def claim_hash(claim) -> str:
    """A stable fingerprint of the EXECUTABLE claim.

    Keyed on the claim's own JSON with sorted keys, so any change to a bound,
    an inequality, an assumption or the measure produces a different hash and
    invalidates an approval that was given for the old one.
    """
    payload = json.dumps(claim.to_json(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _space_line(name: str, space) -> str:
    shape = tuple(getattr(space, "shape", ()) or ())
    kind = getattr(space, "kind", "real")
    low, high = getattr(space, "low", None), getattr(space, "high", None)
    if not shape:
        what = "one number"
    elif len(shape) == 1:
        what = f"{shape[0]} numbers"
    else:
        what = f"{shape[0]} points in R^{shape[1]}"
    where = "" if low is None or high is None else f", each coordinate between {low} and {high}"
    grid = " (whole numbers only)" if kind == "int" else ""
    return f"{name}: {what}{where}{grid}"


def describe_claim(claim) -> list[dict[str, str]]:
    """Plain English for every part of the claim a person must approve.

    Each row is {label, value, why}: the value restates the claim's own field,
    and `why` says what that field decides about the run. Nothing here judges
    the mathematics or predicts an outcome.
    """
    rows: list[dict[str, str]] = []
    quantifier = getattr(claim, "quantifier", "")
    rows.append({
        "label": "Question",
        "value": claim.conjecture,
        "why": "the statement the harness will work on, as the formalizer wrote it",
    })
    rows.append({
        "label": "Quantifier",
        "value": quantifier,
        "why": ("'forall' means one bad case settles it against the claim; "
                "search can refute it but never prove it"
                if quantifier == "forall"
                else "'exists' means one good case settles it for the claim"),
    })
    spaces = getattr(claim, "spaces", {}) or {}
    rows.append({
        "label": "Domain",
        "value": "; ".join(_space_line(n, s) for n, s in spaces.items()) or "(none declared)",
        "why": "the only configurations that will ever be tried; outside these bounds nothing is checked",
    })
    assume = list(getattr(claim, "assume", []) or [])
    rows.append({
        "label": "Assumptions",
        "value": "; ".join(f"{a} >= 0" for a in assume) if assume else "(none)",
        "why": "hypotheses taken as given, so they narrow what the claim actually says",
    })
    constraint = getattr(claim, "constraint", None)
    rows.append({
        "label": "Validity filter",
        "value": json.dumps(constraint) if constraint else "(none)",
        "why": "configurations failing this are skipped as invalid rather than counted against the claim",
    })
    measure = getattr(claim, "measure", None) or {}
    rows.append({
        "label": "Margin",
        "value": json.dumps(measure) if measure else "(none)",
        "why": "the number whose sign decides the claim: margin > 0 means the property holds",
    })
    rows.append({
        "label": "Verification available",
        "value": _verification_line(claim),
        "why": "how strong a stamp this claim can earn at best, decided by what it declares",
    })
    notes = (getattr(claim, "notes", "") or "").strip()
    if notes:
        rows.append({
            "label": "Formalizer notes",
            "value": notes,
            "why": "caveats the translating model raised about its own translation",
        })
    return rows


def _verification_line(claim) -> str:
    """What checking this claim can reach, read off its own declarations."""
    has_certifier = bool(getattr(claim, "certify", None))
    has_lean = bool(getattr(claim, "lean", None))
    spaces = getattr(claim, "spaces", {}) or {}
    dims = [tuple(getattr(s, "shape", ()) or ()) for s in spaces.values()]
    over_d3 = any(len(sh) > 1 and sh[1] > 3 for sh in dims)
    parts = []
    parts.append("exact rational certification" if has_certifier
                 else "no exact certifier declared, so findings stay numeric")
    if has_lean and not over_d3:
        parts.append("a Lean kernel certificate is possible")
    elif has_lean and over_d3:
        parts.append("a Lean hook is declared but no certificate exists above dimension 3")
    else:
        parts.append("no Lean hook declared")
    return "; ".join(parts)


@dataclass
class Intake:
    """One recorded translation from a person's words to an executable Claim."""

    source_text: str
    source_kind: str            # "conjecture" | "spec-file" | "bundled"
    claim_json: dict
    claim_hash: str
    formalizer: str = ""        # "provider/model", empty when nothing translated
    validation: list[str] = field(default_factory=list)  # errors; empty = clean
    review_state: str = "not-required"
    approved_hash: str = ""
    description: list[dict[str, str]] = field(default_factory=list)

    @property
    def approved(self) -> bool:
        """True only while the approval still matches the executable claim.

        A re-formalized or edited claim changes the hash, so an old approval
        stops counting on its own rather than needing to be revoked.
        """
        return self.review_state == "approved" and self.approved_hash == self.claim_hash

    @property
    def needs_approval(self) -> bool:
        return self.review_state != "not-required" and not self.approved

    def to_json(self) -> dict[str, Any]:
        return {
            "format": INTAKE_FORMAT,
            "source_text": self.source_text,
            "source_kind": self.source_kind,
            "formalizer": self.formalizer,
            "claim_hash": self.claim_hash,
            "validation": self.validation,
            "review_state": self.review_state,
            "approved_hash": self.approved_hash,
            "description": self.description,
            "claim": self.claim_json,
        }

    def save(self, out_dir: str | Path) -> Path:
        path = Path(out_dir) / INTAKE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=2), encoding="utf-8")
        return path

    @classmethod
    def from_json(cls, data: dict) -> "Intake":
        if data.get("format") != INTAKE_FORMAT:
            raise ValueError(f"not a {INTAKE_FORMAT} document")
        return cls(
            source_text=data["source_text"],
            source_kind=data["source_kind"],
            claim_json=data["claim"],
            claim_hash=data["claim_hash"],
            formalizer=data.get("formalizer", ""),
            validation=list(data.get("validation", [])),
            review_state=data.get("review_state", "not-required"),
            approved_hash=data.get("approved_hash", ""),
            description=list(data.get("description", [])),
        )

    @classmethod
    def load(cls, out_dir: str | Path) -> "Intake":
        path = Path(out_dir)
        if path.is_dir():
            path = path / INTAKE_FILE
        return cls.from_json(json.loads(path.read_text(encoding="utf-8")))

    def approve(self, given_hash: str) -> None:
        """Record human approval of one exact claim.

        The hash must be supplied and must match, because approving whatever is
        currently on disk would approve a claim the person may never have read.
        """
        if given_hash != self.claim_hash:
            raise ValueError(
                f"approval is for claim {given_hash[:12]}… but this run's claim is "
                f"{self.claim_hash[:12]}…; re-read the claim before approving it"
            )
        self.review_state = "approved"
        self.approved_hash = given_hash


def record(claim, source_text: str, source_kind: str, *, formalizer: str = "",
           validation: list[str] | None = None) -> Intake:
    """Build the intake record for one claim about to be run."""
    return Intake(
        source_text=source_text,
        source_kind=source_kind,
        claim_json=claim.to_json(),
        claim_hash=claim_hash(claim),
        formalizer=formalizer,
        validation=list(validation or []),
        # Only natural language was translated by a model, so only natural
        # language has a translation to review.
        review_state="pending" if source_kind == "conjecture" else "not-required",
        description=describe_claim(claim),
    )


PENDING_DIR = ".pending-claims"


def save_pending(intake: Intake, root: str | Path = "runs") -> Path:
    """Keep a claim that was shown to a human and is waiting for their yes.

    Formalizing is a model call and is NOT deterministic: the same sentence
    yields a differently worded claim next time, with a different hash. If
    approving re-formalized, the hash could never match and the gate would be
    unpassable, so the claim the person actually read is stored under its own
    hash and loaded back by it.
    """
    directory = Path(root) / PENDING_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{intake.claim_hash}.json"
    path.write_text(json.dumps(intake.to_json(), indent=2), encoding="utf-8")
    return path


def load_pending(claim_hash: str, root: str | Path = "runs") -> Intake | None:
    path = Path(root) / PENDING_DIR / f"{claim_hash}.json"
    if not path.is_file():
        return None
    try:
        return Intake.from_json(json.loads(path.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001 - an unreadable record is simply not a match
        return None


def render_text(intake: Intake) -> str:
    """The intake as a person reads it before approving or refusing."""
    lines = [
        "What you asked:",
        f"  {intake.source_text.strip() or '(no source text recorded)'}",
        "",
        f"Translated by: {intake.formalizer or 'nothing (no model translated this)'}",
        f"Claim hash: {intake.claim_hash}",
        "",
        "What the harness will actually run:",
    ]
    for row in intake.description:
        lines.append(f"  {row['label']}: {row['value']}")
        lines.append(f"      ({row['why']})")
    if intake.validation:
        lines.append("")
        lines.append("Validation errors:")
        lines.extend(f"  - {e}" for e in intake.validation)
    lines.append("")
    lines.append(f"Review state: {intake.review_state}"
                 + ("" if not intake.needs_approval else " — approval required before an agent may run"))
    return "\n".join(lines)
