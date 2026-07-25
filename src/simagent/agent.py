"""Kernel-side embodied tool state for pi-managed agent sessions.

This module owns the sandbox actions, trace, proof candidates, and finalization.
It has no provider or model loop. The thin TypeScript package under ``agent/``
drives these tools through ``kernel_transport.py``; only Python proof machinery
can produce verdict artifacts.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np

from . import answer as answer_mod
from . import proof as proof_mod
from .proof import Method
from .search import SearchReport
from .spec import ProblemSpec
from .core.journal import Journal
from .visualize import mpl
from .web.session import SandboxSession

MAX_TOOL_CHARS = 2000

# keep-best ordering for deductive attempts; mirrors proof.py's ladder so a
# later failed attempt can never clobber a verified one
_VERIFIED_RANK = {"sandbox+lean": 3, "lean": 2, "sandbox": 1, "none": 0}

SYSTEM = """You are a mathematician placed inside SimAgent, a 3D math sandbox.
You are embodied: `look` shows you the current configuration as a rendered
image; the other tools move points and run the harness machinery. Use your
eyes — geometry that looks wrong usually is wrong.

Your task: settle the conjecture with one of the ten classical proof methods
(direct, contradiction, contrapositive, induction, cases, construction,
counterexample, exhaustion, combinatorial, infinite descent). That list is
your option menu — pick a line of attack and pursue it in the scene. The
choice is YOURS; the harness only hands you instruments.

Six of those methods have an instrument here, and each is a different
question: `hunt` looks for a counterexample (one bad configuration settles a
`forall` against you), `construct` + `certify` builds a witness for an
existence claim, `exhaust` checks every case of a finite domain,
`sum_of_squares` proves an inequality outright by making the margin a sum of
squares (the only way to establish a `forall` over a CONTINUOUS domain, since
no number of good samples ever proves one), `prove_by_cases` splits the
domain where YOU choose and certifies each half, and `prove_by_induction`
settles every n at once by a base case plus a non-decreasing step. For the
other four methods, reason in the scene and finish with `submit_lean_proof`.

Think in the scene, not in prose: form each hypothesis as a configuration you
can look at, then act on it. Every act is traced — thought, move, resulting
picture — and the harness translates each new state into equations for the
record. Equations are the translation of what you see, not the medium of
thought.

