"""LLM formalizer: natural-language conjecture -> validated native Claim.

Since P5 the model composes from a CLOSED VOCABULARY — spaces, constructor
recipe, and registry keys — instead of emitting Python code strings (decision
D3: typed ops are safer and easier for the model than free code; the exec
path is deprecated). The output is validated against the sandbox
(`validate_claim`); failures are fed back for repair. Structured output keeps
the schema exact.

Routing: the request goes to whatever model pi routes, through the same
control service the agent runs use, so the front door is not pinned to one
vendor while the main hall is open to any. Pi owns provider auth; there is no
key handling here, and `--provider/--model` picks a specific model when you
want one. The reply is raw model output: `validate_claim` remains the gate.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
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

# No default model id: with none given, pi hands over its first authenticated
# model, exactly as an agent run does. A pinned id here would silently override
# whatever the operator authenticated.
DEFAULT_PROVIDER = os.environ.get("SIMAGENT_PROVIDER") or None
DEFAULT_MODEL = os.environ.get("SIMAGENT_MODEL") or None


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


def _ask(
    schema_model,
    *,
    system: str,
    prompt: str,
    tool_name: str,
    tool_description: str,
    provider: str | None,
    model: str | None,
    client=None,
) -> tuple[dict, str]:
    """One schema-shaped request through pi. Returns (output, "provider/model").

    The model is named back to the caller because SimAgent harnesses whichever
    one pi routes: a formalization nobody can attribute is not reproducible.
    """
    from .pi_agent import PiAgentClient

    owned = client is None
    talk = client or PiAgentClient(Path(tempfile.mkdtemp(prefix="simagent-formalize-")))
    try:
        reply = talk.structured(
            system=system,
            prompt=prompt,
            tool_name=tool_name,
            tool_description=tool_description,
            schema=schema_model.model_json_schema(),
            provider=provider,
            model=model,
        )
    except Exception as e:  # noqa: BLE001 - a routing failure must name itself
        raise FormalizeError(f"pi could not answer: {type(e).__name__}: {e}") from e
    finally:
        if owned:
            talk.close()
    return reply["output"], f"{reply['provider']}/{reply['model']}"


def claim_from_model_dump(data: dict) -> Claim:
    """ClaimModel dump -> native Claim (the claim/1 shape plus format key)."""
    return Claim.from_json({**data, "format": "claim/1"})


def formalize(
    conjecture_text: str,
    model: str | None = None,
    max_repairs: int = 2,
    log=print,
    provider: str | None = None,
    client=None,
) -> Claim:
    """Conjecture text -> validated native Claim (with a repair loop)."""
    prompt = f"Formalize this conjecture into a native Claim:\n\n{conjecture_text}"
    errors: list[str] = []
    for attempt in range(max_repairs + 1):
        claim_dict, who = _ask(
            ClaimModel,
            system=build_system_prompt(),
            prompt=prompt,
            tool_name="emit_claim",
            tool_description=(
                "Return the formalized claim. Every field is required unless the "
                "schema marks it optional, and every kind must be a registry key "
                "from the system prompt."
            ),
            provider=provider or DEFAULT_PROVIDER,
            model=model or DEFAULT_MODEL,
            client=client,
        )
        log(f"[llm] formalize attempt {attempt + 1} answered by {who}")
        try:
            claim = claim_from_model_dump(claim_dict)
            errors = validate_claim(claim)
        except Exception as e:  # noqa: BLE001 - malformed structure is a repairable error
            errors = [f"{type(e).__name__}: {e}"]
        if not errors:
            log(f"[llm] claim '{claim.id}' validated against the sandbox")
            return claim
        log(f"[llm] claim failed validation: {errors}")
        # One user turn per attempt: the previous answer is quoted back rather
        # than replayed as an assistant turn, so every provider sees the same
        # well-formed conversation.
        prompt = (
            f"Formalize this conjecture into a native Claim:\n\n{conjecture_text}\n\n"
            "Your previous attempt was:\n```json\n"
            + json.dumps(claim_dict, indent=2)
            + "\n```\n\nIt failed sandbox validation:\n- "
            + "\n- ".join(errors)
            + "\nReturn a corrected, complete claim (all fields, registry keys only)."
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


def attempt_proof(
    spec,
    report_json: dict,
    model: str | None = None,
    provider: str | None = None,
    client=None,
) -> dict:
    """One structured deductive proof attempt: {method, argument, lean_code}.

    The Lean code is checked by the kernel afterwards; nothing returned here
    is believed on its own.
    """
    output, _who = _ask(
        ProofAttemptModel,
        system=PROOF_SYSTEM,
        prompt=(
            "Claim:\n```json\n"
            + json.dumps(spec.to_json(), indent=2)
            + "\n```\n\nSearch report:\n```json\n"
            + json.dumps(report_json, indent=2)
            + "\n```"
        ),
        tool_name="emit_proof_attempt",
        tool_description="Return one deductive proof attempt for this claim.",
        provider=provider or DEFAULT_PROVIDER,
        model=model or DEFAULT_MODEL,
        client=client,
    )
    return output
