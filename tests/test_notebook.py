"""Notebook-facing web API: per-step scene renders, kernel outcome on the
trace, and the background agent job runner (with an injected fake runner —
offline, no LLM)."""
import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from simagent.agent import AgentRun  # noqa: E402
from simagent.library import get  # noqa: E402
from simagent.pi_agent import PiAgentError  # noqa: E402
from simagent.web import create_app  # noqa: E402


@pytest.fixture()
def traced_run(tmp_path):
    """A finished agent run with a certified counterexample on disk."""
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path / "agent-demo")
    run.note_thought("wide triangle should break it")
    run.dispatch("look", {})
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.2]})
    run.dispatch("certify", {})
    run.dispatch("finish", {"summary": "done"})
    run.finalize()
    return tmp_path


def make_client(root, agent_client=None):
    app = create_app(out_root=str(root / "web"), runs_root=str(root), agent_client=agent_client)
    return fastapi_testclient.TestClient(app)


def test_render_endpoint_renders_and_caches(traced_run):
    with make_client(traced_run) as client:
        r = client.get("/api/trace/agent-demo/render/2")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        cache = traced_run / "agent-demo" / "trace_renders" / "step_002.png"
        assert cache.is_file()
        stamp = cache.stat().st_mtime_ns
        assert client.get("/api/trace/agent-demo/render/2").status_code == 200
        assert cache.stat().st_mtime_ns == stamp, "second hit must come from the cache"
        assert client.get("/api/trace/agent-demo/render/99").status_code == 404


def test_trace_carries_kernel_outcome(traced_run):
    with make_client(traced_run) as client:
        tr = client.get("/api/trace/agent-demo").json()
        assert tr["proof"]["method"] == "counterexample"
        assert tr["proof"]["verified_by"] in ("sandbox", "sandbox+lean")
        assert tr["verdict"] and "DISPROVED" in tr["verdict"]


class FakePiControl:
    def __init__(self):
        self.run = "agent-circumcenter-in-triangle"
        self.status_value = "running"
        self.calls = []

    def models(self):
        return [{"provider": "fake", "id": "vision", "vision": True}]

    def start(self, **kwargs):
        self.calls.append(("start", kwargs))
        return {"run": self.run}

    def status(self, run):
        if run != self.run:
            raise PiAgentError("NOT_FOUND", "unknown agent job")
        return {
            "run": run,
            "status": self.status_value,
            "title": "triangle",
            "turns": 1,
            "log": ["[tool] check"],
            "error": None,
            "proof": None,
            "checkpoints": [],
        }

    def events(self, run, after=0):
        self.status(run)
        return {"events": [{"seq": 1, "type": "started", "data": {}}] if after < 1 else [], "total": 1}

    def stop(self, run):
        self.status(run)
        if self.status_value != "running":
            raise PiAgentError("CONFLICT", f"session is not running (status: {self.status_value})")
        self.status_value = "stopping"
        self.calls.append(("stop", run))
        return {"run": run, "status": "stopping"}

    def comment(self, run, text, target):
        self.status(run)
        self.calls.append(("comment", text, target))
        return {"run": run, "status": "queued"}

    def branch(self, run, step, **kwargs):
        self.status(run)
        self.calls.append(("branch", step, kwargs))
        return {"run": f"branch-{run}-step-{step}"}

    def user_action(self, run, tool, args):
        self.status(run)
        if self.status_value != "running":
            raise PiAgentError("CONFLICT", "session is not accepting moves")
        self.calls.append(("user_action", tool, args))
        return {"run": run, "tool": tool, "traceStep": 4, "isError": False}


