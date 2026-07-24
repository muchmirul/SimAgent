"""P5 gates: native claims (zero exec'd code on the bundled path), the
dimension-agnostic known answer (d=4 certified counterexample with the
explicit no-Lean-above-d3 notice), construct/expect tools, and the
closed-vocabulary formalizer schema."""
import json

import numpy as np
import pytest

from simagent.agent import AgentRun
from simagent.core.claim import Claim, validate_claim
from simagent.core.journal import read_trace
from simagent.library import all_specs, get, is_bundled
from simagent.llm import ClaimModel, claim_from_model_dump
from simagent.pipeline import run_problem
from simagent.proof import Method
from simagent.search import run_search
from simagent.spec import ProblemSpec


def test_bundled_library_is_exec_free_native_claims():
    claims = all_specs()
    assert len(claims) == 9
    for c in claims:
        assert isinstance(c, Claim) and c.is_native, c.id
        assert validate_claim(c) == [], c.id
        # spec-like surface used by search/proof/answer
        assert c.domain and c.quantifier in ("forall", "exists")
    assert {c.id for c in claims} >= {
        "circumcenter-in-triangle", "circumcenter-in-tetrahedron",
        "circumcenter-in-4simplex", "euler-characteristic-hull",
        "sum-of-odds-square", "sum-of-squares-vs-linear",
        "orthocenter-in-triangle", "positive-quadratic",
        "conditional-cubic",
    }


def test_native_triangle_reaches_known_answer_with_same_machinery():
    claim = get("circumcenter-in-triangle")
    report = run_search(claim, trials=300, seed=0)
    assert report.verdict == "counterexample"
    assert report.certified is True
    assert report.exact_witness is not None
    # the historical data keys survive the native engine (equation/notebook parity)
    res = claim.compiled().check(T=np.array([[-1.0, 0.0], [1.0, 0.0], [0.0, 0.2]]))
    assert set(res.data) == {"circumcenter", "barycentric"}
    assert res.margin < 0


def test_4simplex_known_answer_certified_sandbox_only(tmp_path):
    """THE dimension-agnostic gate (plan.md P5): certified counterexample in
    R^4; verdict tops out at sandbox; the answer says so explicitly."""
    claim = get("circumcenter-in-4simplex")
    result = run_problem(claim, out_dir=tmp_path, trials=800, seed=3)
    proof = result.proof
    assert proof is not None and proof.method is Method.COUNTEREXAMPLE
    assert proof.verified_by == "sandbox"  # exact rationals; NO lean above d=3
    assert proof.lean_report and "capped at d<=3" in str(proof.lean_report.get("error", ""))
    answer_md = (tmp_path / "answer.md").read_text()
    assert "DISPROVED" in answer_md
    assert "No Lean certificate is generated above d = 3" in answer_md


def test_euler_and_sum_of_odds_ground_truths(tmp_path):
    euler = run_search(get("euler-characteristic-hull"), trials=120, seed=1)
    assert euler.verdict == "no_counterexample"  # evidence path, never a proof
    from simagent.search import run_exhaustive

    odds = run_exhaustive(get("sum-of-odds-square"))
    assert odds.verdict == "holds_on_domain" and odds.certified is True


def test_claim_json_roundtrip_and_untrusted_identity(tmp_path):
    claim = get("circumcenter-in-tetrahedron")
    path = tmp_path / "claim.json"
    claim.save(path)
    loaded = ProblemSpec.load(path)  # routes claim/1 to Claim.from_json
    assert isinstance(loaded, Claim) and loaded.id == claim.id
    assert not is_bundled(loaded)  # disk twin is a different object -> untrusted
    assert validate_claim(loaded) == []


def test_construct_renders_and_follows_ancestors(tmp_path):
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.8]})
    content, err = run.dispatch("construct", {
        "name": "M", "ctor": "midpoint", "args": ["circ_a", "circ_b"]})
    assert err  # unknown args fail closed
    content, err = run.dispatch("construct", {
        "name": "G", "ctor": "centroid", "args": ["T"]})
    assert not err and "constructed G" in content
    scene = run.session.scene()
    assert any(p.get("name") == "G" for p in scene if p.get("type") == "points")
    # the construction follows its ancestors
    g_before = run.session.world.values["G"].copy()
    run.dispatch("set_var", {"name": "T", "row": 2, "values": [0.0, 0.2]})
    assert not np.array_equal(run.session.world.values["G"], g_before)
    step = read_trace(tmp_path)["steps"][1]
    assert step["error"] is True  # the failed construct is an honest journal entry


def test_expect_is_scored_mechanically(tmp_path):
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.8]})
    run.dispatch("expect", {"relation": "<", "value": 0.0,
                            "note": "flattening will push the center out"})
    run.dispatch("set_var", {"name": "T", "row": 2, "values": [0.0, 0.2]})
    steps = read_trace(tmp_path)["steps"]
    assert steps[1]["extra"]["expect"]["id"] == 1
    resolved = steps[2]["extra"]["resolved_expectations"]
    assert resolved[0]["ok"] is True and "margin" in resolved[0]["actual"]
    assert run.open_expectations == []
    # a wrong prediction scores false — prediction error is information
    run.dispatch("expect", {"relation": ">", "value": 100.0})
    run.dispatch("check", {})
    last = read_trace(tmp_path)["steps"][-1]
    assert last["extra"]["resolved_expectations"][0]["ok"] is False


def test_formalizer_schema_accepts_native_claim_and_rejects_junk():
    good = get("circumcenter-in-triangle").to_json()
    good.pop("format")
    model = ClaimModel.model_validate(good)
    claim = claim_from_model_dump(model.model_dump())
    assert validate_claim(claim) == []
    bad = dict(good)
    bad["measure"] = {"kind": "trust_me_bro"}
    junk = claim_from_model_dump(ClaimModel.model_validate(bad).model_dump())
    assert any("measure" in e for e in validate_claim(junk))
    with pytest.raises(Exception):
        ClaimModel.model_validate({**good, "quantifier": "sometimes"})
