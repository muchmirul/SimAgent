"""LLM formalizer: natural-language conjecture -> validated native Claim.

Since P5 the model composes from a CLOSED VOCABULARY — spaces, constructor
recipe, and registry keys — instead of emitting Python code strings (decision
D3: typed ops are safer and easier for the model than free code; the exec
path is deprecated). The output is validated against the sandbox
(`validate_claim`); failures are fed back for repair. Structured output keeps
the schema exact.

Auth: the anthropic client resolves ANTHROPIC_API_KEY or an `ant auth login`
profile automatically — no key handling here.
"""
from __future__ import annotations

import json
import os
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from .core.claim import (
    CERTIFIERS,
    CONSTRAINTS,
    LEANS,
    MEASURES,
    SCENES,
    Claim,
    validate_claim,
)
from .core.derive import CONSTRUCTORS

DEFAULT_MODEL = os.environ.get("SIMAGENT_MODEL", "claude-opus-4-8")


# -- the structured-output schema (mirrors claim/1 JSON) -----------------------

class SpaceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    shape: list[int]
    low: float = -1.0
    high: float = 1.0
    kind: Literal["real", "int"] = "real"


class RecipeStepModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    ctor: str
    args: list[str]


class KindParamsModel(BaseModel):
    """A registry selection: kind + free-form params (validated in Python)."""
    model_config = ConfigDict(extra="allow")
    kind: str


class ClaimModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    conjecture: str
    latex: str
    quantifier: Literal["forall", "exists"]
    spaces: list[SpaceModel]
    recipe: list[RecipeStepModel] = []
    measure: KindParamsModel
    scene: KindParamsModel
    constraint: Optional[KindParamsModel] = None
    certify: Optional[KindParamsModel] = None
    lean: Optional[KindParamsModel] = None
    assume: list[str] = []
    lean_statement: str = ""
    notes: str = ""


def _registry_doc(name: str, registry: dict) -> str:
    lines = [f"### {name}"]
    for key, entry in registry.items():
        if "params" in entry:
            signature = ", ".join(entry["params"])
        else:  # constructors declare an arity, not named params
            signature = f"{entry['arity']} args"
        lines.append(f"- `{key}`({signature}) — {entry['doc']}")
    return "\n".join(lines)


def _example_claim_json() -> str:
    from .library import get

    return json.dumps(get("circumcenter-in-triangle").to_json(), indent=2)


def build_system_prompt() -> str:
    return f"""You are the formalization stage of SimAgent, a sandbox harness for
exploring math conjectures. Convert the user's conjecture into a native
Claim: free entities in Spaces, a recipe of constructions, and a distinguished
measure — ALL chosen from the closed registries below. You write NO code;
you compose vocabulary. If the conjecture cannot be expressed with these
registries, say so plainly in `notes` and pick the nearest faithful bounded
form (or fail honestly).

## Spaces (free entities)
Declare each with name, shape (e.g. [3, 2] = 3 points in R^2; [] = scalar),
bounds, kind. kind="real" = uniform box (sampled search); kind="int" =
integer grid — if EVERY variable is an int grid with a small case count the
harness checks every case (proof by exhaustion, its strongest move), so
prefer faithful finite integer forms when possible. Keep coordinates O(1).
Dimension is unrestricted (shape [5, 4] = 5 points in R^4 is fine); note
that above d = 3 no Lean certificate exists yet (say so in notes).

## Constructors (recipe steps; each defines a named derived entity)
{_registry_doc("constructors", CONSTRUCTORS)}

## Measures (the distinguished check; margin > 0 MUST mean the property holds)
{_registry_doc("measures", MEASURES)}

## Constraints (optional validity filter)
{_registry_doc("constraints", CONSTRAINTS)}

## Assumptions (`assume`: expressions the claim takes as >= 0)
Part of the STATEMENT, not a filter: write "for all positive x" as
assume ["P[0]"], and a triangle's side condition as
assume ["P[0] + P[1] - P[2]", ...]. They are the hypotheses a proof may use
as ingredients, so a conditional claim is provable only if you declare them.
Same expression language as the `expr` measure.

## Certifiers (optional; exact rational re-decision — provide when applicable,
it upgrades numeric findings into mathematical certificates)
{_registry_doc("certifiers", CERTIFIERS)}

## Lean hooks (optional; generated kernel certificates)
{_registry_doc("lean hooks", LEANS)}

## Scenes (how the claim renders)
{_registry_doc("scenes", SCENES)}

## Honesty
latex must faithfully state the conjecture. lean_statement is a Lean 4 /
Mathlib statement of the *positive* conjecture (the harness negates it if
disproved); if no clean formulation exists, say so in a Lean comment. Use
notes for caveats (discrete measures = evidence only; d > 3 = no Lean cert).

## Example claim (this exact JSON shape)
{_example_claim_json()}
"""


