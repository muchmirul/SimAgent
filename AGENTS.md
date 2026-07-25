# SimAgent — notes for the agent
THIS PROJECT IS ONLY HARNESS, thinking or any thought must come from the model itself, which must not be provided here

AGENTS.md and CLAUDE.md are the same file, kept byte-identical on purpose so
every tool reads one source of truth. Edit one, copy it to the other.

Pi-managed harness for visualization-based, finite-dimensional math: a small
correctness-first kernel. The LLM reasons; the harness records only what it can
execute or check; the Lean kernel is the sole authority on deduction. Read
ARCHITECTURE.md before touching the kernel. Current baseline: v2 P0-P6 landed.

core idea of sim agent is this :
1. simagent is the harness on how to get of the best harness to routed models llm, to solve any math problem by experiencing doing math by viz and equation is just formalization. instead of just using text file. and gathering information from outside. doing it by first principle.
2. as a toll human and ai agent can collaborate on solving, sometimes human get stuck agent help, and sometime human giving idea while agent stuck. this done by seamless ui that human can giving comment on the step that agent do.

Other docs, so you do not duplicate them here: ARCHITECTURE.md (kernel design +
contributor rules), README.md (what the project is, for a newcomer), GUIDE.md
(how to use the tool), plan.md (the P0-P7 roadmap), list.md (the ranked work
list), agent/README.md (the pi package on its own terms).

**Two standards bind every change. Read ARCHITECTURE.md for both before you
build anything.**

- **Scope.** SimAgent serves one machine: a finite-dimensional configuration
  space, a scalar margin whose sign decides the claim, a picture of it, and
  exact arithmetic. A claim is admissible only if it passes all four parts of
  the admission test there. Geometry, algebraic inequalities, linear algebra,
  optimization and bounded integer claims are served today; discrete/extremal
  geometry, combinatorics and graph theory need a new Space; analysis,
  topology, abstract algebra, set theory, logic and cryptography are out
  permanently. Work aimed at an out-of-scope domain is rejected on scope.
- **Harness only.** Does this give the model something it cannot get by
  thinking? Capability, perception, verification and memory are ours; strategy,
  insight and the choice of proof method are the model's. An instrument reports
  its own limits but never names the next method to try.
- **Any model pi routes.** SimAgent harnesses whatever model pi selects; there
  is no blessed provider, and a coding model driving a run is normal. With no
  `--provider/--model` the runtime takes the first authenticated VISION model
  pi has, so the choice must never be silent: `KernelTransport.set_runtime`
  records provider/model as run PROVENANCE (`runtime.json` plus the
  `agent_summary.md` header), the CLI prints it, and an unrecorded model is
  said plainly rather than left blank. It is deliberately not a journal record
  — writing one would shift every sequence number and change what a branch
  prefix means. Any claim about agent behaviour must name the model, or it is
  not a claim about anything.

## Commands

```bash
.venv/bin/python -m pytest -q                 # Python suite (offline)
(cd agent && PI_OFFLINE=1 npm run build && PI_OFFLINE=1 npm test)  # pi suite
.venv/bin/simagent list                       # bundled problems
.venv/bin/simagent solve <id> [--trials N --seed S --render-manim]
.venv/bin/simagent solve --conjecture "..."   # needs Claude API auth
.venv/bin/simagent formalize "..." --out spec.json
.venv/bin/simagent play <id>                  # interactive REPL; preview.png re-renders per command
.venv/bin/simagent web                        # reasoning notebook on :8642 (problem in, visual reasoning cells out)
.venv/bin/simagent agent <id>                 # also accepts --spec FILE or --conjecture "..."
```

Always use `.venv/bin/...` explicitly — the shell PATH may resolve python to a
*different project's* venv (jacobian-conjecture). Install with
`uv pip install -p .venv/bin/python -e ".[dev]"`.

## Architecture map

Each module is described once, here. State it nowhere else.

**Kernel and proving**

