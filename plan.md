# SimAgent v2 — Master Plan

> This document is self-contained: it carries the vision, the research that
> shaped it, every design decision with its rationale, the architecture, and
> the phased execution plan. A reader (human or agent) starting from only this
> file plus the repo should reach the same understanding that produced it.

---

## 1. What SimAgent is, and its spirit

SimAgent is a **correctness-first harness where humans and LLM agents solve
math by communicating through visuals.** The agent is *embodied* in a sandbox:
it looks at rendered scenes (vision), moves points, hunts for counterexamples,
certifies in exact arithmetic, and submits Lean proofs. The human watches — and
steers — through a Jupyter-style **reasoning notebook** that streams the
agent's mind step by step.

The spirit (why this exists):

- **Imagination first, formalism second.** Einstein and Newton reasoned
  through imagined scenes — the elevator, the cannonball — and only then
  formalized. SimAgent gives an LLM the same loop: imagine → visualize →
  act → *then* the harness translates each state into equations. **Equations
  are the translation of thought, never the medium of thought.**
- **The sandbox is the agent's mind, and humans can see into it.** Like a
  coding agent showing diffs, SimAgent shows a math agent's visual chain of
  thought: thought → act → picture → equation → diff, per step.
- **The honesty ladder is sacred.** Prose proves nothing. Verdicts come only
  from machinery: `verified_by: sandbox+lean > sandbox > lean > none`. Only
  `src/simagent/proof.py` stamps verdicts. The ten classical proof methods
  (direct, contradiction, contrapositive, induction, cases, construction,
  counterexample, exhaustion, combinatorial, infinite descent) are the agent's
  declared *option menu*; what it *establishes* is stamped by the kernel alone
  (the notebook shows "declared vs established").

## 2. Where v0.1 stands (already built and verified)

