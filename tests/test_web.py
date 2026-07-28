import json

import numpy as np
import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from simagent.library import get  # noqa: E402
from simagent.web import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app = create_app(out_root=str(tmp_path))
    with fastapi_testclient.TestClient(app) as c:
        yield c


def test_problems_and_static(client):
    r = client.get("/api/problems")
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()}
    assert "circumcenter-in-tetrahedron" in ids
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/three.module.min.js").status_code == 200


def test_state_requires_load(client):
    assert client.get("/api/state").status_code == 409


def test_load_rejects_an_invalid_claim_as_input(client, tmp_path):
    data = get("positive-quadratic").to_json()
    data["quantifier"] = "bogus"
    path = tmp_path / "bad-claim.json"
    path.write_text(json.dumps(data))
    response = client.post("/api/load", json={"spec_path": str(path)})
    assert response.status_code == 422
    assert "quantifier" in response.text


def test_load_set_and_check(client):
    st = client.post("/api/load", json={"problem_id": "circumcenter-in-triangle"}).json()
    assert st["spec"]["id"] == "circumcenter-in-triangle"
    assert np.array(st["vars"]["T"]).shape == (3, 2)
    assert st["scene"], "scene graph must not be empty"

    st2 = client.post("/api/set", json={"name": "T", "row": 0, "values": [0.9, 0.9]}).json()
    assert st2["vars"]["T"][0] == [0.9, 0.9]
    assert "holds" in st2["check"]

    assert client.post("/api/set", json={"name": "nope", "values": [1]}).status_code == 422


def test_hunt_and_certify(client):
    client.post("/api/load", json={"problem_id": "circumcenter-in-triangle"})
    r = client.post("/api/hunt", json={"trials": 300}).json()
    assert r["result"]["verdict"] == "counterexample"
    assert r["result"]["loaded_witness"] is True
    assert r["state"]["check"]["holds"] is False

    c = client.post("/api/certify").json()
    assert c["holds"] is False
    assert c["certified"] is True
    assert c["exact"] is not None


def test_manim_endpoint_graceful_or_job(client, monkeypatch):
    # Force the unavailable path so the test is env-independent and never renders.
    import simagent.web.app as web_app

    monkeypatch.setattr(web_app, "manim_available", lambda: False)
    client.post("/api/load", json={"problem_id": "circumcenter-in-triangle"})
    r = client.post("/api/manim", json={"video": False}).json()
    assert r["available"] is False and r["job"] is None


def test_the_notebook_will_not_start_an_agent_on_an_unapproved_claim(client, monkeypatch):
    """Same gate as the CLI, over HTTP: a translated question must be read and
    accepted before an agent settles it, because the harness cannot tell a
    faithful translation from a nearby one."""
    from simagent.library import get
    from simagent.llm import Formalization

    claim = get("positive-quadratic")
    monkeypatch.setattr(
        "simagent.llm.formalize_recorded",
        lambda text, **kw: Formalization(claim=claim, source_text=text,
                                         formalizer="faux/model", attempts=1),
    )
    # No pi service is stubbed on purpose: the gate must refuse before the
    # control plane is ever reached, so an unapproved claim cannot even start.
    r = client.post("/api/agent/start", json={"conjecture": "is x^2 + 1 positive?"})
    assert r.status_code == 428
    body = r.json()["detail"]
    assert body["error"] == "claim_approval_required"
    assert body["formalizer"] == "faux/model"
    assert body["source_text"] == "is x^2 + 1 positive?"
    # the caller is shown what it is approving, not just a hash
    labels = {row["label"] for row in body["description"]}
    assert {"Question", "Domain", "Margin"} <= labels

    stale = client.post("/api/agent/start",
                        json={"conjecture": "is x^2 + 1 positive?",
                              "approve_claim_hash": "0" * 64})
    assert stale.status_code == 409


def test_a_refusal_reaches_the_notebook_as_a_refusal(client, monkeypatch):
    """Not a 500: the service worked, the conjecture is out of vocabulary."""
    from simagent.llm import FormalizeRefused

    def refuse(text, **kw):
        raise FormalizeRefused("no Space expresses that", "faux/model")

    monkeypatch.setattr("simagent.llm.formalize_recorded", refuse)
    r = client.post("/api/agent/start", json={"conjecture": "every graph is planar"})
    assert r.status_code == 422
    assert r.json()["detail"]["reason"] == "no Space expresses that"


def test_approving_a_claim_does_not_re_formalize_it(client, monkeypatch):
    """The gate has to be passable.

    Formalizing is a model call and is not deterministic. If the approval
    request re-formalizes, the second claim differs from the one the user read,
    its hash never matches, and the run can never start: a gate nobody can pass
    is worse than no gate, because the user routes around it.
    """
    from simagent.library import get
    from simagent.llm import Formalization

    calls = []
    variants = [get("positive-quadratic"), get("sum-of-squares-vs-linear")]

    def drifting(text, **kw):
        # a different claim every call, like a real model on a real day
        claim = variants[min(len(calls), len(variants) - 1)]
        calls.append(text)
        return Formalization(claim=claim, source_text=text,
                             formalizer="faux/model", attempts=1)

    monkeypatch.setattr("simagent.llm.formalize_recorded", drifting)

    first = client.post("/api/agent/start", json={"conjecture": "is it positive?"})
    assert first.status_code == 428
    shown = first.json()["detail"]["claim_hash"]
    assert len(calls) == 1

    second = client.post("/api/agent/start",
                         json={"conjecture": "is it positive?",
                               "approve_claim_hash": shown})
    # It must NOT be a 409 hash mismatch: the approved claim is the one shown.
    assert second.status_code != 409, second.json()
    assert len(calls) == 1, "approval re-ran the formalizer and got a different claim"


def test_a_formalizer_that_breaks_is_not_an_internal_server_error(client, monkeypatch):
    """A 500 tells the user nothing they can act on. This one names the model
    that failed and what to do about it."""
    from simagent.llm import FormalizeError

    def broken(text, **kw):
        raise FormalizeError("pi could not answer: some/model returned no emit_claim call")

    monkeypatch.setattr("simagent.llm.formalize_recorded", broken)
    r = client.post("/api/agent/start", json={"conjecture": "anything"})
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail["error"] == "formalization_failed"
    assert "no emit_claim call" in detail["reason"]
    assert "pick a model" in detail["hint"]


def test_the_model_you_pick_also_formalizes(client, monkeypatch):
    """Otherwise the formalizer silently used whichever model pi listed first,
    which may not support structured tool calls at all."""
    from simagent.library import get
    from simagent.llm import Formalization

    seen = {}

    def spy(text, **kw):
        seen.update(kw)
        return Formalization(claim=get("positive-quadratic"), source_text=text,
                             formalizer="faux/model", attempts=1)

    monkeypatch.setattr("simagent.llm.formalize_recorded", spy)
    client.post("/api/agent/start", json={"conjecture": "x", "provider": "somewhere",
                                          "model": "some-model"})
    assert seen.get("provider") == "somewhere"
    assert seen.get("model") == "some-model"