- `proof.py` — THE proof kernel: ten classical methods, Proof record,
  `verified_by` ladder (sandbox+lean > sandbox > lean > none). Only this
  module assigns stamps. Mechanized methods: counterexample, construction,
  exhaustion; everything deductive is Lean-or-nothing. `sos_proof()` is the
  only route to PROVING a `forall` over a continuous domain (search can refute
  one but never establish one): it certifies the margin as a sum of squares,
  and being a DIRECT (deductive) method it returns None unless the Lean kernel
  accepts the certificate. It requires a STRICT certificate (margin >= eps >
  0); eps == 0 proves only margin >= 0, which does not settle a strict claim,
  so it is never upgraded. Two instruments reuse that same SOS-plus-Lean
  machinery: `cases_proof()` (the MODEL picks the split coordinate and value;
  the harness certifies both halves) and `induction_proof()` (unbounded over
  the naturals: base case positive, step case margin(n+1) - margin(n) a sum of
  squares). Every such proof still bottoms out in a kernel-accepted
  certificate, so all three are Lean-or-nothing.
- `lean_check.py` + `sandbox/leangen.py` — generated Lean 4 *core*
  certificates (`by decide`, rationals as integer pairs), checked with a bare
  `lean file.lean`. The toolchain IS installed (`~/.elan/bin/lean`, Lean
  4.32.1, via elan, no sudo, no Mathlib). The checker is fail-closed including
  `#print axioms` clean. Lean *skeletons* (conjecture.lean) stay UNCHECKED.
  leangen is capped at d<=3.
- `search.py` — random sampling + margin-guided annealing +
  rationalize-and-certify. **Margin convention: margin > 0 ⇔ property holds**;
  search minimizes it for `forall` (counterexamples), maximizes for `exists`.
- `sandbox/` — `geometry.py` (numeric toolbox: circumcenter, barycentric,
  hulls), `certify.py` (sympy exact mirror + rationalization), `scene.py`
  (renderer-agnostic scene-graph primitives), `sos.py` (exact rational
  sum-of-squares search: monomial basis, Gram matrix, symmetric elimination
  for the PSD split, plus `constraints` so a claim's own hypotheses join the
  identity as `p - eps = sigma_0 + sum sigma_k g_k`). Free Gram parameters are
  tried at zero first, then by alternating projection between the affine set
  and the PSD cone, then snapped back to rationals; every candidate is
  re-checked exactly, so the numeric step can only propose. The search is
  still INCOMPLETE and says so: a failure means "no certificate found", never
  "none exists".

**The eight atoms**

- `core/` holds seven pure atoms: space, entity, op, derive, measure, claim,
  journal. The eighth atom, view, lives in `views/`. The layer is pure and
  `tests/test_layering.py` enforces it.
- `core/space.py` is the one domain sampler; each Space declares its own
  dimension.
- `core/claim.py` owns the closed registries (MEASURES, CONSTRAINTS,
  CERTIFIERS, LEANS, SCENES) and `validate_claim()`, the gate for LLM output.
- `core/expr.py` is the GENERAL vocabulary: one safe arithmetic AST
  (whitelist, no exec/eval) drives three evaluators — float (search), exact
  sympy (certify), Lean Q-terms (stamp) — behind the `expr`
  measure/certifier/Lean hook. Any rational inequality over a box is therefore
  expressible with no new code and carries no d<=3 cap. Prefer `expr` over
  adding a problem-specific measure; validate_claim rejects a certifier or
  Lean hook whose margin is not the measure's margin verbatim.
- `core/derive.py` holds the geometry kit and CONSTRUCTORS. EVERY constructor
  must carry an `exact` counterpart, because `_exact_recipe_env` replays the
  recipe in rational arithmetic so a margin may read a derived entity and
  still certify. Lean takes only FREE variables as atoms, so the `recipe` Lean
  hook PINS each construction to its defining equations
  (`leangen.RECIPE_PINS`: circumcenter, orthocenter, barycentric, centroid,
  midpoint) and the kernel checks how the numbers were built. A constructor
  with no pin RAISES and the claim keeps its `sandbox` stamp, because a
  certificate over an unpinned derived value would check a bare number and
  prove nothing about its construction.
- `core/journal.py` is the mind trace. `trace.py` is a compatibility shim that
  re-exports it; new code imports `core.journal` directly.