- Pipeline: conjecture → ProblemSpec (JSON + exec'd code strings) → numpy
  sandbox → search (random + margin-guided annealing; **margin > 0 ⇔ property
  holds**) → sympy **exact rational certification** → generated **Lean 4 core
  certificates** (`by decide`, rationals as integer pairs, axiom-free,
  fail-closed checker) → answer.md/.tex/conjecture.lean. Lean 4.32.1 via
  ~/.elan.
- `simagent agent`: embodied LLM loop (two backends: Anthropic SDK `api`, and
  `claude-code` via the Claude Agent SDK on the user's `claude` login, tools
  bridged over in-process MCP, `look` images as MCP image content). Tools:
  plan / look / sample / set_var / nudge / check / refine / hunt / exhaust /
  certify / submit_lean_proof / finish. Cooperative stop. Verdicts only from
  kernel state.
- **Mind trace** (the v0.1 path was `trace.py`; now `core/journal.py` writes
  `trace.jsonl`): each step records the model's thought, the act, the scene
  graph, an equation
  translation, and a diff vs the previous step.
- **Reasoning notebook** (`src/simagent/web/`): In[]/Out[] cells streaming the
  trace live (approach/thinking/act/picture/equations/diff), interactive
  three.js overlay per cell, replay of past runs, stop/restart, verdict cell
  sourced only from proof.json/answer.md.
- 4 bundled known-answer problems (2 certified-disproved geometry, 1
  evidence-only Euler, 1 exhaustion-proved arithmetic); 61+ offline tests;
  hardening tests pin the audit fixes (fail-closed exhaustion, Lean checker
  name-binding, statement_review honesty).

## 3. Research context (what shaped v2)

Condensed findings from the research sweeps (July 2026):

- **OpenAI Five**: no pixels — semantic entity lists + tiny terrain grids;
  spatial intuition learned from coordinates via massive RL. Lesson: structured
  state is the substrate of precision; but a *frozen* LLM cannot learn from raw
  coordinates, so we must render into the modalities where its pretrained
  priors live (vision gestalt + language relations) — **dual-coding**.
- **Blender**: one authoritative data model, mutated ONLY by named operators,
  with a dependency graph recomputing derived data; every UI is a dumb view.
- **CAD kernels** (Parasolid/OCC/FreeCAD): the authoritative state is the
  *recipe* (named refs + parameters + constraints); coordinates are derived by
  replay. Their hardest problem (stable topological naming) is free for us —
  math objects are already named symbols.
- **Ansys / CAE post-processing**: the geometry is only the canvas; what
  engineers look at is the *field* painted on it (contours + calibrated
  legend), probes, extrema callouts, convergence plots. **SimAgent's margin is
  a scalar field over configuration space — render it.** A field view of the
  triangle claim makes the zero-contour literally the Thales circle: search
  becomes perception, perception becomes symbolic conjecture.
- **Visual Sketchpad** (NeurIPS 2024): letting a model draw auxiliary lines
  and look at its own drawing gives +11–23% on geometry — evidence for the
  `construct` tool.
- **AlphaGeometry / Newclid**: LM proposes constructions, symbolic kernel
  deduces — same honesty split as ours; Newclid (open source) is a candidate
  future deductive backend.
- **Landscape sweep conclusion**: *no open-source project combines* embodied
  perceive-act loop + numeric falsification + exact certification + Lean gate
  + visual mind-trace UI. Nearest per-pillar: GeoGebra MCP servers (sandbox
  bridge, no kernel), "Learning to Disprove" (counterexamples+Lean, text-only),
  Visual Sketchpad (draws, verifies nothing), FunSearch/PatternBoost
  (evaluator loops, blind), LeanCopilot (in-Lean tactics). **The combination
  is the moat; the honesty ladder is its heart.**
- **pi** (github.com/earendil-works/pi, MIT, TypeScript): agent harness
  monorepo. `@earendil-works/pi-ai` = unified multi-provider LLM API;
  `@earendil-works/pi-agent-core` = agent runtime with tool calling, state
  management, **session branching**, event streaming. This is exactly the
  plumbing we hand-rolled.

## 4. Decision log (all user-approved)

| # | decision | rationale |
|---|---|---|
| D1 | **Dimension-agnostic core** — dimension enters only at the boundaries (Space in, View out) | the truth layer is already dimension-free; 3D is the default *view*, not the ontology |
| D2 | **Eight primitives ("atoms")**, first-principles, smallest bricks | long-term survival: correctness + maintainability over features |
| D3 | **Closed op/constructor vocabulary replaces LLM-emitted exec'd code strings** | typed, safe, LLM-friendly (AlphaGeometry-proven); exec path deleted after migration |
| D4 | **Imagination mechanic, visible** — thought experiments render as dashed Im[n] cells | the Einstein spirit is the product; explicit chain of thought for humans |
| D5 | **Multi-agent: FULL collaboration** — peers can inspect, adopt, and branch from each other, with provenance | user choice over the simpler peer-aware option |
| D6 | **d>3 ships without Lean certificates** — verdicts top out at `sandbox` (exact rationals), stated explicitly to users | leangen's determinant encoding caps at d≤3; honesty over delay; LU-witness encoding is the documented post-v2 path |
| D7 | **Select-and-comment steering** per GitHub issue #6 — comments steer, never certify | human joins the loop as collaborator, not spectator |
| D8 | **Reversible sessions** — branch from any step with optional redirection | rewind = journal prefix replay; branch = fork + provenance |
| D9 | **Adopt pi** for agent loop, providers, state, steering, branching; SimAgent keeps only kernel + UX | massive complexity reduction; pi natively has what P6 would have hand-built |
| D10 | **pi-style separated codebases**: kernel/ (Python) · agent/ (TS, thin) · ui/ | changes never override each other; each layer owns one thing |

## 5. The eight atoms (the core)

Everything in the domain — *harnessing an LLM to do math through
visualization* — composes from eight primitives. Dimension-aware code exists
ONLY in Space and View.

| primitive | physical analogy | role |
|---|---|---|
| **Space** | configuration space | input boundary: `sample / valid / perturb / exact / enumerate`. v1: `Box(ℝᵈ)`, `IntBox(ℤᵈ)` |
| **Entity** | particle | named, stable id; *free* (value in a Space) or *derived* (recipe over entities — coordinates are consequences, the CAD lesson) |
| **Op** | force | THE only mutation channel (Blender lesson) = the LLM's entire action vocabulary; closed registry |
| **Derive** | physical law | dependency graph; derived entities recompute when ancestors move |
| **Measure** | observable | perception: margins + qualitative predicates ("O outside, beyond face BCD"); the claim's check is a distinguished measure; the LLM never sees raw coordinate dumps — **compression is perception** |
| **Claim** | hypothesis under test | quantifier + free Spaces + distinguished Measure |
| **Journal** | worldline / lab notebook | dynamics first-class: state = replay(journal) = save format = undo = notebook feed; `imagine` branches = thought experiments; annotation events = plan / expect / user_comment |
| **View** | detector / photograph | output boundary: identity (d≤3), **field** (margin painted over a 2D slice, fixed diverging colormap centered at 0, zero-contour + min marker — the Ansys lesson), sweep, ghost, trajectory, measure-plot. Pictures explain, never prove |

**Completeness argument**: every activity is one of five verbs — *pose* (a
Claim), *act* (Ops → Journal), *perceive* (Measures + Views), *conclude*
(truth layer on exact Space points), *converse* (annotation events — model
narrative, declared intent, user comments; steering, never truth).

**Derivations** (existing/planned features as compositions):
sample = Op(Space.sample) · refine = loop{perturb → Measure → keep} · hunt =
sampleⁿ + refine · exhaust = Space.enumerate × Measure · certify = Space.exact
+ exact Measure · construct = Op(add derived) + Derive · diff = Journal[n] −
Journal[n−1] · probe = zero-op imagine · imagine = Ops on a Journal fork,
never merged · plan/expect/user_comment = annotation events · undo/rewind =
journal prefix replay · branch = fork(replay(prefix)) + provenance · steering
= user_comment consumed as the next user turn · multi-agent = N Journals on
one Claim + peers Measure · field view = View over Measure on a Space slice.

## 6. Architecture: pi does the plumbing, we do the math and the face

```
kernel/   Python (uv) — THE MOAT
  src/simagent/core/    space.py entity.py op.py derive.py measure.py claim.py journal.py report.py
  src/simagent/truth/   proof.py lean_check.py sandbox/{geometry,certify,leangen}.py   [rules unchanged]
  src/simagent/views/   identity field sweep ghost trajectory + scene.py mpl.py manim_gen.py
  mcp_server.py         exposes the tool surface over MCP stdio
  cli.py                solve / play / list stay pure-Python
agent/    TypeScript (npm/bun, exact-pinned) — THIN (~300 lines)
  pi-agent-core Agent + pi-ai provider wiring + kernel MCP tools + system prompt
  session store, WS/event bridge + artifact serving for the UI
ui/       vanilla JS + vendored three.js — THE FACE
  reasoning notebook: merges pi session events with the kernel journal
```

- **Two records, one story**: pi session log = the *conversation* (thoughts,
  tool bracketing, steering, branch tree); kernel `journal.jsonl` = the *world*
  (ops, state, scenes, equations, diffs, imagine branches). Correlated by
  tool-call id. The kernel journal alone replays world state — reproducibility
  never depends on pi.
- **Honesty is structural**: verdicts are computed only in the Python kernel;
  pi transports messages. Comments/steering ride pi AND are journaled as
  `user_comment` events — narrative, never verdict material (hardening test).
- **Deleted by this move**: agent.py's manual Anthropic loop + claude-code
  backend (~450 lines), the web job runner (start/stop/status/single-flight/
  comment queue), backend resolution. **Kept**: tool definitions + dispatch
  handlers (become the MCP server), `_report_from_certify`, `best_report`,
  `finalize` (kernel-side, where verdicts live).
- Layering enforced by `tests/test_layering.py` (AST walk): core → truth →
  views; kernel never imports pi/web/llm; ui talks only HTTP/WS.

### Key mechanics

**Imagine (the Einstein mechanic).** `imagine(ops=[...], look=True)` — one
tool call, one journal event, no nesting: fork the World, apply ops through
the same `apply_op`, measure after each, render a ghost view, journal
`{mode:"imagine", branch:{base_step, ops, outcomes}}`, discard the fork.
Mainline untouched; diff baseline advances only on commit. Kernel-grade ops
(certify/exhaust/hunt/lean) are REJECTED inside imagine — truth only runs on
committed state. Probe = one-op imagine without look. No promotion op: the
agent re-issues ops for real ("imagined it, looked right, did it").

**expect (prediction-forced perception).** `expect(measure, relation, value,
note)` journals a prediction; later commits resolve it mechanically; the
notebook shows ◌ → ✓/✗ chips with actuals. This channel matters *more* as d
grows (vision weakens, prediction error doesn't).

**Steering (issue #6).** Select a cell, a thought/act line, an equation line,
or a 3D primitive (raycast pick) → comment popover → delivered via pi steering
as a user turn + journaled as `user_comment` + rendered as a comment cell.
Comments steer reasoning; they can never certify anything.

**Reversibility.** Every cell: "branch from here" → new session whose journal
is seeded by replaying the source prefix (events carry `provenance:{run,step}`),
pi session branched accordingly, optional steering comment as first turn.

**Multi-agent (full collaboration).** Group = `runs/<group>/claim.json` +
`agents/<run>/` (each run dir as today; agents write only their own).
`peers()` = compact summaries (declared plan, tip margin, best kernel result).
`adopt(run, what)` = copy a peer's witness/entity into own world as ordinary
ops with provenance (re-certified locally — automatic, since certify only runs
on own committed state). Fork-from-peer = the same branch machinery.
Claim-level best = recompute-on-read over run reports via `_report_rank`;
kernel-grade merges, narrative never does. Cap 4 concurrent. Race-free by
construction: all sharing is read-append + copy-on-adopt.

**UI per-step contract**: PAST = diff · PRESENT = state + measures (incl.
qualitative) + picture · FUTURE = declared approach + pending expect chips +
imagined branches. Thinking always visible. Cell kinds are additive and keyed
on journal fields (old traces keep rendering). Multi-agent page = claim header
(statement + merged best) over lanes. d>3 verdict cells and answer.md carry
explicitly: *"no Lean certificate available above d=3 — verified by exact
rational arithmetic (sandbox) only."*

## 7. Phases (each ends: full offline suite green + its gate)

- **P0 — pi spike + go/no-go (1 session).** Exact-pin pi-ai/pi-agent-core;
  extract `kernel/mcp_server.py` from the existing claude-code tool bridge;
  minimal TS agent runs a scripted session. Verify 4 assumptions: image tool
  results reach the model · mid-run steering · session branch · auth paths
  (API key now; Claude-subscription OAuth noted honestly; fallback = keep the
  legacy claude-code backend behind a flag). Any failed assumption gets a
  written fallback before proceeding.
- **P1 — Space (1).** Box/IntBox/from_varspec; absorb `sample_vars`,
  `_refine`'s perturb, `run_exhaustive`'s enumeration; d-genericity fixes
  (`rationalize_array`/`exact_repr` any-ndim, `_int_repr` recursive).
  Gate: bundled reports byte-identical; d=5 Box test.
- **P2 — Entity/Op/Derive (2).** Recipe model; SandboxSession = thin shell
  over `apply_op` (public API unchanged). Gate: fork isolation + recompute
  tests; existing web/agent tests untouched.
- **P3 — Measure/Claim/Journal (2).** Qualitative predicates; Claim plus the
  temporary migration adapter that P5 later removed; journal promotion into
  `core/journal.py` (mode, annotation events, replay(), prefix-fork).
  Gate at the time: adapter equivalence and golden old/new traces.
- **P4 — Views/probe/imagine (2).** views/ package; imagine + probe tools;
  hull split (generic `hull_facets` d≤8 fail-closed; 3D pair kept for the
  Euler spec); notebook Im-cells + view cells. Gate: triangle field view's
  zero-contour = Thales circle (metadata assert); imagine leaves mainline
  untouched; kernel-ops rejected inside imagine.
- **P5 — construct/expect/native Claims/exec retirement (landed).** construct +
  expect + chips; bundled specs became native Claims; the d=4 known-answer gate
  landed; formalize emits `claim/1`; executable spec paths and migration shims
  are now deleted. Old traces remain readable, while old code-bearing problem
  files are refused. Gate: all ground truths with no `exec` or `eval` call in
  production source.
- **P6 - pi integration (landed).** `agent/` is the exact-pinned pi runtime and
  session service; the Python provider backends and web job runner are gone.
  Notebook and CLI launch pi sessions through a strict JSONL control bridge.
  Select-and-comment covers cells, thought/action/equation lines, and 3D
  raycast picks; branches use settled pi checkpoints, hash-verified kernel
  replay, and provenance chips. Gates: comment-cannot-change-verdict hardening
  test, visible next-turn steering response, and exact prefix branch replay.
- **P7 — UX v2 + multi-agent (2).** Event/journal merge in the notebook;
  lanes; peers/adopt/fork-from-peer; merge_best; provenance UI. Gate:
  test_collab with injected fake runners (merge prefers certified; adoption
  journals provenance; stopping one lane leaves the other running); single-run
  UI identical without a group.

Total ≈ 12 sessions.

## 8. Risks

1. **pi API youth** → exact pins; P0 spike before dependence; kernel never
   imports pi (blast radius = thin agent/ layer only).
2. **Claude-subscription auth via pi-ai unknown** → P0 verifies; fallback:
   legacy claude-code backend behind a flag until pi covers it.
3. **Polyglot toolchain** (uv + bun/npm) → docs + CI both; ui stays
   framework-free.
4. **Image tool results through pi** → P0 gate; fallback: look returns an
   artifact path and agent/ inlines the image into the model turn.
5. **Event↔journal drift** → tool-call id in both; kernel journal is the sole
   source of world-truth.
6. **leangen d≤3 cap** → documented + explicit wording (D6); LU-witness Lean
   encoding is the designed post-v2 extension (emit exact L,U as rational
   atoms; kernel checks A=L·U ∧ diag(U)≠0; polynomial size, decide-able).
7. **Exec deletion breakage** → last step of P5, gated on native Claims +
   Claim formalize + legacy JSON converter; adapter kept one release beyond.
8. **Notebook churn** → additive cell kinds; permissive readers; golden
   fixtures for both trace formats.
9. **replay() cost on long runs** → journal keeps a live tip World; replay
   only for load/branch; snapshot events every 100 steps if needed.

## 9. Verification (end-to-end definitions of done)

- Every phase: `.venv/bin/python -m pytest -q` — offline, green.
- After P5: `simagent solve circumcenter-4simplex` → DISPROVED, certified,
  verdict text carries the d>3 no-Lean notice.
- After P6: during a live session — select an equation line, comment → comment
  cell appears, the agent visibly responds next step, `user_comment` is in the
  journal, verdict provenance unchanged (hardening test). "Branch from here"
  on step N continues from exactly that state with the comment as first turn.
- After P7: a 2-agent group run streams two lanes; adopt shows a provenance
  chip; the claim header shows the merged best; stopping one lane leaves the
  other running.
- The flagship demo (realized = this works): *type a conjecture in plain words,
  any dimension → notebook streams plan → look → imagine (dashed) → field view
  where the failure region has a visible shape → construct the object that
  names it → certify → Lean stamp (d≤3) → verdict cell: "declared and
  established: counterexample — verified by sandbox+lean."*

## 10. References

- Repo issues: #6 (select-and-comment — the steering spec and acceptance
  criteria), #1–#5 (Lean shapes, Mathlib bridge, domains, LLM search
  strategies, Manim narration).
- pi: https://github.com/earendil-works/pi (`@earendil-works/pi-ai`,
  `@earendil-works/pi-agent-core`; MIT).
- Research anchors: Visual Sketchpad (arXiv 2406.09403) · AlphaGeometry
  (Nature 2024) / Newclid · PatternBoost (arXiv 2411.00566) · Learning to
  Disprove (arXiv 2603.19514) · SayPlan (arXiv 2307.06135) · OpenAI Five
  (arXiv 1912.06680) · Ansys/PyAnsys post-processing docs (field views,
  probes) · blender-mcp / GeoGebra MCP servers (tool-bridge precedents).
- Internal: ARCHITECTURE.md (kernel rules — read before touching the kernel),
  CLAUDE.md (conventions, environment quirks), GUIDE.md (user walkthrough).