def test_agent_routes_delegate_to_pi_control(tmp_path):
    control = FakePiControl()
    with make_client(tmp_path, agent_client=control) as client:
        assert client.get("/api/agent/models").json()[0]["vision"] is True
        started = client.post(
            "/api/agent/start",
            json={"problem_id": "circumcenter-in-triangle", "max_turns": 17},
        )
        assert started.status_code == 200 and started.json()["run"] == control.run
        assert control.calls[0][0] == "start"
        assert control.calls[0][1]["max_turns"] == 17
        assert client.get(f"/api/agent/{control.run}/status").json()["status"] == "running"
        assert client.get(f"/api/agent/{control.run}/events").json()["total"] == 1

        target = {"step": 1, "kind": "equation", "index": 0}
        comment = client.post(
            f"/api/agent/{control.run}/comment",
            json={"text": "check the sign", "target": target},
        )
        assert comment.status_code == 200 and comment.json()["status"] == "queued"
        assert ("comment", "check the sign", target) in control.calls

        branch = client.post(
            f"/api/agent/{control.run}/branch",
            json={"step": 1, "comment": "try again", "target": target},
        )
        assert branch.status_code == 200
        assert branch.json()["run"].startswith("branch-")

        stopped = client.post(f"/api/agent/{control.run}/stop")
        assert stopped.status_code == 200 and stopped.json()["status"] == "stopping"
        assert client.post(f"/api/agent/{control.run}/stop").status_code == 409


def test_the_human_can_move_the_world_through_the_notebook(tmp_path):
    """The second half of collaboration needs a route, not only a kernel op.

    A comment can only suggest; when the agent is stuck the human has to be
    able to place the point, and the request must reach the same live kernel
    the agent is working in.
    """
    control = FakePiControl()
    with make_client(tmp_path, agent_client=control) as client:
        moved = client.post(
            f"/api/agent/{control.run}/action",
            json={"tool": "set_var", "args": {"name": "T", "row": 0, "values": [0.9, 0.1]}},
        )
        assert moved.status_code == 200 and moved.json()["isError"] is False
        assert (
            "user_action",
            "set_var",
            {"name": "T", "row": 0, "values": [0.9, 0.1]},
        ) in control.calls

        sampled = client.post(f"/api/agent/{control.run}/action", json={"tool": "sample"})
        assert sampled.status_code == 200
        assert ("user_action", "sample", {}) in control.calls

        assert client.post(f"/api/agent/{control.run}/action", json={"tool": "  "}).status_code == 422
        assert client.post("/api/agent/no-such-run/action", json={"tool": "sample"}).status_code == 404

        # A settled session has nothing live to move: the refusal must be an
        # explicit conflict, not a move applied to nothing.
        control.status_value = "done"
        stale = client.post(f"/api/agent/{control.run}/action", json={"tool": "sample"})
        assert stale.status_code == 409


def test_pi_event_websocket_bridges_controller_events(tmp_path):
    control = FakePiControl()
    control.status_value = "done"
    with make_client(tmp_path, agent_client=control) as client:
        with client.websocket_connect(f"/api/agent/{control.run}/stream") as websocket:
            first = websocket.receive_json()
            settled = websocket.receive_json()
        assert first["type"] == "started"
        assert settled["type"] == "settled" and settled["data"]["status"] == "done"


def test_agent_routes_validate_and_map_unknown_jobs(tmp_path):
    control = FakePiControl()
    with make_client(tmp_path, agent_client=control) as client:
        assert client.post("/api/agent/start", json={}).status_code == 422
        assert (
            client.post(
                "/api/agent/start",
                json={"problem_id": "circumcenter-in-triangle", "conjecture": "both"},
            ).status_code
            == 422
        )
        assert client.post("/api/agent/start", json={"problem_id": "nope"}).status_code == 404
        assert client.get("/api/agent/nope/status").status_code == 404
        assert client.post("/api/agent/nope/stop").status_code == 404
        assert client.post(
            f"/api/agent/{control.run}/comment", json={"text": "  ", "target": {}}
        ).status_code == 422
        assert client.post(
            f"/api/agent/{control.run}/branch", json={"step": -1}
        ).status_code == 422


def test_p6_notebook_assets_offer_comment_branch_and_scene_pick(tmp_path):
    with make_client(tmp_path, agent_client=FakePiControl()) as client:
        index = client.get("/").text
        script = client.get("/static/app.js").text
        assert "commentPopover" in index and "branch with comment" in index
        assert "modelSel" in index and "/api/agent/models" in script
        assert "thinkingSel" in index and "thinking_level" in script
        assert "backendSel" not in index and "claude-code" not in index
        assert "/comment`" in script and "/branch`" in script
        assert "THREE.Raycaster" in script and "kind: 'scene'" in script
        assert "branch provenance" in script


