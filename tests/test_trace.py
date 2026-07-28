"""Mind-trace tests: the agent's visual chain of thought is recorded per step
(thought + act + scene + equation translation + diff) and served by the web
API for replay/live-follow. All offline — scripted fake model, no manim."""
import json
from pathlib import Path
import pytest

from simagent.agent import AgentRun
from simagent.library import get
from simagent.core.journal import TRACE_FILE, diff_vars, equation_of_state, read_trace


def read_steps(out_dir):
    lines = [json.loads(l) for l in (Path(out_dir) / TRACE_FILE).read_text().splitlines()]
    return [l for l in lines if "event" not in l], [l for l in lines if "event" in l]


# -- recorder mechanics (AgentRun driven directly, no model) ------------------


def test_trace_records_state_equation_and_diff(tmp_path):
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.note_thought("I picture a wide obtuse triangle.", kind="thinking")
    run.note_thought("Let me place it.", kind="text")
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.2]})
    run.dispatch("certify", {})
    run.dispatch("finish", {"summary": "done"})
    run.note_thought("trailing narrative after the last act")
    run.finalize()

    steps, events = read_steps(tmp_path)
    assert events == [{"event": "end", "steps": len(steps)}]

    set_step = steps[0]
    # the buffered thoughts attached to the first act, in order and kinds kept
    assert [t["kind"] for t in set_step["thought"]] == ["thinking", "text"]
    assert "obtuse" in set_step["thought"][0]["text"]
    assert set_step["tool"] == "set_var" and set_step["error"] is False
    # full replayable state: scene graph + vars + kernel check
    assert set_step["scene"], "scene snapshot must be recorded"
    assert set_step["vars"]["T"] == [[-1, 0], [1, 0], [0, 0.2]]
    assert set_step["check"]["holds"] is False
    # the equation translation of the state (margin convention spelled out)
    eq = "\n".join(set_step["equation"]["text"])
    assert "T = (-1, 0), (1, 0), (0, 0.2)" in eq
    assert "margin" in eq and "FAILS" in eq
    assert any(r"\mu" in l for l in set_step["equation"]["latex"])
    # the diff shows what moved and how the margin changed
    changed = {(c["var"], c["row"]) for c in set_step["diff"]["changed"]}
    assert ("T", 0) in changed or ("T", None) in changed
    assert set_step["diff"]["margin"]["after"] == pytest.approx(-12.0)

    certify_step = steps[1]
    assert certify_step["thought"] is None  # no new narrative between acts
    assert certify_step["extra"]["certified"] is True
    assert certify_step["extra"]["exact"]["T"] == [["-1", "0"], ["1", "0"], ["0", "1/5"]]
    assert certify_step["diff"]["changed"] == []  # certify moves nothing

    # trailing thought flushed as a tool-less entry on finalize
    assert steps[-1]["tool"] is None
    assert steps[-1]["thought"][0]["text"].startswith("trailing")


def test_plan_declares_approach_as_intent_only(tmp_path):
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.dispatch("plan", {"method": "counterexample", "idea": "flatten the triangle"})
    run.dispatch("plan", {"method": "interpretive dance", "idea": "nope"})  # invalid
    run.dispatch("finish", {"summary": "done"})
    run.finalize()
    steps, _ = read_steps(tmp_path)
    ok, bad = steps[0], steps[1]
    assert ok["extra"] == {"declared_method": "counterexample", "idea": "flatten the triangle"}
    assert ok["error"] is False and "intent" in ok["result"].lower()
    assert bad["error"] is True  # junk method surfaces to the model, not the kernel
    assert run.declared_plans == [{"method": "counterexample", "idea": "flatten the triangle"}]
    # declaring a plan never creates proof material
    assert run.best_report() is None and run.deductive is None


def test_system_prompt_offers_plan_and_method_menu():
    from simagent.agent import SYSTEM, TOOLS

    assert "plan" in {t["name"] for t in TOOLS}
    assert "line of attack" in SYSTEM
    assert "never becomes the verdict" in SYSTEM


def test_trace_look_saves_image_and_errors_are_steps(tmp_path):
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.dispatch("look", {})
    run.dispatch("exhaust", {})  # continuous domain -> error, still traced
    run.finalize()
    steps, _ = read_steps(tmp_path)
    assert steps[0]["tool"] == "look"
    assert steps[0]["image"] == "looks/look_001.png"
    assert (tmp_path / steps[0]["image"]).exists()
    assert steps[1]["tool"] == "exhaust" and steps[1]["error"] is True


# -- pure helpers -------------------------------------------------------------


def test_equation_of_state_discrete_and_degenerate():
    eq = equation_of_state({"n": 7}, {"holds": True, "margin": None, "data": {}})
    text = "\n".join(eq["text"])
    assert "n = 7" in text and "discrete check" in text
    eq2 = equation_of_state({"n": 7}, {"error": "ZeroDivisionError: boom"})
    assert any("degenerate" in l for l in eq2["text"])


def test_diff_vars_rows_and_shape_changes():
    a = {"T": [[0, 0], [1, 0], [0, 1]]}
    b = {"T": [[0, 0], [1, 0], [2, 2]], "n": 3}
    changes = diff_vars(a, b)
    by_var = {(c["var"], c["row"]): c for c in changes}
    assert by_var[("T", 2)]["after"] == "(2, 2)"
    assert ("T", 0) not in by_var  # unchanged rows are not noise
    assert by_var[("n", None)]["before"] is None  # new var
    assert diff_vars(None, b) == []  # first step has no diff


# -- web API ------------------------------------------------------------------

fastapi_testclient = pytest.importorskip("fastapi.testclient")


@pytest.fixture()
def traced_run(tmp_path):
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path / "agent-demo")
    run.note_thought("wide triangle should break it")
    run.dispatch("look", {})
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.2]})
    run.dispatch("certify", {})
    run.finalize()
    return tmp_path


@pytest.fixture()
def client(traced_run):
    from simagent.web import create_app

    app = create_app(out_root=str(traced_run / "web"), runs_root=str(traced_run))
    with fastapi_testclient.TestClient(app) as c:
        yield c


def test_api_runs_lists_traced_runs(client):
    runs = client.get("/api/runs").json()
    assert [r["run"] for r in runs] == ["agent-demo"]
    assert runs[0]["title"] == "Circumcenter lies inside every triangle"


def test_api_trace_replay_and_live_polling(client):
    tr = client.get("/api/trace/agent-demo").json()
    assert tr["done"] is True and tr["total"] == 3
    assert tr["spec"]["id"] == "circumcenter-in-triangle"
    assert tr["steps"][0]["thought"][0]["text"].startswith("wide triangle")
    assert tr["steps"][1]["scene"], "each step carries a replayable scene"
    # live-follow contract: after=N returns only newer steps
    newer = client.get("/api/trace/agent-demo?after=2").json()
    assert [s["step"] for s in newer["steps"]] == [3]
    assert newer["total"] == 3

    assert client.get("/api/trace/nope").status_code == 404


def test_api_trace_file_serves_look_but_blocks_traversal(client):
    r = client.get("/api/trace/agent-demo/file/looks/look_001.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    evil = client.get("/api/trace/agent-demo/file/..%2F..%2Fpyproject.toml")
    assert evil.status_code == 404
    assert client.get("/api/trace/agent-demo/file/spec.json").status_code == 200
