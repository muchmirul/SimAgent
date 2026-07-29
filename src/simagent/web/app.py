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
from ..core.claim import Claim
from .. import explain
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
                      "check": s.get("check"), "scene": scene, "raw": s})
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
    combined.append({"type": "label", "text": (
        f"1 state, the only configuration this run reached: {steps}"
        if len(lanes) == 1 else
        f"{len(lanes)} states, pale = early, deep = late: {steps}"
    )})
    return combined


def _disk_specs() -> dict[str, tuple[Claim, Path]]:
    """Spec files in ./problems, keyed by id. A broken file is skipped with a
    printed reason: silence would look like the file was never there."""
    found: dict[str, tuple[Claim, Path]] = {}
    root = Path(PROBLEMS_DIR)
    if not root.is_dir():
        return found
    for path in sorted(root.glob("*.json")):
        try:
            spec = Claim.load(path)
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
    # numbers-first default; true makes this run the image arm
    images: bool = False
    # the hash of the exact formalized claim the caller read and accepted;
    # required before an agent runs on natural-language input
    approve_claim_hash: str | None = None
    # the NAME of an earlier run in this runs root to continue. Its journal is
    # replayed and hash-checked, then re-opened, so a run that died on its turn
    # budget can be carried on from the page that was watching it.
    adopt: str | None = None


class AgentCommentBody(BaseModel):
    text: str
    target: dict


class AgentActionBody(BaseModel):
    tool: str
    args: dict = {}


class AgentBranchBody(BaseModel):
    step: int
    comment: str | None = None
    target: dict | None = None


# Claims shown to a user and awaiting their yes. Keyed by the hash they were
# shown, so approving returns the exact claim they read rather than whatever a
# second formalizer call happens to produce. Bounded: a browser tab left open
# must not grow the process without limit.
_PENDING_CLAIM_LIMIT = 32
_pending_claims: dict[str, object] = {}