def test_agent_run_stop_blocks_tools_but_allows_finish(tmp_path):
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.dispatch("check", {})
    run.stop()
    content, err = run.dispatch("hunt", {"trials": 10})
    assert err and "stopped" in content
    _content, err2 = run.dispatch("finish", {"summary": "s"})
    assert not err2
    run.finalize()
    assert run.summary == "s"


def test_a_problem_file_joins_the_dropdown_and_starts_by_path(tmp_path, monkeypatch):
    """Your own claim in ./problems must be runnable from the notebook.

    A question that cannot get into the tool is one the tool cannot help with,
    so the dropdown is not limited to the bundled eleven. The runtime takes a
    disk claim as a PATH, never as a bundled id, which is what keeps
    `library.is_bundled` (and therefore the review flag) honest.
    """
    from simagent.library import get as get_bundled

    problems = tmp_path / "problems"
    problems.mkdir()
    spec = get_bundled("positive-quadratic")
    payload = spec.to_json()
    payload["id"] = "my-own-claim"
    payload["title"] = "a claim of my own"
    (problems / "mine.json").write_text(__import__("json").dumps(payload))
    (problems / "broken.json").write_text("{not json")
    monkeypatch.chdir(tmp_path)

    control = FakePiControl()
    with make_client(tmp_path, agent_client=control) as client:
        rows = client.get("/api/problems").json()
        mine = [r for r in rows if r["id"] == "my-own-claim"]
        assert mine and mine[0]["source"] == "file", "the file must appear, marked as yours"
        assert all(r["id"] != "broken" for r in rows), "a broken file is skipped, not fatal"

        started = client.post(
            "/api/agent/start",
            json={"problem_id": "my-own-claim", "max_turns": 3},
        )
        assert started.status_code == 200
        kwargs = control.calls[0][1]
        assert kwargs["problem_id"] is None, "a disk claim is never passed as a bundled id"
        assert str(kwargs["spec_path"]).endswith("problems/mine.json")

        assert client.post(
            "/api/agent/start", json={"problem_id": "no-such-claim"}
        ).status_code == 404


def test_progression_collapses_repeats_and_renders_one_picture(traced_run):
    """The whole run as one scene, so "where was it going" has an answer.

    A per-step picture answers "what did it do". Only the combined view shows
    the trajectory, and it must not draw the same state twice: look, measure
    and certify leave the world where it was, so consecutive identical scenes
    are one state, not three.
    """
    from simagent.web.app import _combined_scene, _lanes

    with make_client(traced_run) as client:
        states = client.get("/api/trace/agent-demo/progression").json()
        assert [s["tool"] for s in states] == ["look", "set_var"], states
        png = client.get("/api/trace/agent-demo/progression.png")
        assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"

    steps = [
        {"step": 1, "tool": "look", "scene": [{"type": "points", "coords": [[0, 0, 0]]}]},
        {"step": 2, "tool": "measure", "scene": [{"type": "points", "coords": [[0, 0, 0]]}]},
        {"step": 3, "mode": "imagine", "scene": [{"type": "points", "coords": [[9, 9, 9]]}]},
        {"step": 4, "tool": "nudge", "scene": [{"type": "points", "coords": [[1, 0, 0]]}]},
    ]
    lanes = _lanes(steps)
    assert [x["step"] for x in lanes] == [1, 4], "repeats collapse; imagined forks never happened"

    combined = _combined_scene(lanes)
    colors = {p["color"] for p in combined if p.get("type") == "points"}
    assert len(colors) == 2, "each state gets its own colour, or time is unreadable"
    assert combined[-1]["type"] == "label" and "pale = early" in combined[-1]["text"]


def test_a_cached_render_is_redrawn_when_the_renderer_changes(traced_run, monkeypatch):
    """A cached picture is only valid while the code that drew it is.

    Steps are append-only, so a step's scene never changes and caching is
    sound on that axis. The renderer is the other axis: when the theme moved
    from dark to light every cached PNG kept the old look, and the UI appeared
    to revert on its own.
    """
    from simagent.web import app as web_app

    with make_client(traced_run) as client:
        assert client.get("/api/trace/agent-demo/render/2").status_code == 200
        cache = traced_run / "agent-demo" / "trace_renders" / "step_002.png"
        stamp = cache.stat().st_mtime_ns
        assert client.get("/api/trace/agent-demo/render/2").status_code == 200
        assert cache.stat().st_mtime_ns == stamp, "unchanged renderer must reuse the cache"

        monkeypatch.setattr(web_app, "_RENDERER_MTIME", cache.stat().st_mtime + 60)
        assert client.get("/api/trace/agent-demo/render/2").status_code == 200
        assert cache.stat().st_mtime_ns != stamp, "a newer renderer must redraw"


