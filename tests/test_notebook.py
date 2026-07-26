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
