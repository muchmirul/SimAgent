"""The formalizer must be routed by pi, like everything else the model does.

SimAgent harnesses whatever model pi routes. That standard was true for agent
runs and false for the front door: formalization was pinned to one vendor's
SDK and one model id, so turning a conjecture into a Claim required a specific
provider even though running the Claim did not. These tests hold the door open,
offline: a fake pi client stands in for the service, so nothing here touches a
network.
"""
import json
from pathlib import Path

import pytest

from simagent import llm
from simagent.library import get


class FakePi:
    """Records the request and replays canned structured outputs."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.requests = []
        self.closed = False

    def structured(self, **kwargs):
        self.requests.append(kwargs)
        return {
            "provider": "somewhere",
            "model": "some-model",
            "output": self.outputs.pop(0),
        }

    def close(self):
        self.closed = True


def _triangle_claim_dump() -> dict:
    """A valid claim in ClaimModel's shape, taken from the bundled example."""
    data = get("circumcenter-in-triangle").to_json()
    data.pop("format", None)
    return data


def test_llm_imports_no_vendor_sdk():
    """A pinned SDK import is how the vendor lock comes back."""
    source = Path(llm.__file__).read_text()
    assert "import anthropic" not in source
    assert "anthropic.Anthropic" not in source


def test_no_model_is_pinned_by_default():
    """With nothing given, pi picks; a hard-coded id would override the operator."""
    assert llm.DEFAULT_MODEL is None
    assert llm.DEFAULT_PROVIDER is None


def test_formalize_asks_pi_and_validates_the_answer():
    pi = FakePi([_triangle_claim_dump()])
    claim = llm.formalize("circumcenter inside every triangle", client=pi, log=lambda *_: None)

    assert claim.id == "circumcenter-in-triangle"
    request = pi.requests[0]
    assert request["tool_name"] == "emit_claim"
    assert request["provider"] is None and request["model"] is None
    # The schema on the wire is the claim schema, so the shape is enforced by
    # the tool call rather than by hoping the model returns clean JSON.
    assert request["schema"]["properties"]["quantifier"] is not None
    assert not pi.closed, "a caller-owned client must outlive the call"


def test_formalize_repairs_with_the_validation_errors_quoted_back():
    broken = _triangle_claim_dump()
    broken["measure"] = {"kind": "no_such_measure"}
    pi = FakePi([broken, _triangle_claim_dump()])
    claim = llm.formalize("circumcenter inside every triangle", client=pi, log=lambda *_: None)

    assert claim.id == "circumcenter-in-triangle"
    assert len(pi.requests) == 2
    repair = pi.requests[1]["prompt"]
    assert "no_such_measure" in repair, "the model must see what it produced"
    assert "failed sandbox validation" in repair


def test_formalize_reports_a_routing_failure_instead_of_hiding_it():
    class Broken(FakePi):
        def structured(self, **kwargs):
            raise RuntimeError("no authenticated Pi model is available")

    with pytest.raises(llm.FormalizeError, match="no authenticated Pi model"):
        llm.formalize("x", client=Broken([]), log=lambda *_: None)


def test_proof_attempt_goes_through_the_same_route():
    pi = FakePi([{"method": "direct", "argument": "because", "lean_code": ""}])
    out = llm.attempt_proof(get("positive-quadratic"), {"verdict": "no_counterexample"}, client=pi)
    assert out["method"] == "direct"
    assert pi.requests[0]["tool_name"] == "emit_proof_attempt"
    assert json.loads(json.dumps(pi.requests[0]["schema"]))["properties"]["method"]


def test_no_vendor_sdk_is_a_dependency():
    """The vendor lock has to be gone from the install, not just the imports.

    A declared dependency on one provider's SDK says the tool needs that
    provider, which is exactly the claim this change removes.
    """
    import tomllib

    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    every = [*project["dependencies"], *sum(project.get("optional-dependencies", {}).values(), [])]
    assert not any("anthropic" in item for item in every), every


def test_the_client_the_formalizer_opens_itself_is_closed_again():
    """A leaked service process outlives the command that started it."""
    made = []

    def fake_factory(_root):
        client = FakePi([_triangle_claim_dump()])
        made.append(client)
        return client

    import simagent.pi_agent as pi_agent

    original = pi_agent.PiAgentClient
    pi_agent.PiAgentClient = fake_factory
    try:
        llm.formalize("a conjecture", log=lambda *_: None)
    finally:
        pi_agent.PiAgentClient = original
    assert len(made) == 1 and made[0].closed is True


def test_a_specific_model_is_passed_straight_through():
    pi = FakePi([_triangle_claim_dump()])
    llm.formalize("x", client=pi, provider="somewhere", model="some-model",
                  log=lambda *_: None)
    assert pi.requests[0]["provider"] == "somewhere"
    assert pi.requests[0]["model"] == "some-model"


def test_formalize_gives_up_with_the_last_errors_named():
    """A repair loop that ends in silence is one the caller cannot diagnose."""
    broken = _triangle_claim_dump()
    broken["measure"] = {"kind": "no_such_measure"}
    pi = FakePi([dict(broken) for _ in range(3)])
    with pytest.raises(llm.FormalizeError, match="no_such_measure"):
        llm.formalize("x", client=pi, max_repairs=2, log=lambda *_: None)
    assert len(pi.requests) == 3, "max_repairs=2 means three attempts in total"