def test_the_result_and_every_state_explain_themselves(traced_run):
    """A stamp and a list of fractions is not an answer a person can read.

    The explanation is built from kernel state only, so it restates what
    proof.py decided and can never raise it. That is the whole reason it is
    allowed to exist: describing a verdict is perception, minting one is not.
    """
    from simagent import explain

    with make_client(traced_run) as client:
        tr = client.get("/api/trace/agent-demo").json()
        labels = [r["label"] for r in tr["explain"]]
        assert "Verified by" in labels, "the reader must be told what checked this"
        assert any(l.startswith("Margin") for l in labels), "and what the deciding number was"
        assert tr["explain_summary"], "and whether it is an answer or only evidence"

        states = client.get("/api/trace/agent-demo/progression").json()
        assert all(s["why"] for s in states), "every state says what happened"
        assert "starting configuration" in states[0]["why"]
        moved = [s for s in states if "moved" in s["why"]]
        assert moved, "a state that changed the world must name what moved"

    # The rule that makes this safe: it reports the stamp, it never raises it.
    rows = explain.result_rows(None, {"verified_by": "none"}, None, {"margin": -1.0})
    assert any(r["value"] == "none" for r in rows)
    assert "Not a proof" in " ".join(r["why"] for r in rows)


# -- continuing a finished run from the notebook -------------------------------
# Adopt existed only on the command line, so the page could watch a run die on
# its turn budget and offer nothing but starting over. These pin the boundary.

def test_the_notebook_can_continue_a_finished_run(traced_run):
    """The claim comes from the earlier run's own spec, and the earlier run's
    directory is what the kernel replays."""
    import json

    control = FakePiControl()
    journal = traced_run / "agent-demo" / "kernel-journal.jsonl"
    journal.write_text('{"event": "header", "version": 4}\n')
    with make_client(traced_run, agent_client=control) as client:
        started = client.post("/api/agent/start", json={"adopt": "agent-demo"})
        assert started.status_code == 200, started.json()
        kwargs = control.calls[0][1]
        assert kwargs["adopt"] == str(traced_run / "agent-demo")
        assert kwargs["problem_id"] is None
        assert str(kwargs["spec_path"]).endswith("agent-demo/spec.json")


def test_continuing_refuses_to_also_pick_a_problem(traced_run):
    """Naming a problem beside `adopt` could only name a DIFFERENT claim, and
    the journal would then replay into a world that claim does not describe."""
    control = FakePiControl()
    (traced_run / "agent-demo" / "kernel-journal.jsonl").write_text("{}\n")
    with make_client(traced_run, agent_client=control) as client:
        r = client.post("/api/agent/start",
                        json={"adopt": "agent-demo",
                              "problem_id": "circumcenter-in-tetrahedron"})
        assert r.status_code == 422
        assert "brings its own claim" in str(r.json())


def test_a_run_without_a_journal_cannot_be_continued(traced_run):
    """Fail closed: adopt REPLAYS a journal. Without one there is nothing to
    reproduce, and starting anyway would invent a state nobody executed."""
    control = FakePiControl()
    with make_client(traced_run, agent_client=control) as client:
        r = client.post("/api/agent/start", json={"adopt": "agent-demo"})
        assert r.status_code == 422 and "no kernel journal" in str(r.json())
        assert client.post("/api/agent/start",
                           json={"adopt": "../etc"}).status_code == 404


def test_the_runs_listing_says_which_runs_can_be_continued(traced_run):
    """The page must not offer a button that cannot work, so the judgement is
    made where the files are."""
    with make_client(traced_run) as client:
        listed = {r["run"]: r for r in client.get("/api/runs").json()}
        assert listed["agent-demo"]["continuable"] is False
        (traced_run / "agent-demo" / "kernel-journal.jsonl").write_text("{}\n")
        listed = {r["run"]: r for r in client.get("/api/runs").json()}
        assert listed["agent-demo"]["continuable"] is True
