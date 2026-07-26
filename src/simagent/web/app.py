"""FastAPI backend for the SimAgent reasoning notebook.

Single-user local tool. The frontend is a notebook: a math problem goes in as
text (or a bundled problem id), the TypeScript pi service runs an embodied
agent session, and the UI streams the mind trace — thought + act + rendered
scene + equation translation + diff per step — as notebook cells. FastAPI stays
the kernel authority: it also exposes the sandbox session API (load/set/
sample/refine/hunt/certify) and Manim render jobs; the UI cannot mint
verdicts, it only displays kernel state.
"""
from __future__ import annotations

import asyncio
import colorsys
import json
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..library import all_specs, get
from ..spec import ProblemSpec
from ..core.journal import TRACE_FILE, read_trace
from ..sandbox import scene as scene_mod
from ..visualize import mpl
from ..visualize.manim_gen import manim_available, try_render_manim, write_manim_scene
from .session import SandboxSession

_STATIC = Path(__file__).parent / "static"

# Your own problems, so the notebook is not limited to the bundled eleven.
# Drop a claim/1 spec.json in ./problems and it joins the dropdown. These are
# NOT bundled: trust is by object identity with the bundled registry, so a Lean
# stamp on one of these still says statement_review = spec-generated-review-needed.
PROBLEMS_DIR = "problems"

# Cached step pictures are only valid while the code that drew them is. Both
# files matter: mpl.py draws, scene.py chooses the colours.
_RENDERER_MTIME = max(
    Path(mpl.__file__).stat().st_mtime,
    Path(scene_mod.__file__).stat().st_mtime,
)


