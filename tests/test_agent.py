"""Kernel-side agent tool state tests. The provider loop lives in agent/ (pi)."""
import json
from pathlib import Path

from simagent import agent
from simagent.agent import AgentRun
from simagent.library import get
from simagent.proof import Method


def test_agent_manual_counterexample_by_hand(tmp_path):
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.2]})
    run.dispatch("certify", {})
    run.dispatch("finish", {"summary": "Wide triangle: circumcenter far below."})
    proof, report, artifacts = run.finalize()
    assert proof is not None and proof.method is Method.COUNTEREXAMPLE
    assert report.notes[0].startswith("found interactively")
    assert Path(artifacts["proof"]).is_file()


def test_agent_exhaustion_path(tmp_path):
    run = AgentRun(get("sum-of-odds-square"), tmp_path)
    content, error = run.dispatch("exhaust", {})
    assert not error and "holds_on_domain" in content
    run.dispatch("finish", {"summary": "All cases checked."})
    proof, _report, _artifacts = run.finalize()
    assert proof is not None and proof.method is Method.EXHAUSTION


def test_agent_tool_errors_are_recorded_without_proof(tmp_path):
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    content, error = run.dispatch("exhaust", {})
    assert error and "not finite" in content
    run.dispatch("finish", {"summary": "stuck"})
    proof, _report, _artifacts = run.finalize()
    assert proof is None
    lines = [json.loads(line) for line in (tmp_path / "transcript.jsonl").read_text().splitlines()]
    assert lines[0]["tool"] == "exhaust" and lines[0]["error"] is True


def test_python_agent_module_has_no_provider_backend_loop():
    assert not hasattr(agent, "run_agent")
    assert not hasattr(agent, "run_agent_claude_code")
    assert not hasattr(agent, "run")


# -- what the model can actually read ----------------------------------------


def test_status_carries_the_free_coordinates(tmp_path):
    """Without its own coordinates the model must guess positions off a PNG."""
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.2]})
    content, error = run.dispatch("check", {})
    assert not error
    state = json.loads(content)
    assert state["config"]["T"] == [[-1.0, 0.0], [1.0, 0.0], [0.0, 0.2]]
    assert "margin" in state and "holds" in state


def test_truncation_stays_parseable_and_says_it_truncated():
    """A sliced JSON string reads as a complete reply; a dropped field cannot."""
    payload = {"holds": False, "margin": -0.5, "witness": [[1.2345678] * 40] * 40}
    text = agent._fit(payload)
    assert len(text) <= agent.MAX_TOOL_CHARS
    out = json.loads(text)  # the whole point: it must still parse
    assert out["truncated"] is True and out["dropped_fields"] == ["witness"]
    assert out["margin"] == -0.5  # the verdict-bearing field survives


def test_measure_describes_a_non_geometry_claim(tmp_path):
    """Every measure kind speaks, not only the barycentric family."""
    run = AgentRun(get("positive-quadratic"), tmp_path)
    run.dispatch("set_var", {"name": "P", "values": [0.5, 0.5]})
    lines = json.loads(run.dispatch("measure", {})[0])["qualitative"]
    assert any("term by term" in line for line in lines)

    discrete = AgentRun(get("euler-characteristic-hull"), tmp_path / "euler")
    lines = json.loads(discrete.dispatch("measure", {})[0])["qualitative"]
    assert any("V - E + F" in line for line in lines)


def test_recall_returns_the_journal_and_mints_nothing(tmp_path):
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.dispatch("plan", {"method": "counterexample", "idea": "obtuse triangle"})
    run.dispatch("expect", {"relation": "<", "value": 0.0})
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.2]})
    run.dispatch("certify", {})
    digest = json.loads(run.dispatch("recall", {})[0])

    assert digest["approaches_declared"] == [
        {"method": "counterexample", "idea": "obtuse triangle"}
    ]
    scored = digest["predictions"]["scored"]
    assert len(scored) == 1 and scored[0]["ok"] is True
    assert [a["tool"] for a in digest["acts"]] == ["plan", "expect", "set_var", "certify"]
    assert digest["margin_seen"]["lowest"]["margin"] <= digest["margin_seen"]["highest"]["margin"]
    # It restates; it never stamps. No verdict word may originate here.
    assert "verified_by" not in digest


def test_recall_counts_the_acts_it_drops(tmp_path):
    """A silent cap reads as complete coverage; this one says what it left out."""
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    for _ in range(agent.RECALL_ACTS + 5):
        run.dispatch("check", {})
    digest = json.loads(run.dispatch("recall", {})[0])
    assert digest["acts_omitted"] == 5
    assert len(digest["acts"]) == agent.RECALL_ACTS
