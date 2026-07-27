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


def test_look_carries_the_coordinates_too(tmp_path):
    """The vision path must not be the one place the numbers go missing."""
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.2]})
    blocks, error = run.dispatch("look", {})
    assert not error
    text = next(b["text"] for b in blocks if b["type"] == "text")
    assert json.loads(text.removeprefix("status: "))["config"]["T"][2] == [0.0, 0.2]


def test_coordinates_are_rounded_not_dumped_at_full_precision(tmp_path):
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.dispatch("set_var", {"name": "T", "values": [1 / 3, 0, 1, 0, 0, 0.2]})
    config = json.loads(run.dispatch("check", {})[0])["config"]
    assert config["T"][0][0] == round(1 / 3, agent.COORD_PLACES)


def test_truncation_keeps_the_verdict_when_every_field_is_protected():
    """The last resort must still be JSON, or the fail-safe is itself a failure."""
    text = agent._fit({"holds": True, "margin": 1.0, "note": "y" * 5000})
    out = json.loads(text)
    assert out["holds"] is True and out["margin"] == 1.0
    assert out["truncated"] is True and "only verdict fields kept" in out["note"]


def test_geometry_measure_still_names_the_face_it_escaped(tmp_path):
    """The barycentric wording predates the registry; moving it must not lose it."""
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.2]})
    lines = json.loads(run.dispatch("measure", {})[0])["qualitative"]
    assert any("OUTSIDE" in line and "face opposite vertex" in line for line in lines)

    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 1.5]})
    lines = json.loads(run.dispatch("measure", {})[0])["qualitative"]
    assert any("INSIDE" in line for line in lines)


def test_discrete_measure_states_both_sides_of_the_identity(tmp_path):
    run = AgentRun(get("sum-of-odds-square"), tmp_path)
    lines = json.loads(run.dispatch("measure", {})[0])["qualitative"]
    assert any("odd numbers" in line and "n squared" in line for line in lines)


def test_every_measure_kind_can_describe_itself():
    """A measure with no describer leaves the model only the margin it had.

    'Every output explains itself' is a standard, so a new measure kind must
    not be able to enter the registry mute.
    """
    from simagent.core.claim import MEASURES

    mute = [name for name, entry in MEASURES.items() if entry.get("qualitative") is None]
    assert mute == [], f"these measures cannot describe their own state: {mute}"


def test_a_describer_that_raises_does_not_break_the_tool_call(tmp_path, monkeypatch):
    """Perception is a convenience; it must never take the instrument down."""
    from simagent.core import claim as claim_mod

    def explode(*_args):
        raise RuntimeError("describer is broken")

    monkeypatch.setitem(claim_mod.MEASURES["min_coord"], "qualitative", explode)
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    content, error = run.dispatch("measure", {})
    assert not error
    state = json.loads(content)
    assert state["margin"] is not None
    assert any("could not describe" in line for line in state["qualitative"])


def test_measure_without_a_spec_still_reports_the_margin():
    """The registry lookup is optional context, not a requirement."""
    from simagent.core.measure import measure_state

    state = measure_state({"P": [0.5, 0.5]}, {"holds": True, "margin": 0.5, "data": {}})
    assert state["margin"] == 0.5
    assert any("HOLDS" in line for line in state["qualitative"])


def test_recall_on_a_run_that_has_done_nothing_says_so(tmp_path):
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    digest = json.loads(run.dispatch("recall", {})[0])
    assert digest["acts"] == [] and digest["acts_omitted"] == 0
    assert digest["margin_seen"] is None
    assert digest["approaches_declared"] == []
    assert digest["predictions"] == {"scored": [], "still_open": []}


def test_recall_reports_a_wrong_prediction_as_wrong(tmp_path):
    """Being wrong is the one thing the model cannot notice on its own."""
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.dispatch("expect", {"relation": ">", "value": 0.0, "note": "I think it holds"})
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.2]})
    scored = json.loads(run.dispatch("recall", {})[0])["predictions"]["scored"]
    assert len(scored) == 1 and scored[0]["ok"] is False
    assert scored[0]["note"] == "I think it holds"


def test_recall_changes_nothing_in_the_world(tmp_path):
    """A memory tool that mutates state would corrupt the branch it serves."""
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.2]})
    before = run.dispatch("check", {})[0]
    run.dispatch("recall", {})
    assert run.dispatch("check", {})[0] == before


def test_every_declared_tool_has_a_handler_and_a_description():
    """A tool the schema advertises and the kernel cannot run is a dead end."""
    names = [tool["name"] for tool in agent.TOOLS]
    assert len(names) == len(set(names)), "duplicate tool name"
    assert "recall" in names
    for tool in agent.TOOLS:
        assert tool["description"].strip(), f"{tool['name']} has no description"
        assert hasattr(AgentRun, f"_t_{tool['name']}"), f"{tool['name']} has no handler"


def test_recall_reports_the_past_without_steering_the_future(tmp_path):
    """Memory is a harness job; choosing the next move is the model's.

    `recall` is the one new surface that reads the whole run, which makes it
    the most tempting place to slip in a suggestion.
    """
    advice = ("you should", "try instead", "we recommend", "next, try", "consider ")
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.dispatch("plan", {"method": "counterexample", "idea": "obtuse triangle"})
    run.dispatch("hunt", {"trials": 200})
    text = run.dispatch("recall", {})[0].lower()
    for phrase in advice:
        assert phrase not in text, f"recall is steering: {phrase!r}"

    description = next(t["description"] for t in agent.TOOLS if t["name"] == "recall").lower()
    for phrase in advice:
        assert phrase not in description
    assert "no next move" in description or "names no next move" in description