class _FreshStatic(StaticFiles):
    """Never let a browser cache the UI.

    This is a local single-user tool whose files change while you are using it.
    A cached app.js means an edit appears to do nothing, and the failure looks
    like a broken feature rather than a stale file, which is the most expensive
    kind of confusion. Bandwidth is not a concern over loopback.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-store"
        return response


def _lanes(steps: list[dict]) -> list[dict]:
    """One entry per state the configuration actually reached.

    Imagined steps are forks that never happened, so they are excluded: a
    progression must show the world's history, not the road not taken.
    """
    lanes: list[dict] = []
    for s in steps:
        if s.get("mode") in ("imagine", "annotation"):
            continue
        scene = s.get("scene")
        if not scene:
            continue
        if lanes and lanes[-1]["scene"] == scene:
            continue
        lanes.append({"step": s.get("step"), "tool": s.get("tool"),
                      "check": s.get("check"), "scene": scene})
    return lanes


def _lane_color(index: int, count: int) -> str:
    """Time as one violet ramp: pale early, deep late.

    Deliberately not blue and not red. Those two already mean HOLDS and FAILS
    in every other picture this tool draws, and one colour cannot honestly
    carry two meanings at once.
    """
    t = 1.0 if count < 2 else index / (count - 1)
    r, g, b = colorsys.hls_to_rgb(276.0 / 360.0, (76.0 - 46.0 * t) / 100.0,
                                  (32.0 + 30.0 * t) / 100.0)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def _combined_scene(lanes: list[dict]) -> list[dict]:
    """Every state in one scene graph, recoloured by when it happened."""
    combined: list[dict] = []
    for index, lane in enumerate(lanes):
        color = _lane_color(index, len(lanes))
        last = index == len(lanes) - 1
        fade = 1.0 if last else 0.3 + 0.4 * (index / len(lanes))
        for prim in lane["scene"]:
            if prim.get("type") == "label":
                continue  # per-state labels would stack into noise
            p = dict(prim)
            if p.get("type") == "sphere":
                continue  # one circumsphere per state buries everything else
            if not last:
                p["name"] = None  # the same name once per state is just overprint
            p["color"] = color
            if "opacity" in p:
                p["opacity"] = float(p["opacity"]) * fade
            elif not last:
                p["opacity"] = fade
            combined.append(p)
    steps = ", ".join(f"[{lane['step']}] {lane['tool'] or '—'}" for lane in lanes)
    combined.append({"type": "label",
                     "text": f"{len(lanes)} states, pale = early, deep = late: {steps}"})
    return combined


def _disk_specs() -> dict[str, tuple[ProblemSpec, Path]]:
    """Spec files in ./problems, keyed by id. A broken file is skipped with a
    printed reason: silence would look like the file was never there."""
    found: dict[str, tuple[ProblemSpec, Path]] = {}
    root = Path(PROBLEMS_DIR)
    if not root.is_dir():
        return found
    for path in sorted(root.glob("*.json")):
        try:
            spec = ProblemSpec.load(path)
        except Exception as exc:  # a user-authored file, so say what is wrong
            print(f"problems/{path.name}: skipped ({exc})")
            continue
        found[spec.id] = (spec, path)
    return found


class LoadBody(BaseModel):
    problem_id: str | None = None
    spec_path: str | None = None


class SetBody(BaseModel):
    name: str
    row: int | None = None
    values: list[float]


class SampleBody(BaseModel):
    seed: int | None = None


class RefineBody(BaseModel):
    steps: int = 300


class HuntBody(BaseModel):
    trials: int = 800


class ManimBody(BaseModel):
    video: bool = False


class AgentStartBody(BaseModel):
    problem_id: str | None = None
    conjecture: str | None = None
    provider: str | None = None
    model: str | None = None
    thinking_level: Literal[
        "off", "minimal", "low", "medium", "high", "xhigh", "max"
    ] = "medium"
    max_turns: int = 40


class AgentCommentBody(BaseModel):
    text: str
    target: dict


class AgentBranchBody(BaseModel):
    step: int
    comment: str | None = None
    target: dict | None = None


def create_app(
    out_root: str = "runs/web",
    runs_root: str | None = None,
    agent_client=None,
) -> FastAPI:
    owned_agent_client = None

    @asynccontextmanager
    async def lifespan(_app):
        yield
        if owned_agent_client is not None:
            await asyncio.to_thread(owned_agent_client.close)

    app = FastAPI(title="SimAgent sandbox", lifespan=lifespan)
    sessions: dict[str, SandboxSession] = {}
    jobs: dict[str, dict] = {}
    lock = threading.Lock()
    # Where agent runs live (each with a trace.jsonl mind trace). Default: the
    # parent of out_root, i.e. `runs/` when serving from `runs/web`.
    traces_root = Path(runs_root) if runs_root else Path(out_root).parent

    def run_dir(run: str) -> Path:
        d = (traces_root / run).resolve()
        if (
            run in ("", ".", "..")
            or "/" in run
            or "\\" in run
            or not d.is_relative_to(traces_root.resolve())
            or not (d / TRACE_FILE).exists()
        ):
            raise HTTPException(404, f"no trace for run {run!r}")
        return d

    def session() -> SandboxSession:
        s = sessions.get("current")
        if s is None:
            raise HTTPException(409, "no problem loaded; POST /api/load first")
        return s

    @app.get("/api/problems")
    def problems() -> list[dict]:
        rows = [
            {
                "id": s.id,
                "title": s.title,
                "quantifier": s.quantifier,
                "conjecture": s.conjecture,
                "source": "bundled",
            }
            for s in all_specs()
        ]
        rows += [
            {
                "id": spec.id,
                "title": spec.title,
                "quantifier": spec.quantifier,
                "conjecture": spec.conjecture,
                "source": "file",
            }
            for spec, _ in _disk_specs().values()
        ]
        return rows

    @app.post("/api/load")
    def load(body: LoadBody) -> dict:
        if body.spec_path:
            spec = ProblemSpec.load(body.spec_path)
        elif body.problem_id:
            try:
                spec = get(body.problem_id)
            except KeyError as e:
                raise HTTPException(404, str(e)) from e
        else:
            raise HTTPException(422, "problem_id or spec_path required")
        sessions["current"] = SandboxSession(spec, Path(out_root) / spec.id)
        return sessions["current"].state()

    @app.get("/api/state")
    def state() -> dict:
        return session().state()

    @app.post("/api/set")
    def set_value(body: SetBody) -> dict:
        s = session()
        try:
            s.set_value(body.name, body.row, body.values)
        except (KeyError, ValueError) as e:
            raise HTTPException(422, str(e)) from e
        return s.state()

    @app.post("/api/sample")
    def sample(body: SampleBody) -> dict:
        s = session()
        s.sample(body.seed)
        return s.state()

    @app.post("/api/refine")
    def refine(body: RefineBody) -> dict:
        s = session()
        try:
            result = s.refine(body.steps)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return {"result": result, "state": s.state()}

    @app.post("/api/hunt")
    def hunt(body: HuntBody) -> dict:
        s = session()
        result = s.hunt(body.trials)
        return {"result": result, "state": s.state()}

    @app.post("/api/certify")
    def certify() -> dict:
        s = session()
        try:
            return s.certify()
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    @app.post("/api/manim")
    def manim_render(body: ManimBody) -> dict:
        s = session()
        if not manim_available():
            return {
                "job": None,
                "available": False,
                "message": "Manim is not available on this machine (see README: .manim-env).",
            }
        job_id = uuid.uuid4().hex[:8]
        scene = s.scene()
        scene_py = write_manim_scene(scene, s.spec.title, s.spec.id, s.out / "scene_manim.py")
        with lock:
            jobs[job_id] = {"status": "running", "message": "rendering...", "file": None}

        def work() -> None:
            ok, msg, files = try_render_manim(
                scene_py, still=not body.video, quality="h" if not body.video else "l"
            )
            with lock:
                jobs[job_id] = {
                    "status": "done" if ok else "failed",
                    "message": msg,
                    "file": files[-1] if files else None,
                }

        threading.Thread(target=work, daemon=True).start()
        return {"job": job_id, "available": True, "video": body.video}

    @app.get("/api/manim/{job_id}")
    def manim_status(job_id: str) -> dict:
        with lock:
            job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "unknown job")
        return {**job, "url": f"/api/manim/{job_id}/file" if job["file"] else None}

    @app.get("/api/manim/{job_id}/file")
    def manim_file(job_id: str):
        with lock:
            job = jobs.get(job_id)
        if job is None or not job["file"]:
            raise HTTPException(404, "no file for this job")
        return FileResponse(job["file"])

    # -- mind traces: replay/watch an agent's chain of thought ---------------

    @app.get("/api/runs")
    def runs() -> list[dict]:
        """Agent runs under the runs root that recorded a mind trace."""
        found = []
        if traces_root.is_dir():
            for d in traces_root.iterdir():
                tf = d / TRACE_FILE
                if not tf.is_file():
                    continue
                title = None
                spec_file = d / "spec.json"
                if spec_file.is_file():
                    try:
                        title = json.loads(spec_file.read_text()).get("title")
                    except (OSError, ValueError):
                        pass
                found.append({"run": d.name, "title": title, "mtime": tf.stat().st_mtime})
        return sorted(found, key=lambda r: r["mtime"], reverse=True)

    @app.get("/api/trace/{run}")
    def trace(run: str, after: int = 0) -> dict:
        """Steps of a run's mind trace; `after` returns only steps > it, so a
        viewer can poll and follow a live agent."""
        d = run_dir(run)
        out = read_trace(d, after=after)
        spec_meta = None
        spec_file = d / "spec.json"
        if spec_file.is_file():
            try:
                s = json.loads(spec_file.read_text())
                spec_meta = {
                    k: s.get(k) for k in ("id", "title", "conjecture", "latex", "quantifier")
                }
            except (OSError, ValueError):
                pass
        # Kernel outcome, straight from the artifacts on disk (never computed here).
        proof_meta, verdict = None, None
        proof_file = d / "proof.json"
        if proof_file.is_file():
            try:
                p = json.loads(proof_file.read_text())
                proof_meta = {
                    k: p.get(k) for k in ("method", "verified_by", "claim", "statement_review")
                }
            except (OSError, ValueError):
                pass
        answer_file = d / "answer.md"
        if answer_file.is_file():
            try:
                for line in answer_file.read_text().splitlines():
                    if line.startswith("## Verdict:"):
                        verdict = line.removeprefix("## Verdict:").strip()
                        break
            except OSError:
                pass
        return {"run": run, "spec": spec_meta, "proof": proof_meta, "verdict": verdict, **out}

    @app.get("/api/trace/{run}/render/{step}")
    def trace_render(run: str, step: int):
        """Server-side PNG of one step's scene graph (matplotlib, cached).

        Steps are append-only, so a step's scene never changes. The RENDERER
        does: when it did, every cached picture kept the old look and the UI
        appeared to revert. So the cache is also invalid whenever the renderer
        is newer than the picture it produced.
        """
        d = run_dir(run)
        cache = d / "trace_renders" / f"step_{step:03d}.png"
        stale = cache.is_file() and cache.stat().st_mtime < _RENDERER_MTIME
        if not cache.is_file() or stale:
            entry = next((s for s in read_trace(d)["steps"] if s.get("step") == step), None)
            if entry is None:
                raise HTTPException(404, f"no step {step} in this trace")
            scene = entry.get("scene") or []
            if not scene:
                raise HTTPException(404, "this step has no renderable scene")
            title = None
            spec_file = d / "spec.json"
            if spec_file.is_file():
                try:
                    title = json.loads(spec_file.read_text()).get("title")
                except (OSError, ValueError):
                    pass
            cache.parent.mkdir(exist_ok=True)
            mpl.render_png(scene, cache, title=title)
        return FileResponse(cache)

    @app.get("/api/trace/{run}/progression")
    def trace_progression(run: str) -> list[dict]:
        """The distinct configurations a run reached, in order.

        A step that only looks or measures leaves the world where it was, and
        drawing that state twice would stack identical geometry, so consecutive
        identical scenes collapse to one entry.
        """
        return [
            {"step": lane["step"], "tool": lane["tool"], "check": lane["check"]}
            for lane in _lanes(read_trace(run_dir(run))["steps"])
        ]

    @app.get("/api/trace/{run}/progression.png")
    def trace_progression_png(run: str):
        """One picture of the whole run: every distinct state in a single scene.

        Not cached: a live run reaches new states, so a cached file would go
        stale in exactly the case where the picture is most interesting.
        """
        d = run_dir(run)
        lanes = _lanes(read_trace(d)["steps"])
        if len(lanes) < 2:
            raise HTTPException(404, "this run reached fewer than two distinct states")
        title = None
        spec_file = d / "spec.json"
        if spec_file.is_file():
            try:
                title = json.loads(spec_file.read_text()).get("title")
            except (OSError, ValueError):
                pass
        out = d / "trace_renders" / "progression.png"
        out.parent.mkdir(exist_ok=True)
        mpl.render_png(_combined_scene(lanes), out, title=title)
        return FileResponse(out)

    @app.get("/api/trace/{run}/file/{path:path}")
    def trace_file(run: str, path: str):
        """Serve a file from inside one run dir only (e.g. looks/look_001.png)."""
        d = run_dir(run)
        f = (d / path).resolve()
        if not f.is_relative_to(d) or not f.is_file():
            raise HTTPException(404, "no such file in this run")
        return FileResponse(f)

    # -- pi agent control: TypeScript owns model sessions and branches --------

    def control():
        nonlocal owned_agent_client
        if agent_client is not None:
            return agent_client
        if owned_agent_client is None:
            from ..pi_agent import PiAgentClient

            owned_agent_client = PiAgentClient(traces_root)
        return owned_agent_client

    def control_error(exc):
        from ..pi_agent import PiAgentError

        if not isinstance(exc, PiAgentError):
            raise exc
        status = {
            "NOT_FOUND": 404,
            "BUSY": 409,
            "CONFLICT": 409,
            "VALIDATION": 422,
            "NOT_BUILT": 503,
            "NO_NODE": 503,
        }.get(exc.code, 500)
        raise HTTPException(status, str(exc)) from exc

    @app.get("/api/agent/models")
    def agent_models() -> list[dict]:
        try:
            return control().models()
        except Exception as exc:
            control_error(exc)

    @app.post("/api/agent/start")
    def agent_start(body: AgentStartBody) -> dict:
        conjecture = body.conjecture.strip() if body.conjecture else ""
        if bool(body.problem_id) == bool(conjecture):
            raise HTTPException(422, "give exactly one of problem_id or conjecture")
        spec_path = None
        problem_id = body.problem_id
        if problem_id:
            try:
                get(problem_id)
            except KeyError as exc:
                # Not bundled: it may be one of the user's own files, which the
                # runtime takes as a path rather than an id.
                on_disk = _disk_specs().get(problem_id)
                if on_disk is None:
                    raise HTTPException(404, str(exc)) from exc
                spec_path = on_disk[1].resolve()
                problem_id = None
        else:
            from ..llm import formalize

            spec = formalize(conjecture)
            spec_dir = traces_root / ".formalized"
            spec_dir.mkdir(parents=True, exist_ok=True)
            spec_path = spec_dir / f"{spec.id}-{uuid.uuid4().hex[:8]}.json"
            spec.save(spec_path)
        try:
            return control().start(
                problem_id=problem_id,
                spec_path=spec_path,
                provider=body.provider,
                model=body.model,
                thinking_level=body.thinking_level,
                max_turns=max(1, min(body.max_turns, 200)),
            )
        except Exception as exc:  # transport errors map to stable HTTP statuses
            control_error(exc)

    @app.post("/api/agent/{run}/stop")
    def agent_stop(run: str) -> dict:
        try:
            return control().stop(run)
        except Exception as exc:
            control_error(exc)

    @app.get("/api/agent/{run}/status")
    def agent_status(run: str) -> dict:
        try:
            return control().status(run)
        except Exception as exc:
            control_error(exc)

    @app.get("/api/agent/{run}/events")
    def agent_events(run: str, after: int = 0) -> dict:
        try:
            return control().events(run, after=max(0, after))
        except Exception as exc:
            control_error(exc)

    @app.post("/api/agent/{run}/comment")
    def agent_comment(run: str, body: AgentCommentBody) -> dict:
        if not body.text.strip():
            raise HTTPException(422, "comment text must be non-empty")
        try:
            return control().comment(run, body.text.strip(), body.target)
        except Exception as exc:
            control_error(exc)

    @app.post("/api/agent/{run}/branch")
    def agent_branch(run: str, body: AgentBranchBody) -> dict:
        if body.step < 0:
            raise HTTPException(422, "branch step must be non-negative")
        try:
            return control().branch(
                run,
                body.step,
                comment=body.comment,
                target=body.target,
            )
        except Exception as exc:
            control_error(exc)

    @app.websocket("/api/agent/{run}/stream")
    async def agent_stream(websocket: WebSocket, run: str):
        await websocket.accept()
        after = 0
        try:
            while True:
                event_batch = await asyncio.to_thread(control().events, run, after)
                for event in event_batch["events"]:
                    await websocket.send_json(event)
                after = event_batch["total"]
                status = await asyncio.to_thread(control().status, run)
                if status["status"] in ("done", "failed", "stopped"):
                    await websocket.send_json({"type": "settled", "data": status})
                    return
                await asyncio.sleep(0.35)
        except WebSocketDisconnect:
            return
        except Exception as exc:
            await websocket.send_json({"type": "error", "data": {"message": str(exc)}})

    @app.get("/")
    def index():
        return FileResponse(_STATIC / "index.html")

    app.mount("/static", _FreshStatic(directory=_STATIC), name="static")
    return app