- `views/` is the eighth atom plus the analytical output views: `identity`
  (scene graph as-is, d<=3), `field` (margin over a 2D slice; the zero-contour
  is the theorem's shape), `sweep` (margin along one coordinate, zero
  crossings marked), `trajectory` (margin vs journal step, the convergence
  plot), `ghost` (before/after overlay for imagination and diff replays).
  Registered scene builders render Space state; simplex scenes above d=3
  explicitly project to the first three coordinates and label the projection.

**Problems in, answers out**

- `library/` contains eleven bundled native Claims (zero exec'd code: a recipe
  plus registry keys): circumcenter in triangle / tetrahedron / 4-simplex,
  orthocenter in triangle, sum of squares vs linear, positive quadratic,
  conditional cubic, unbounded quadratic, sum of odds, Euler polyhedron, graph
  triangle threshold. Every bundled Claim is a known-answer test and `simagent
  bench` scores 11/11. The triangle Claim is the LLM few-shot example. Four
  carry a specific job:
  `sum-of-squares-vs-linear` (vocabulary) has margin (x-1)²+(y-1)²-1, so the
  field view's zero-contour is that unit circle, the algebraic echo of Thales;
  `orthocenter-in-triangle` (geometry kit) has a margin over a DERIVED entity,
  which certification reaches only by replaying the recipe exactly and Lean
  only by pinning each construction;
  `positive-quadratic` (proving) is the TRUE twin of `sum-of-squares-vs-linear`
  with one constant changed, proved outright by a Lean-checked sum-of-squares
  certificate rather than left as evidence; `circumcenter-in-4simplex` (ℝ⁴) is
  the dimension-agnostic test: certified counterexample, verified_by
  "sandbox", with the explicit no-Lean-above-d3 notice printed by answer.py.
- `spec.py` is the deprecated legacy compatibility path. It still compiles old
  exec-code disk specs; `ProblemSpec.load` routes native `claim/1` JSON to
  `core.claim`. Bundled and LLM-created problems use Claims.
- `llm.py` is the Claude formalizer (`messages.parse` structured output, model
  `claude-opus-4-8`, adaptive thinking) with a `validate_claim()` repair loop.
  Its closed-vocabulary prompt is generated from registry `doc` strings.
- `pipeline.py` orchestrates one full run (spec → search → certify → visualize
  → answer) into a self-describing directory: spec.json, report.json,
  preview.png, scene.json, scene_manim.py, answer.md, answer.tex,
  conjecture.lean, optional proof_sketch.md and media/.
- `answer.py` writes answer.md / answer.tex / conjecture.lean. Verdict wording
  is deliberate: certified vs numeric-candidate vs evidence. Never upgrade the
  claim.
- `cli.py` is the command surface listed above; `play.py` is the interactive
  sandbox that re-renders `preview.png` after every command.
- `visualize/` — `mpl.py` (always-on PNG), `manim_gen.py` (generates a
  self-contained ThreeDScene). Manim runs from a repo-local conda-forge env
  `.manim-env/` (micromamba, no sudo — pip manim is impossible here: no cairo
  headers); `_manim_python()` resolves SIMAGENT_MANIM_PYTHON → current
  interpreter → `.manim-env`. Degrade gracefully if absent.

**Agent mode and the web notebook**

- `agent.py` (`AgentRun`) owns kernel-side tool state: sandbox actions, trace,
  proof candidates, finalization. No provider, no model loop. `look` returns a
  vision image.
- `kernel_transport.py` is the provider-free, strict JSONL kernel boundary.
- `agent/` is the TypeScript pi runtime, with
  `@earendil-works/pi-coding-agent` and `@earendil-works/pi-ai` exact-pinned
  at 0.82.0. Pi owns provider auth, model turns, events, steering, and
  conversation sessions. Inside: `tools.ts` (the closed tool schemas, checked
  against Python), `kernel-client.ts` (spawns and talks to the Python kernel),
  `runtime.ts` (model turns), `controller.ts` (run lifecycle), `service.ts`
  (the HTTP control service), `cli.ts`, `index.ts`.
- `pi_agent.py` is the web app's thin Python client for that service. It
  transports commands only; no response from it can mint a verdict.