class FormalizeError(RuntimeError):
    pass


def _request_claim(client, model: str, messages: list[dict]) -> dict:
    """One structured-output request; parse() with a raw-schema fallback."""
    try:
        resp = client.messages.parse(
            model=model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=build_system_prompt(),
            messages=messages,
            output_format=ClaimModel,
        )
        if resp.stop_reason == "refusal":
            raise FormalizeError("model refused the formalization request")
        if resp.parsed_output is None:
            raise FormalizeError(f"no parsed output (stop_reason={resp.stop_reason})")
        return resp.parsed_output.model_dump()
    except (AttributeError, TypeError):
        schema = ClaimModel.model_json_schema()
        resp = client.messages.create(
            model=model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=build_system_prompt(),
            messages=messages,
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        if resp.stop_reason == "refusal":
            raise FormalizeError("model refused the formalization request")
        text = next(b.text for b in resp.content if b.type == "text")
        return json.loads(text)


def claim_from_model_dump(data: dict) -> Claim:
    """ClaimModel dump -> native Claim (the claim/1 shape plus format key)."""
    return Claim.from_json({**data, "format": "claim/1"})


def formalize(
    conjecture_text: str,
    model: str | None = None,
    max_repairs: int = 2,
    log=print,
) -> Claim:
    """Conjecture text -> validated native Claim (with a repair loop)."""
    import anthropic

    client = anthropic.Anthropic()
    model = model or DEFAULT_MODEL
    messages: list[dict] = [
        {
            "role": "user",
            "content": f"Formalize this conjecture into a native Claim:\n\n{conjecture_text}",
        }
    ]
    errors: list[str] = []
    for attempt in range(max_repairs + 1):
        log(f"[llm] formalize attempt {attempt + 1} (model={model})")
        claim_dict = _request_claim(client, model, messages)
        try:
            claim = claim_from_model_dump(claim_dict)
            errors = validate_claim(claim)
        except Exception as e:  # noqa: BLE001 - malformed structure is a repairable error
            errors = [f"{type(e).__name__}: {e}"]
        if not errors:
            log(f"[llm] claim '{claim.id}' validated against the sandbox")
            return claim
        log(f"[llm] claim failed validation: {errors}")
        messages.append({"role": "assistant", "content": json.dumps(claim_dict)})
        messages.append(
            {
                "role": "user",
                "content": (
                    "That claim failed sandbox validation:\n- "
                    + "\n- ".join(errors)
                    + "\nReturn a corrected, complete claim (all fields, registry keys only)."
                ),
            }
        )
    raise FormalizeError(f"claim failed validation after {max_repairs + 1} attempts: {errors}")


class ProofAttemptModel(BaseModel):
    """A deductive proof attempt. The harness checks the Lean; it never trusts prose."""

    model_config = ConfigDict(extra="forbid")
    method: Literal[
        "direct",
        "contradiction",
        "contrapositive",
        "induction",
        "cases",
        "construction",
        "counterexample",
        "exhaustion",
        "combinatorial",
        "infinite_descent",
    ]
    argument: str
    lean_code: Optional[str] = None


PROOF_SYSTEM = """You are the proof stage of SimAgent. Given a claim and
the sandbox search report, produce ONE proof attempt.

Rules (the harness enforces them; do not fight them):
- Pick exactly one classical method and name it in `method`. The sandbox has
  already exhausted the mechanized methods (counterexample / construction /
  exhaustion) — you are called because a deductive method is needed, so
  usually: direct, contradiction, contrapositive, induction, cases,
  combinatorial, or infinite_descent.
- `argument` is the honest human core of the proof — every step justified,
  no more certainty than the evidence supports.
- `lean_code`, if you can produce it, must be a SELF-CONTAINED Lean 4 CORE
  file: no imports, no Mathlib, no Batteries, no sorry. Prefer statements
  decidable by `decide` over Nat/Int (bounded quantifiers via `∀ n, n < N →`,
  explicit numerals, small recursive defs), and end with
  `#print axioms <theorem_name>` — the harness accepts the proof only if Lean
  exits cleanly and reports no axioms. If the theorem genuinely cannot be
  stated in core Lean, omit lean_code; your attempt will be recorded as
  unverified, which is the honest outcome."""


def attempt_proof(spec, report_json: dict, model: str | None = None) -> dict:
    """One structured deductive proof attempt: {method, argument, lean_code}."""
    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.parse(
        model=model or DEFAULT_MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=PROOF_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    "Claim:\n```json\n"
                    + json.dumps(spec.to_json(), indent=2)
                    + "\n```\n\nSearch report:\n```json\n"
                    + json.dumps(report_json, indent=2)
                    + "\n```"
                ),
            }
        ],
        output_format=ProofAttemptModel,
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise FormalizeError(f"no proof attempt (stop_reason={resp.stop_reason})")
    return resp.parsed_output.model_dump()