Your senses go beyond `look`: `measure` describes the state qualitatively
(inside/outside, which face, how near the boundary); `view kind=field` paints
the margin over a 2D slice of configuration space — the red region is where
the claim FAILS and the zero-contour is the SHAPE of the claim's boundary
(recognize that shape and you have a conjecture); `view kind=sweep` plots the
margin along one coordinate. `imagine` runs a thought experiment on a fork of
the world (Einstein's move: picture it first); the mainline is untouched —
re-issue the ops for real when the picture looks right.

Declare your line of attack with `plan` (method + one-line idea) before your
first substantive act, and declare again whenever you switch strategy. The
declaration is recorded as intent — it never becomes the verdict; what you
*establish* is stamped by the kernel alone.

The harness is the authority, and it is strict:
- Only these count as established: a `certify` that returns CERTIFIED (exact
  rational arithmetic), an `exhaust` over the full finite domain, a
  `sum_of_squares` certificate the Lean kernel accepts, or
  `submit_lean_proof` code that the Lean kernel accepts (Lean 4 CORE only —
  no imports, no Mathlib, no sorry; prefer `decide`-style statements; end
  with `#print axioms <name>`).
- Your prose is recorded but proves nothing. Never claim more than the
  machinery verified.

Work economically: look, form a hypothesis, test it. Call one tool per turn so
every notebook cell is a safe branch point. When the matter is settled (or you
are honestly stuck), call `finish` with a summary."""

TOOLS = [
    {
        "name": "plan",
        "description": "Declare your current line of attack: one of the ten methods plus a one-line idea. Recorded as intent (re-declare when you switch); the verdict is still stamped only by the kernel.",
        "input_schema": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "enum": [m.value for m in Method]},
                "idea": {"type": "string"},
            },
            "required": ["method", "idea"],
            "additionalProperties": False,
        },
    },
    {
        "name": "look",
        "description": "Render the current configuration and see it (image + exact holds/margin status).",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "sample",
        "description": "Draw a new random valid configuration.",
        "input_schema": {
            "type": "object",
            "properties": {"seed": {"type": "integer"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "set_var",
        "description": "Place one row of a variable exactly (row omitted = set the whole array, flattened).",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "row": {"type": "integer"},
                "values": {"type": "array", "items": {"type": "number"}},
            },
            "required": ["name", "values"],
            "additionalProperties": False,
        },
    },
    {
        "name": "nudge",
        "description": "Move one row of a variable by a delta.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "row": {"type": "integer"},
                "delta": {"type": "array", "items": {"type": "number"}},
            },
            "required": ["name", "row", "delta"],
            "additionalProperties": False,
        },
    },
    {
        "name": "check",
        "description": "Exact numeric check of the current configuration (holds, margin, data).",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "measure",
        "description": "Perceptual measurement of the current configuration: qualitative predicates (inside/outside, which face, near the boundary) plus margin — the compressed description a mathematician would give.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "view",
        "description": "Render an analytical view. kind='field': margin painted over a 2D slice of configuration space (vary two coordinates of one row; zero-contour = the claim's boundary SHAPE — read it!). kind='sweep': margin along one coordinate with zero crossings. kind='trajectory': margin vs step so far.",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["field", "sweep", "trajectory"]},
                "var": {"type": "string"},
                "row": {"type": "integer"},
                "xi": {"type": "integer"},
                "yi": {"type": "integer"},
                "coord": {"type": "integer"},
                "resolution": {"type": "integer"},
            },
            "required": ["kind"],
            "additionalProperties": False,
        },
    },
    {
        "name": "imagine",
        "description": "Thought experiment (Einstein-style): apply ops to a FORK of the world, see the outcomes and a ghost image, then the fork is discarded — the real configuration is untouched. ops entries: {\"op\":\"set\"|\"nudge\",\"target\":name,\"row\":int,\"values\"|\"delta\":[...]}. Kernel actions (certify/exhaust/hunt/lean) are forbidden here: truth only runs on committed state. If the imagined picture looks right, re-issue the ops for real.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ops": {"type": "array", "items": {"type": "object"}},
                "look": {"type": "boolean"},
            },
            "required": ["ops"],
            "additionalProperties": False,
        },
    },
    {
        "name": "refine",
        "description": "Anneal the current configuration toward violation (forall) or witness (exists).",
        "input_schema": {
            "type": "object",
            "properties": {"steps": {"type": "integer"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "hunt",
        "description": "Automated random search; loads the found counterexample/witness into the scene.",
        "input_schema": {
            "type": "object",
            "properties": {"trials": {"type": "integer"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "exhaust",
        "description": "Check EVERY case of the domain (finite integer domains only) — proof by exhaustion.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "certify",
        "description": "Exact-rational verdict for the current configuration; CERTIFIED results count as proof material.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "sum_of_squares",
        "description": (
            "Instrument for a DIRECT proof of an inequality: try to write the claim's "
            "margin as a sum of squares, which makes it nonnegative at EVERY point at "
            "once — the only way to establish a 'forall' over a continuous domain "
            "(hunting can refute one, never prove one). Reach for this when you have "
            "decided the claim is true and the margin is polynomial. It is recorded "
            "only if the Lean kernel accepts the certificate. On failure you get the "
            "reason, so you can choose a different method."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "prove_by_cases",
        "description": (
            "Instrument for a proof by CASES: split the domain in two at a value you "
            "choose, and certify each half separately. Use it when a claim is true but "
            "resists a single certificate. YOU pick where to cut; the harness only "
            "executes the split and checks both halves in Lean."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "var": {"type": "string"},
                "index": {"type": "integer"},
                "at": {"type": "number"},
            },
            "required": ["var", "at"],
            "additionalProperties": False,
        },
    },
    {
        "name": "prove_by_induction",
        "description": (
            "Instrument for a proof by INDUCTION over one integer variable: checks the "
            "base case and certifies that the margin never decreases, which settles "
            "EVERY n at once rather than the bounded range `exhaust` can reach."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "submit_lean_proof",
        "description": "Submit a deductive proof: named method, honest argument, and self-contained Lean 4 CORE code the kernel will check.",
        "input_schema": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "enum": [m.value for m in Method]},
                "argument": {"type": "string"},
                "lean_code": {"type": "string"},
            },
            "required": ["method", "argument"],
            "additionalProperties": False,
        },
    },
    {
        "name": "construct",
        "description": "Sketch: add a named derived object to the scene (midpoint, centroid, circumcenter, barycentric, segment, simplex_volume, vertex). It renders in every later look and recomputes automatically when its ancestors move — your auxiliary construction, like drawing a line in a proof.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "ctor": {"type": "string"},
                "args": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["name", "ctor", "args"],
            "additionalProperties": False,
        },
    },
    {
        "name": "expect",
        "description": "Declare a falsifiable prediction BEFORE acting (e.g. margin < 0 after the next move). The harness scores it mechanically against later committed state — prediction error is how you learn the scene's dynamics. Relations: '<', '<=', '>', '>=', 'holds', 'fails'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "relation": {"type": "string", "enum": ["<", "<=", ">", ">=", "holds", "fails"]},
                "value": {"type": "number"},
                "note": {"type": "string"},
            },
            "required": ["relation"],
            "additionalProperties": False,
        },
    },
    {
        "name": "finish",
        "description": "End the session with a summary of what was (and was not) established.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
    },
]


def _task_prompt(spec: ProblemSpec) -> str:
    return (
        f"Conjecture: {spec.conjecture}\n\nLaTeX: {spec.latex}\n"
        f"Quantifier: {spec.quantifier}. Domain: "
        + ", ".join(
            f"{v.name}{v.shape or '[scalar]'} in [{v.low},{v.high}] ({v.kind})"
            for v in spec.domain
        )
        + "\n\nSettle it. Start by looking at the world."
    )


def _report_from_certify(spec: ProblemSpec, session: SandboxSession, c: dict) -> SearchReport | None:
    """Promote an interactive certified configuration to kernel proof material."""
    if not c.get("certified"):
        return None
    holds = c["holds"]
    if spec.quantifier == "forall" and not holds:
        verdict = "counterexample"
    elif spec.quantifier == "exists" and holds:
        verdict = "witness"
    else:
        return None
    return SearchReport(
        verdict=verdict,
        certified=True,
        trials=0,
        valid_trials=0,
        refine_steps=0,
        seed=0,
        witness={k: np.asarray(v).tolist() for k, v in session.vars.items()},
        witness_check={"holds": holds, "margin": c.get("margin"), "data": {}},
        exact_witness=c.get("exact"),
        margin_min=None,
        margin_max=None,
        notes=["found interactively in an agent session; certified in exact arithmetic"],
    )


class AgentRun:
    """Provider-free tool state behind the pi transport. Cannot stamp verdicts."""

    def __init__(self, spec: ProblemSpec, out_dir):
        self.spec = spec
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "looks").mkdir(exist_ok=True)
        (self.out / "views").mkdir(exist_ok=True)
        (self.out / "imagined").mkdir(exist_ok=True)
        self.session = SandboxSession(spec, self.out)
        self.looks = 0
        self.seq = 0
        self.declared_plans: list[dict] = []  # narrative intent, never the verdict
        self.deductive: proof_mod.Proof | None = None
        self.certify_report: SearchReport | None = None
        self.finished = False
        self.stop_requested = False
        self.summary = ""
        # which model pi routed to this run; SimAgent harnesses any of them, so
        # the run has to say which one produced it
        self.runtime_info: dict = {}
        self._transcript = (self.out / "transcript.jsonl").open("w")
        # The mind trace: thought + act + scene + equation per step, replayable
        # in the web UI's Mind panel (narrative only — proof.json stays boss).
        self.trace = Journal(self.out)
        self.trace.seed(self.session.vars, self.session._check())
        self.views_taken = 0
        self.imaginings = 0
        self.open_expectations: list[dict] = []  # scored on later committed steps
        self._expectation_seq = 0
        self._step_extra: dict | None = None
        self._step_image: str | None = None
        self._step_mode: str = "commit"
        self._step_branch: dict | None = None
        self._step_state: tuple | None = None  # (vars, check, scene) override

    def note_thought(self, text: str | None, kind: str = "text") -> None:
        """Backends feed the model's narrative/thinking here; it attaches to
        the next tool step in the trace."""
        self.trace.note_thought(text, kind)

    def stop(self) -> None:
        """Cooperative cancel (threads can't be killed): every further tool
        call errors, the pi controller winds down, and finalize still records
        whatever the kernel established before the stop."""
        self.stop_requested = True
        self.finished = True
        self.summary = self.summary or "session stopped by the user"

    # -- tool dispatch -------------------------------------------------------

    def dispatch(self, name: str, args: dict, *, tool_call_id: str | None = None):
        """Returns (content, is_error): content is str or a content-block list.

        ``tool_call_id`` is transport metadata only.  Carrying it into the
        transcript and trace lets an external runtime correlate its session
        entries with kernel actions without giving that runtime any verdict
        authority.
        """
        self.seq += 1
        self._step_extra = None
        self._step_image = None
        self._step_mode = "commit"
        self._step_branch = None
        self._step_state = None
        try:
            if self.stop_requested and name != "finish":
                raise RuntimeError("session stopped by the user; no further actions will run")
            if self.finished and name != "finish":
                raise RuntimeError("session already finished; no further actions will run")
            handler = getattr(self, f"_t_{name}", None)
            if handler is None:
                content, is_error = f"unknown tool {name!r}", True
            else:
                content, is_error = handler(**(args or {})), False
        except Exception as e:  # noqa: BLE001 - the model must see and recover from errors
            content, is_error = f"{type(e).__name__}: {e}", True
        result_text = content if isinstance(content, str) else "<image>"
        self._transcript.write(
            json.dumps(
                {
                    "seq": self.seq,
                    "toolCallId": tool_call_id,
                    "tool": name,
                    "args": args,
                    "result": result_text,
                    "error": is_error,
                }
            )
            + "\n"
        )
        self._transcript.flush()
        if self._step_state is not None:  # imagine: journal the hypothetical state
            step_vars, step_check, step_scene = self._step_state
        else:
            step_vars, step_check, step_scene = (
                self.session.vars, self.session._check(), self.session.scene()
            )
        # Predictions score only against COMMITTED state, and never against
        # the expect/plan bookkeeping steps themselves.
        if (self._step_mode == "commit" and not is_error
                and name not in ("expect", "plan", "finish")):
            resolved = self._resolve_expectations(step_check)
            if resolved:
                self._step_extra = {**(self._step_extra or {}),
                                    "resolved_expectations": resolved}
        self.trace.record(
            tool_call_id=tool_call_id,
            tool=name,
            args=args,
            result=result_text,
            error=is_error,
            vars=step_vars,
            check=step_check,
            scene=step_scene,
            extra=self._step_extra,
            image=self._step_image,
            mode=self._step_mode,
            branch=self._step_branch,
        )
        return content, is_error

    def _status(self) -> str:
        check = self.session._check()
        return json.dumps(check, default=str)[:MAX_TOOL_CHARS]

    def _t_plan(self, method: str, idea: str):
        m = Method(method)  # ValueError on junk -> the model sees and recovers
        self.declared_plans.append({"method": m.value, "idea": idea})
        self._step_extra = {"declared_method": m.value, "idea": idea}
        return (
            f"approach recorded: {m.value} — {idea!r}. Intent only; the kernel "
            "stamps what you actually establish."
        )

    def _t_look(self):
        self.looks += 1
        path = self.out / "looks" / f"look_{self.looks:03d}.png"
        scene = self.session.scene()
        if not scene:
            return "scene could not be built (degenerate configuration?)"
        mpl.render_png(scene, path, title=self.spec.title)
        self._step_image = f"looks/{path.name}"  # what the agent saw, for the trace
        data = base64.standard_b64encode(path.read_bytes()).decode()
        return [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
            {"type": "text", "text": f"status: {self._status()}"},
        ]

    def _t_sample(self, seed: int | None = None):
        self.session.sample(seed)
        return f"sampled; status: {self._status()}"

    def _t_set_var(self, name: str, values: list, row: int | None = None):
        self.session.set_value(name, row, values)
        return f"set; status: {self._status()}"

    def _t_nudge(self, name: str, row: int, delta: list):
        cur = np.asarray(self.session.vars[name][row], dtype=float)
        self.session.set_value(name, row, (cur + np.asarray(delta, dtype=float)).tolist())
        return f"nudged; status: {self._status()}"

    def _t_check(self):
        return self._status()

    def _t_measure(self):
        from .core.measure import measure_state

        state = measure_state(self.session.vars, self.session._check())
        return json.dumps(state, default=str)[:MAX_TOOL_CHARS]

    def _t_view(self, kind: str, var: str | None = None, row: int = 0,
                xi: int = 0, yi: int = 1, coord: int = 0, resolution: int = 48):
        from . import views as views_mod
        from .core.journal import read_trace

        self.views_taken += 1
        path = self.out / "views" / f"view_{self.views_taken:03d}_{kind}.png"
        if kind == "field":
            _, meta = views_mod.render_field(
                self.spec, self.session.comp, self.session.vars, path,
                var=var, row=row, xi=xi, yi=yi, resolution=max(8, min(resolution, 96)),
            )
        elif kind == "sweep":
            _, meta = views_mod.render_sweep(
                self.spec, self.session.comp, self.session.vars, path,
                var=var, row=row, coord=coord, resolution=max(8, min(resolution, 400)),
            )
        elif kind == "trajectory":
            steps = read_trace(self.out)["steps"]
            _, meta = views_mod.render_trajectory(steps, path, title=self.spec.title)
        else:
            raise ValueError(f"unknown view kind {kind!r}")
        self._step_image = f"views/{path.name}"
        self._step_extra = {"view": meta}
        data = base64.standard_b64encode(path.read_bytes()).decode()
        return [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
            {"type": "text", "text": f"view metadata: {json.dumps(meta, default=str)}"},
        ]

    _IMAGINE_OPS = ("set", "nudge", "construct", "remove")

    def _t_imagine(self, ops: list, look: bool = True):
        """Thought experiment on a fork of the world; mainline untouched."""
        from .core.op import apply_op
        from .core.journal import diff_vars
        from . import views as views_mod

        if not isinstance(ops, list) or not ops:
            raise ValueError("imagine needs a non-empty list of ops")
        for op in ops:
            if not isinstance(op, dict) or op.get("op") not in self._IMAGINE_OPS:
                raise ValueError(
                    f"imagine allows only world ops {self._IMAGINE_OPS}; got "
                    f"{op.get('op') if isinstance(op, dict) else op!r} — kernel actions "
                    "(certify/exhaust/hunt/lean) run only on committed state"
                )
        base_vars = {k: np.array(v, dtype=float) for k, v in self.session.vars.items()}
        base_scene = self.session.scene()
        fork = self.session.world.fork()
        outcomes: list[dict] = []
        for i, op in enumerate(ops):
            try:
                apply_op(fork, op)
            except Exception as e:  # noqa: BLE001 - a failed imagined move is an outcome
                outcomes.append({"op": i, "error": f"{type(e).__name__}: {e}"})
                break
            hyp_vars = fork.free_values()
            try:
                res = self.session.comp.check(**hyp_vars)
                check = {"holds": res.holds, "margin": res.margin, "data": res.data}
            except Exception as e:  # noqa: BLE001
                check = {"error": f"{type(e).__name__}: {e}"}
            outcomes.append({
                "op": i,
                "check": check,
                "diff": diff_vars(base_vars, hyp_vars),
            })
        hyp_vars = fork.free_values()
        try:
            hyp_scene = self.session.comp.build_scene(**hyp_vars)
        except Exception:  # noqa: BLE001
            hyp_scene = []
        try:
            hyp_check_res = self.session.comp.check(**hyp_vars)
            hyp_check = {"holds": hyp_check_res.holds, "margin": hyp_check_res.margin,
                         "data": hyp_check_res.data}
        except Exception as e:  # noqa: BLE001
            hyp_check = {"error": f"{type(e).__name__}: {e}"}

        self.imaginings += 1
        self._step_mode = "imagine"
        self._step_branch = {"base_step": self.trace.steps, "ops": ops, "outcomes": outcomes}
        self._step_state = (hyp_vars, hyp_check, hyp_scene)

        content: list[dict] = []
        if look and hyp_scene:
            path = self.out / "imagined" / f"imag_{self.imaginings:03d}.png"
            views_mod.render_ghost(base_scene, hyp_scene, path,
                                   title=f"imagined — {self.spec.title}")
            self._step_image = f"imagined/{path.name}"
            data = base64.standard_b64encode(path.read_bytes()).decode()
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": "image/png", "data": data}})
        summary = {
            "imagined": True,
            "mainline_unchanged": True,
            "outcomes": outcomes,
            "note": "fork discarded — re-issue the ops for real if the picture looks right",
        }
        content.append({"type": "text", "text": json.dumps(summary, default=str)[:MAX_TOOL_CHARS]})
        return content

    def _t_refine(self, steps: int = 300):
        r = self.session.refine(steps)
        return json.dumps(r, default=str)

    def _t_hunt(self, trials: int = 1500):
        r = self.session.hunt(trials)
        self._step_extra = {"verdict": r.get("verdict"), "certified": r.get("certified")}
        return json.dumps(r, default=str)[:MAX_TOOL_CHARS]

    def _t_exhaust(self):
        r = self.session.exhaust()
        self._step_extra = {"verdict": r.get("verdict"), "certified": r.get("certified")}
        return json.dumps(r, default=str)[:MAX_TOOL_CHARS]

    def _t_certify(self):
        r = self.session.certify()
        report = _report_from_certify(self.spec, self.session, r)
        if report is not None:
            self.certify_report = report
        self._step_extra = {"certified": r.get("certified"), "exact": r.get("exact")}
        return json.dumps(r, default=str)[:MAX_TOOL_CHARS]

    def _keep_best_deductive(self, attempt) -> None:
        """Never let a later failed attempt clobber a verified one."""
        rank = _VERIFIED_RANK
        if self.deductive is None or rank.get(attempt.verified_by, 0) >= rank.get(
            self.deductive.verified_by, 0
        ):
            self.deductive = attempt

    def _t_sum_of_squares(self):
        """The model chose a direct proof; the harness runs the instrument.

        Choosing to call this IS the method declaration, exactly as `hunt` is
        the counterexample instrument and `exhaust` the exhaustion one. The
        kernel still decides whether anything was established."""
        from . import library

        # No search required first: a certificate stands on its own, and making
        # the model hunt before it may prove would be the harness dictating the
        # order of work. A search that already found a counterexample is the
        # one case this refuses.
        report = self.best_report()
        notes: list[str] = []
        proof = proof_mod.sos_proof(
            self.spec, report, out_dir=self.out,
            spec_trusted=library.is_bundled(self.spec), notes=notes,
        )
        if proof is not None:
            self._keep_best_deductive(proof)
        self._step_extra = {"method": "direct",
                            "verified_by": proof.verified_by if proof else "none"}
        return json.dumps({
            "proved": proof is not None,
            "verified_by": proof.verified_by if proof else "none",
            "argument": proof.argument if proof else None,
            "notes": notes,
        }, default=str)[:MAX_TOOL_CHARS]

    def _t_prove_by_cases(self, var: str, at: float, index: int = 0):
        from . import library

        notes: list[str] = []
        proof = proof_mod.cases_proof(
            self.spec, var, index, at, out_dir=self.out,
            spec_trusted=library.is_bundled(self.spec), notes=notes,
        )
        if proof is not None:
            self._keep_best_deductive(proof)
        self._step_extra = {"method": "cases",
                            "verified_by": proof.verified_by if proof else "none"}
        return json.dumps({
            "proved": proof is not None,
            "verified_by": proof.verified_by if proof else "none",
            "argument": proof.argument if proof else None,
            "notes": notes,
        }, default=str)[:MAX_TOOL_CHARS]

    def _t_prove_by_induction(self):
        from . import library

        notes: list[str] = []
        proof = proof_mod.induction_proof(
            self.spec, out_dir=self.out,
            spec_trusted=library.is_bundled(self.spec), notes=notes,
        )
        if proof is not None:
            self._keep_best_deductive(proof)
        self._step_extra = {"method": "induction",
                            "verified_by": proof.verified_by if proof else "none"}
        return json.dumps({
            "proved": proof is not None,
            "verified_by": proof.verified_by if proof else "none",
            "argument": proof.argument if proof else None,
            "notes": notes,
        }, default=str)[:MAX_TOOL_CHARS]

    def _t_submit_lean_proof(self, method: str, argument: str, lean_code: str | None = None):
        attempt = proof_mod.deductive_proof(
            self.spec, method, argument, lean_code, out_dir=self.out
        )
        self._step_extra = {"method": method, "verified_by": attempt.verified_by}
        self._keep_best_deductive(attempt)
        detail = (attempt.lean_report or {}).get("output", "no Lean code given")
        return f"recorded: method={method}, verified_by={attempt.verified_by}. Lean says: {detail[:800]}"

    def _t_construct(self, name: str, ctor: str, args: list):
        result = self.session.construct(name, ctor, list(args))
        self._step_extra = {"construct": result}
        if result["degenerate"]:
            return (f"constructed {name} = {ctor}({', '.join(args)}) — DEGENERATE at the "
                    "current configuration (no value); it will recompute when ancestors move")
        return (f"constructed {name} = {ctor}({', '.join(args)}) = {result['value']}; "
                "it now renders in every look and follows its ancestors")

    _RELATIONS = {
        "<": lambda m, v: m is not None and m < v,
        "<=": lambda m, v: m is not None and m <= v,
        ">": lambda m, v: m is not None and m > v,
        ">=": lambda m, v: m is not None and m >= v,
    }

    def _t_expect(self, relation: str, value: float | None = None, note: str = ""):
        if relation in self._RELATIONS and value is None:
            raise ValueError(f"relation {relation!r} needs a value")
        if relation not in self._RELATIONS and relation not in ("holds", "fails"):
            raise ValueError(f"unknown relation {relation!r}")
        self._expectation_seq += 1
        exp = {"id": self._expectation_seq, "relation": relation,
               "value": value, "note": note}
        self.open_expectations.append(exp)
        self._step_extra = {"expect": exp}
        return (f"expectation #{exp['id']} recorded: margin {relation} "
                f"{value if value is not None else ''} — it will be scored against "
                "the next committed states")

    def _resolve_expectations(self, check: dict) -> list[dict]:
        """Mechanical scoring: no judgment, just comparison against the new
        committed state. Prediction error is the teacher."""
        if not self.open_expectations or check.get("error"):
            return []
        margin, holds = check.get("margin"), check.get("holds")
        resolved = []
        for exp in self.open_expectations:
            rel = exp["relation"]
            if rel in ("holds", "fails"):
                if holds is None:
                    continue
                ok = bool(holds) if rel == "holds" else not bool(holds)
                actual = f"holds={holds}"
            else:
                if margin is None:
                    continue
                ok = self._RELATIONS[rel](float(margin), float(exp["value"]))
                actual = f"margin={float(margin):.6g}"
            resolved.append({**exp, "ok": ok, "actual": actual})
        self.open_expectations = [
            e for e in self.open_expectations if all(r["id"] != e["id"] for r in resolved)
        ]
        return resolved

    def _t_finish(self, summary: str):
        self.finished = True
        self.summary = summary
        return "session ended"

    # -- kernel finalization -------------------------------------------------

    def best_report(self) -> SearchReport | None:
        """Prefer the strongest kernel-grade report accumulated in the session.

        Uses the session's kept-best (never-downgraded) report plus any
        certified interactive configuration, and returns the strongest.
        """
        from .web.session import _report_rank

        candidates = [
            r for r in (self.session.best_report, self.certify_report) if r is not None
        ]
        if not candidates:
            return None
        return max(candidates, key=_report_rank)

    def finalize(self) -> tuple[proof_mod.Proof | None, SearchReport | None, dict]:
        self._transcript.close()
        from . import library

        report = self.best_report()
        proof = None
        if report is not None:
            proof = proof_mod.mechanized_proof(
                self.spec, report, out_dir=self.out, spec_trusted=library.is_bundled(self.spec)
            )
        if proof is None and self.deductive is not None:
            proof = self.deductive
        artifacts: dict[str, str] = {}
        if report is not None:
            artifacts.update(answer_mod.write_answers(self.spec, report, self.out, proof=proof))
        if proof is not None:
            artifacts["proof"] = proof_mod.save_proof(proof, self.out)
            if proof.lean_file:
                artifacts["lean"] = proof.lean_file
        who = self.runtime_info
        provenance = (
            f"Model: {who.get('provider', '?')}/{who.get('model', '?')}"
            + (f" (thinking: {who['thinkingLevel']})" if who.get("thinkingLevel") else "")
            if who else
            "Model: not recorded (the run did not report which model pi routed)"
        )
        (self.out / "agent_summary.md").write_text(
            "# Agent summary (the model's narrative — see proof.json for what is verified)\n\n"
            + provenance + "\n\n"
            + self.summary
        )
        if who:
            (self.out / "runtime.json").write_text(json.dumps(who, indent=2))
        artifacts["agent_summary"] = str(self.out / "agent_summary.md")
        artifacts["transcript"] = str(self.out / "transcript.jsonl")
        artifacts["trace"] = str(self.trace.path)
        # Close the journal LAST: its end marker tells live viewers the run is
        # complete, so proof.json/answer.md must already be on disk by then
        # (otherwise a live notebook can read "done" and miss the verdict).
        self.trace.close()
        return proof, report, artifacts