def _remember_claim(claim_hash: str, formalization) -> None:
    _pending_claims[claim_hash] = formalization
    while len(_pending_claims) > _PENDING_CLAIM_LIMIT:
        _pending_claims.pop(next(iter(_pending_claims)))


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
            try:
                spec = Claim.load(body.spec_path)
            except (OSError, ValueError) as exc:
                raise HTTPException(422, f"claim file refused: {exc}") from exc
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
                # Whether this run can be CONTINUED. Adopt replays the journal
                # and rebuilds the claim from the spec, so a run missing either
                # cannot be carried on; the page needs to know before it offers.
                found.append({
                    "run": d.name, "title": title, "mtime": tf.stat().st_mtime,
                    "continuable": (d / "kernel-journal.jsonl").is_file()
                    and spec_file.is_file(),
                })
        return sorted(found, key=lambda r: r["mtime"], reverse=True)

    @app.get("/api/trace/{run}")
    def trace(run: str, after: int = 0) -> dict:
        """Steps of a run's mind trace; `after` returns only steps > it, so a
        viewer can poll and follow a live agent."""
        d = run_dir(run)
        out = read_trace(d, after=after)
        # A saved tool image is the notebook's record of that state. In an
        # image-channel run it was also model input. It was drawn in whatever
        # style the renderer had then, so runs
        # older than the current renderer would therefore fill the notebook
        # with pictures in a style nothing else uses. Flag those: the UI draws
        # the same state fresh instead, and the saved file stays untouched on
        # disk, because it is evidence of what the model perceived.
        for step in out.get("steps", []):
            image = step.get("image")
            if not image:
                continue
            f = (d / image).resolve()
            step["image_stale"] = (
                not f.is_file() or f.stat().st_mtime < _RENDERER_MTIME
            )
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
        proof_meta, verdict, proof_full = None, None, None
        proof_file = d / "proof.json"
        if proof_file.is_file():
            try:
                proof_full = json.loads(proof_file.read_text())
                proof_meta = {
                    k: proof_full.get(k)
                    for k in ("method", "verified_by", "claim", "statement_review")
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
        # The result in plain English, built from proof.json and the last state
        # the kernel checked. Facts only: this restates the stamp, it never
        # raises it.
        explain_rows, explain_summary = [], None
        if proof_meta is not None:
            lanes = _lanes(read_trace(d)["steps"])
            final = lanes[-1]["check"] if lanes else None
            explain_rows = explain.result_rows(None, proof_full, None, final)
            explain_summary = explain.result_summary(proof_full, None)
        return {"run": run, "spec": spec_meta, "proof": proof_meta, "verdict": verdict,
                "explain": explain_rows, "explain_summary": explain_summary, **out}

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
        lanes = _lanes(read_trace(run_dir(run))["steps"])
        out = []
        for i, lane in enumerate(lanes):
            out.append({
                "step": lane["step"],
                "tool": lane["tool"],
                "check": lane["check"],
                # What actually happened here, in words. A reader must not have
                # to diff two lists of coordinates by eye to see the move.
                "why": explain.step_line(lane["raw"], lanes[i - 1]["raw"] if i else None),
            })
        return out

    @app.get("/api/trace/{run}/progression.png")
    def trace_progression_png(run: str):
        """One picture of the whole run: every distinct state in a single scene.

        Not cached: a live run reaches new states, so a cached file would go
        stale in exactly the case where the picture is most interesting.
        """
        d = run_dir(run)
        lanes = _lanes(read_trace(d)["steps"])
        if not lanes:
            raise HTTPException(404, "this run never drew a configuration")
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
        from .. import intake as intake_mod

        conjecture = body.conjecture.strip() if body.conjecture else ""
        spec_path = None
        problem_id = body.problem_id
        approved_intake = None
        adopt_dir = None

        if body.adopt:
            # Continuing carries its own claim: the earlier run's spec.json is
            # the same document, so asking for a problem here could only name a
            # DIFFERENT one, and the journal would then replay into a world the
            # claim does not describe.
            if body.problem_id or conjecture:
                raise HTTPException(
                    422, "adopt continues an earlier run and brings its own claim; "
                         "do not also give problem_id or conjecture")
            adopt_dir = run_dir(body.adopt)
            if not (adopt_dir / "kernel-journal.jsonl").exists():
                raise HTTPException(
                    422, f"run {body.adopt!r} has no kernel journal, so there is "
                         "nothing to replay; only pi-driven runs can be continued")
            source_spec = adopt_dir / "spec.json"
            if not source_spec.exists():
                raise HTTPException(
                    422, f"run {body.adopt!r} kept no spec.json, so its claim "
                         "cannot be reproduced")
            spec_path = source_spec.resolve()
            problem_id = None
            try:
                # The earlier run's contract, not a fresh one: it was approved
                # for this exact claim, and re-recording it would relabel an
                # approved conjecture as a spec file.
                approved_intake = intake_mod.Intake.load(adopt_dir)
            except (OSError, ValueError, KeyError):
                approved_intake = intake_mod.record(
                    Claim.load(spec_path), str(spec_path), "spec-file")
        elif bool(body.problem_id) == bool(conjecture):
            raise HTTPException(
                422, "give exactly one of problem_id or conjecture, or adopt a run")
        if problem_id:
            try:
                approved_intake = intake_mod.record(get(problem_id), problem_id, "bundled")
            except KeyError as exc:
                # Not bundled: it may be one of the user's own files, which the
                # runtime takes as a path rather than an id.
                on_disk = _disk_specs().get(problem_id)
                if on_disk is None:
                    raise HTTPException(404, str(exc)) from exc
                spec_path = on_disk[1].resolve()
                problem_id = None
        if spec_path is not None and approved_intake is None:
            approved_intake = intake_mod.record(
                Claim.load(spec_path), str(spec_path), "spec-file")
        if not problem_id and spec_path is None:
            from ..llm import FormalizeError, FormalizeRefused, formalize_recorded

            # Approval names ONE claim by hash. Formalizing is a model call and
            # is not deterministic, so re-running it on the approval request
            # produces a different claim and the hash can never match: the gate
            # would be unpassable. The claim the user read is kept here and
            # loaded back by its own hash.
            pending = _pending_claims.get(body.approve_claim_hash or "")
            if pending is not None:
                made = pending
            else:
                try:
                    # The model YOU picked formalizes too. Without this the
                    # formalizer silently used whatever pi listed first, which
                    # here was a small model that returns no tool call at all.
                    made = formalize_recorded(conjecture, provider=body.provider,
                                              model=body.model)
                except FormalizeRefused as refused:
                # 422: the request is answerable, the conjecture is not. Saying
                # so beats substituting a nearby claim the user never asked.
                    raise HTTPException(422, {
                        "error": "formalization_refused",
                        "reason": refused.reason,
                        "formalizer": refused.formalizer,
                    }) from refused
                except FormalizeError as broke:
                    # A formalizer that breaks is not a server fault, and a bare
                    # 500 tells the user nothing they can act on. Name what failed.
                    raise HTTPException(502, {
                        "error": "formalization_failed",
                        "reason": str(broke),
                        "hint": "pick a model in the picker: the default is whichever "
                                "model pi lists first, which may not support the "
                                "structured tool call the formalizer needs",
                    }) from broke
            spec = made.claim
            record = intake_mod.record(spec, made.source_text, "conjecture",
                                       formalizer=made.formalizer)
            if body.approve_claim_hash:
                try:
                    record.approve(body.approve_claim_hash)
                except ValueError as exc:
                    raise HTTPException(409, str(exc)) from exc
            if record.needs_approval:
                # 428 Precondition Required: the caller must read this exact
                # claim and send its hash back before an agent may run on it.
                _remember_claim(record.claim_hash, made)
                raise HTTPException(428, {
                    "error": "claim_approval_required",
                    "claim_hash": record.claim_hash,
                    "formalizer": record.formalizer,
                    "source_text": record.source_text,
                    "description": record.description,
                })
            _pending_claims.pop(record.claim_hash, None)
            spec_dir = traces_root / ".formalized"
            spec_dir.mkdir(parents=True, exist_ok=True)
            spec_path = spec_dir / f"{spec.id}-{uuid.uuid4().hex[:8]}.json"
            spec.save(spec_path)
            approved_intake = record
        try:
            started = control().start(
                problem_id=problem_id,
                spec_path=spec_path,
                provider=body.provider,
                model=body.model,
                thinking_level=body.thinking_level,
                max_turns=max(1, min(body.max_turns, 200)),
                images=body.images,
                adopt=str(adopt_dir) if adopt_dir is not None else None,
            )
        except Exception as exc:  # transport errors map to stable HTTP statuses
            control_error(exc)
        # The record lands in the run directory, so a trace read months later
        # still names the original question and who translated it.
        run_name = started.get("run") if isinstance(started, dict) else None
        if run_name and approved_intake is not None:
            try:
                approved_intake.save(traces_root / str(run_name))
            except OSError:
                pass  # a run that started must not die over its own paperwork
        return started

    @app.post("/api/agent/{run}/pause")
    def agent_pause(run: str) -> dict:
        """Hold the model at its next settled step so the human can work.

        Running tools finish first, so the kernel is never caught mid-write;
        what stops is the model taking a new action.
        """
        try:
            return control().pause(run)
        except Exception as exc:
            control_error(exc)

    @app.post("/api/agent/{run}/resume")
    def agent_resume(run: str) -> dict:
        try:
            return control().resume(run)
        except Exception as exc:
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

    @app.post("/api/agent/{run}/action")
    def agent_action(run: str, body: AgentActionBody) -> dict:
        """Move the world yourself while the agent is running.

        The other half of collaboration: a comment suggests, this places the
        point. The kernel journals it under the user's name and the model is
        told, so neither the trace nor the model mistakes it for the model's
        own move.
        """
        if not body.tool.strip():
            raise HTTPException(422, "action needs a tool name")
        try:
            return control().user_action(run, body.tool.strip(), body.args)
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