- Closed agent tools (20): plan, look, sample, set_var, nudge, check, measure,
  view, imagine, refine, hunt, exhaust, certify, sum_of_squares,
  prove_by_cases, prove_by_induction, submit_lean_proof, construct, expect,
  finish. TypeScript exposes no pi coding tools and no discovered resources.
- Every run writes `trace.jsonl` (thought, action, scene, equation, diff
  cells) and `kernel-journal.jsonl` (replayable calls and state hashes).
  Comments enter pi with `session.steer()` and are journaled as
  `user_comment`; the annotation must preserve the full kernel state hash.
  Branches copy a settled pi conversation prefix, replay the matching kernel
  journal prefix, verify the exact hash, and add provenance. Product turns
  accept one kernel action, which is what makes tool cells settled branch
  points.
- `web/` — notebook UI + kernel API. `session.py` (SandboxSession:
  server-authoritative state), `app.py` (FastAPI:
  load/set/sample/refine/hunt/certify + Manim jobs + trace endpoints
  `/api/runs`, `/api/trace/{run}`, per-step mpl renders + pi control routes
  for models/start/status/events/stop/comment/branch/stream), `static/`
  (index.html + app.js = the reasoning notebook: cells stream the mind trace;
  cell images click through to an interactive three.js overlay;
  three.module.min.js and OrbitControls.js are vendored — keep them). The
  frontend renders the same scene-graph JSON as Manim/mpl. UI convention: z is
  up. The notebook supports selecting a cell or line, or raycast-picking a 3D
  primitive, for comment or branch. Pi events stream at
  `/api/agent/{run}/stream`.

## Rules that must not regress

- Only `proof.py` stamps `verified_by`. Views, measures, journals, UI code,
  model prose, and user comments never mint a verdict.
- Fail closed. See `tests/test_hardening.py`: lean_check binds axiom-freedom
  to printed theorem NAMES and rejects sorry/admit/native_decide/'depends on
  axioms'; run_exhaustive certifies only via an exact certifier or an
  integer-exact domain, treats a raising check as incomplete, and rejects
  empty or inverted domains; mechanized_proof stamps statement_review
  'spec-generated-review-needed' unless `library.is_bundled(spec)`.
- The model picks the proof method; the harness only hands it instruments.
  Calling an instrument IS the declaration (hunt = counterexample, construct +
  certify = construction, exhaust = exhaustion, sum_of_squares = direct,
  prove_by_cases = cases, prove_by_induction = induction); the other four of
  the ten methods finish through submit_lean_proof. Never add a tool that
  decides the method for the model.
- Every instrument must explain its failures. `sos.find_sos`/`prove_positive`
  and `proof.sos_proof` take a `notes` list and append the REASON at each
  refusal (tight/equality case, Gram matrix not PSD, odd degree, wrong
  verdict), because a dead end with no reason is one the model cannot act on.
- New formalization vocabulary means a registry entry for a measure,
  constraint, constructor, certifier, Lean hook, or scene. Give it an accurate
  `doc` string, because `llm.py` generates the model's menu from those docs.
- Tests must stay offline: no API calls, no manim requirement.

## Roadmap

P7 multi-agent lanes, adopt, and merge remain unbuilt. The pi service permits
one active controlled run at a time.


# Claude Instructions
this instruction is the guideline development of this simAgent project


## Rule Priority

Follow system, developer, safety, and tool rules first. Then follow this file and the user's current request.

This project is built around the eight atoms described above.

## Communication

- Address the user as **Mr. President**.
- Use simple, natural English with a smooth flow.
- Use common words and short sentences.
- Keep answers short by default.
- If the user's message includes `//`, give a detailed explanation.
- End every answer with `Confidence: X/10`.
- Never use the em dash character. Use a comma, colon, parentheses, or a normal hyphen instead.
- Do not repeat, quote, or explain these instructions.
- Do not show private reasoning or internal checklists.

## Goal-First Rule

Every sentence, section, step, and line of code must directly help the user's real goal. Do not add something only because it is common, expected, or used in similar work.

Before acting, decide privately:

1. Who needs the result?
2. What exact outcome do they need?
3. What is the smallest result that gives them that outcome?
4. Which parts are truly needed, and what job does each part do?
5. What can be removed without hurting the outcome?

Start from nothing. Add only what the goal requires.

## Scope Control

- Include a section, step, or detail only when it has a clear purpose.
- Do not add background, summaries, options, warnings, or counterpoints unless the user will use them.
- Do not copy a standard structure unless it helps this exact reader and goal.
- Do not add plans, outlines, or other work products unless they help produce or check the final result.
- Do not add caveats for cases that do not apply.
- Prefer removing weak parts over adding more content.
- If a requested part does not help the goal, ask one short question about its purpose.
- If the user gives a clear purpose, include it.
- If no real purpose exists, do not add it.

Use these checks when scope starts to grow:

- Extra section or background: What decision will it support?
- More complete coverage: Complete for which exact need?
- Alternatives or both sides: Will the user act on them?
- Standard structure: Does it help the reader, or only follow habit?
- More professional wording: Which reader needs which signal?
- Final summary: Is it needed, or did the main answer fail to land?
- General use: What is the second real use case?

## Answer Format

Give the smallest direct answer that completes the goal. Do not describe what you removed, refused, or chose unless the user asks or the missing part blocks the work.

End with:

`Confidence: X/10`

## Coding Rules

### Before Coding

- State assumptions only when they affect the result.
- If two meanings would lead to different code, ask before editing.
- Point out a simpler approach when it meets the same goal.
- Define a clear success check before making changes.
- For a multi-step task, give a short plan with one check per step.

Examples:

1. Add validation. Check: invalid input fails in a test.
2. Fix a bug. Check: a test first shows the bug, then passes after the fix.
3. Refactor code. Check: the same tests pass before and after.

### Keep Code Small

- Write the least code needed for the current goal.
- Do not add features that were not requested.
- Do not create an abstraction unless at least two real callers need it now.
- Do not add settings for possible future users.
- Do not add a wrapper that only changes a name.
- Do not add a compatibility layer unless a current user needs it.
- Do not add defensive code for a state that cannot happen.
- If a much shorter solution works as well, use it.

### Make Small Changes

- Change only the files and lines required by the request.
- Match the project's current style.
- Do not clean up, rename, reformat, or refactor nearby code unless needed for the goal.
- Remove only unused code created by your own change.
- Mention unrelated problems, but do not edit them unless asked.
- Every changed line must trace back to the request.

### Challenge Unneeded Code

Ask for the real need before adding:

- A new layer, manager, service, adapter, or interface without a second real use.
- Future-proof, plug-in, or general code without a current caller.
- A library wrapper based only on a possible future swap.
- Backward support without a named version, client, or user.
- Edge-case tests for inputs that cannot reach the code.
- A general refactor without a second real use case.

If the user names a real need, implement the smallest form that meets it. If not, do not add the code.

### Verify

- Run the smallest useful test first.
- Continue until the success check passes.
- Report the result, changed files, and any real blocker.
- For code changes, show a short before-and-after description.
- Do not claim success without checking it.

## Code Answer Format

Keep the final reply short:

1. What now works.
2. What changed.
3. How it was checked.
4. Any real blocker.
5. `Confidence: X/10`

Omit any item that has nothing useful to say.

## Change reporting (required, every time)

EVERY change is reported as a comparison table. Not prose, not a summary of
what was done: what was true before, what is true now, and what that buys the
goal. One row per thing that actually changed.

| what | before | after | impact on the goal |
|---|---|---|---|
| <the thing> | <what was true> | <what is true now> | <which pillar it serves, and how> |

Rules:

- The **impact** column names a pillar, not a feature. Pillar 1 is the harness
  giving a model what it cannot get by thinking; pillar 2 is human and agent
  unblocking each other. A change that serves neither needs a reason to exist.
- **Before** must be the real prior state, including when it was "nothing" or
  "silently wrong". Do not describe the old behaviour more kindly than it was.
- A row per change, even the small ones. A fix that came out of a bug found
  along the way is its own row, because that is usually the row that matters.
- Say plainly when a change buys nothing yet and is groundwork.
- The table comes BEFORE the prose, so the reader can stop after it.
