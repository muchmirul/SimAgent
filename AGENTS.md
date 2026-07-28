# SimAgent — notes for the agent
THIS PROJECT IS ONLY HARNESS, thinking or any thought must come from the model itself, which must not be provided here

AGENTS.md and CLAUDE.md are the same file, kept byte-identical on purpose so
every tool reads one source of truth. Edit one, copy it to the other.

Pi-managed harness for experience-based, finite-dimensional math: a small
correctness-first kernel. The LLM reasons; the harness records only what it can
execute or check; the Lean kernel is the sole authority on deduction. Read
ARCHITECTURE.md before touching the kernel. Current baseline: v2 P0-P6 landed.

core idea of sim agent is this :
1. simagent is the harness that gives a routed llm the best way to solve a
   math problem by EXPERIENCING it, not by reading a text file: the model acts
   in a world (sample, nudge, refine) and the world answers back, from first
   principles. NUMBERS-FIRST (decided 2026-07-27, todo.md step 0): the model's
   senses are text and coordinates — exact margins, exact positions, `measure`
   words — because current models read numbers exactly and pixels coarsely.
   Equation is just formalization. Pictures are rendered from the same kernel
   state, but their audience is the HUMAN; sending them to the model is a
   per-run flag, default off, kept so evaluation can judge the image channel
   with evidence instead of belief.
2. as a tool human and ai agent collaborate on solving: sometimes the human is
   stuck and the agent helps, sometimes the human gives the idea while the
   agent is stuck. this happens in a seamless ui where the human comments on
   the exact step the agent took — and the notebook's pictures exist for this,
   the human's window into the run.

Other docs, so you do not duplicate them here: ARCHITECTURE.md (kernel design +
contributor rules), README.md (what the project is, for a newcomer),
docs/onboarding/ (six pages for someone who has never seen the project; start
there before this file), GUIDE.md (how to use the tool), plan.md (the P0-P7
roadmap), list.md (the ranked work list), agent/README.md (the pi package on
its own terms).

**Four standards bind every change. Read ARCHITECTURE.md for all four before
you build anything** ("The harness answers nothing", "Scope: which mathematics
this harness serves", "Which model runs it: any model pi routes", and "Every
output explains itself"). The first one governs the rest.

- **The harness answers nothing.** SimAgent is only a harness, and every
  answer comes from the model pi routes. The harness may be powerful — it
  samples, anneals, enumerates, certifies, generates Lean and draws — because
  all of that is EXECUTION. It owes capability, perception, verification and
  memory; the model owes which claim to attack, which configuration to try,
  which of the ten methods, what the picture means and what to conclude. So: no
  mathematical thinking lives in this repository, no hints in tool
  descriptions, no worked solutions in spec notes; an instrument reports its
  own limits but never the next move; prose is never a verdict whoever wrote
  it. This binds whoever edits the repo too, human or coding agent: build
  instruments, do not solve the user's mathematics inside the harness, because
  shipping insight as code is how a harness turns into an answer key.
- **Scope.** SimAgent serves one machine: a finite-dimensional configuration
  space, a scalar margin whose sign decides the claim, a picture of it, and
  exact arithmetic. A claim is admissible only if it passes all four parts of
  the admission test there. Geometry, algebraic inequalities, linear algebra,
  optimization and bounded integer claims are served today; discrete/extremal
  geometry, combinatorics and graph theory need a new Space; analysis,
  topology, abstract algebra, set theory, logic and cryptography are out
  permanently. Work aimed at an out-of-scope domain is rejected on scope.
- **Every output explains itself.** A stamp is a word and a witness is a list
  of fractions; neither tells a reader what happened. Every result and every
  state in a progression carries plain English saying what was found, what
  checked it, and whether it is an answer or only evidence. `explain.py` writes
  them for both `answer.md` and the notebook, from kernel state only, and it
  RESTATES the stamp rather than raising it: explaining a `verified_by: none`
  result says in words that nothing checked it.
- **Any model pi routes.** SimAgent harnesses whatever model pi selects; there
  is no blessed provider, and a coding model driving a run is normal. With no
  `--provider/--model` the runtime takes the first authenticated model pi has
  (a text-only model is a normal driver, since the senses are numbers; vision
  is required only for an `--images` run), so the choice must never be silent:
  `KernelTransport.set_runtime`
  records provider/model as run PROVENANCE (`runtime.json` plus the
  `agent_summary.md` header), the CLI prints it, and an unrecorded model is
  said plainly rather than left blank. It is deliberately not a journal record
  — writing one would shift every sequence number and change what a branch
  prefix means. Any claim about agent behaviour must name the model, or it is
  not a claim about anything.

## Commands

```bash
.venv/bin/python -m pytest -q                 # Python suite (offline)
SIMAGENT_LEAN=off .venv/bin/python -m pytest -q   # the no-toolchain path users have
(cd agent && PI_OFFLINE=1 npm run build && PI_OFFLINE=1 npm test)  # pi suite
.venv/bin/simagent bench                      # known-answer test, must stay 11/11
.venv/bin/simagent eval --arms search         # does the LOOP help? offline floor arm
.venv/bin/simagent eval --arms search text images --provider P --model M  # spends API calls
.venv/bin/simagent list                       # bundled problems
.venv/bin/simagent solve <id> [--trials N --seed S --render-manim]
.venv/bin/simagent solve --conjecture "..."   # needs one authenticated pi model
.venv/bin/simagent formalize "..." --out spec.json
.venv/bin/simagent play <id>                  # interactive REPL; preview.png re-renders per command
.venv/bin/simagent web                        # reasoning notebook on :8642 (problem in, visual reasoning cells out)
.venv/bin/simagent agent <id> [--images]      # also accepts --spec FILE or --conjecture "..."
.venv/bin/simagent agent <id> --adopt runs/PRIOR   # continue a run that ran out of turns
.venv/bin/simagent agent <id> --rounds 3      # each round adopts the last; stops on a kernel stamp
```

`.github/workflows/ci.yml` runs those four on every push and pull request, in
three jobs: the suite with no Lean at all (the machine a new user actually
has), the suite plus `bench` with Lean 4.32.1 installed by elan, and the pi
runtime built and tested offline. That third job still needs Python: the
kernel-backed pi tests spawn `<repo>/.venv/bin/python -m
simagent.kernel_transport` as a real subprocess, because the boundary is what
they are testing. CI fails when no browser is present rather
than letting `tests/test_ui_browser.py` skip, because a silent skip is how
three UI bugs shipped green.

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
  4.32.1, via elan, no sudo, no Mathlib). The checker rejects Lean commands
  that can execute I/O, requires `#print axioms` clean, and runs model-written
  source only inside bubblewrap with no network or writable host tree. If that
  isolation cannot start, the attempt stays unverified. Lean *skeletons*
  (conjecture.lean) stay UNCHECKED. leangen is capped at d<=3.
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
  CERTIFIERS, LEANS, SCENES), the only `claim/1` loader, and
  `validate_claim()`, the hard gate for every input path. IDs are safe slugs
  because they become run-directory names. Legacy executable specs are
  refused, not compiled.
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
- `core/journal.py` is the mind trace and its only import path.
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
- `llm.py` is the formalizer. It asks whatever model pi routes, through the
   same control service agent runs use (`structured` op → `_ask`), so the
   front door is not pinned to one vendor while the main hall is open to any.
   No default model id: with none given pi hands over its first authenticated
   model, and `--provider/--model` picks one. The answer shape is forced by a
   single tool whose parameters ARE the schema, and a `validate_claim()`
   repair loop quotes each failure back. Its closed-vocabulary prompt is
   generated from registry `doc` strings. It answers in exactly one of two
   ways: a supported Claim, or a typed refusal (`FormalizeRefused`, never
   retried). Substituting a NEARBY claim is forbidden, because the kernel would
   then settle a different question under the user's words.
- `evaluate.py` answers a question `bench` cannot: does ACTING in the world
  help a model settle a claim? One `eval/1` manifest, three arms on the same
  tasks, seeds and budget (`search` = no model, the floor; `text` = the
  numbers-first loop; `images` = the same loop with pictures), and only
  mechanical outcomes scored (certified solve rate, `verified_by`, turns, tool
  errors, human interventions, and how each run ENDED — an arm whose runs all
  die on the turn budget is saying the budget binds, not that the harness
  failed). Those counts are read from each run's own `metrics.json` rather than
  recounted here. The required improvement is declared IN the
  manifest before anything runs, a seed whose first sample already settles the
  claim is screened out and the skip is recorded, and `format_report` states
  the gap without ever naming a winner. `separation()` also reports tasks the
  floor already solves, because a task search settles says nothing about the
  loop. Arms differ by ONE flag: same task, seed, budget and model, and the
  `--seed` reaches `SandboxSession` so two seeds are two different starting
  worlds rather than the same run twice. A manifest `budget.rounds` above 1
  makes each model arm a LOOP of adopted runs on the same rules `rounds.py`
  gives the CLI, and the report prints the rounds spent, because an arm that
  needed three rounds to reach another's rate bought it with model calls.
  Default 1, so every result recorded before this still means what it says.
  FIRST LIVE RESULT (2026-07-28, `runs/eval-live/eval.json`,
  openai-codex/gpt-5.6-sol, 3 seeds on `circumcenter-near-centroid`): search
  0/3 certified, text 3/3 (median 9 turns), images 3/3 (median 11). Both beat
  the +0.25 declared before the run. Images did not separate from text, which
  is why numbers-first is the default and the image channel is a flag.
- `intake.py` is the problem CONTRACT. It hashes the executable Claim,
  restates every part of it in plain English (`describe_claim`: quantifier,
  domain, assumptions, filter, margin meaning, verification limits), and
  records the user's exact words with the formalizer's provider/model in
  `intake.json`. Natural-language input starts `pending`: no agent runs until a
  human approves that exact hash (`simagent agent --approve-claim HASH`, or the
  notebook's 428 plus its approval cell). Re-formalizing changes the hash and
  voids an old approval on its own. This review confirms the TRANSLATION only;
  it never touches `verified_by`, and `answer.md` prints both the source text
  and the review state. The web keeps the shown claim in a small bounded cache
  keyed by its hash: formalizing is a model call and is NOT deterministic, so
  re-formalizing on the approval request would produce a different claim, the
  hash would never match, and the gate would be unpassable. A formalizer that
  breaks (rather than refuses) answers 502 naming the model and the fix; the
  model you pick in the notebook formalizes too, because the default is
  whichever model pi lists first and small models often cannot make the
  structured tool call at all.
- `pipeline.py` orchestrates one full run (spec → search → certify → visualize
  → answer) into a self-describing directory: spec.json, report.json,
  preview.png, scene.json, scene_manim.py, answer.md, answer.tex,
  conjecture.lean, optional proof_sketch.md and media/.
- `core/measure.py` is perception as compression, and each measure kind
   describes its OWN state through a `qualitative` entry in the MEASURES
   registry (min_coord speaks about faces of a simplex, expr about the terms
   of its margin). A measure with no describer would leave the model only the
   margin number it already had.
- `explain.py` turns kernel state into plain English: `result_rows()` and
  `result_summary()` for the end of a run, `step_line()` for one state of a
  progression, `handoff_markdown()` for what one run leaves the next. Reads
  Proof/SearchReport objects or the JSON they were saved as, so `answer.md` and
  the notebook say the same thing. The handoff is built from
  `AgentRun.journal_digest()`, the same builder `recall` uses, so the run's
  memory and its handoff cannot drift into two accounts of one journal. Never
  mints or upgrades a verdict: a run that established nothing says in words
  that the claim is exactly as open as it was before.
- `answer.py` writes answer.md / answer.tex / conjecture.lean. Verdict wording
  is deliberate: certified vs numeric-candidate vs evidence. Never upgrade the
  claim.
- `cli.py` is the command surface listed above; `play.py` is the interactive
  sandbox that re-renders `preview.png` after every command. `agent --rounds N`
  is the LOOP: round k runs into `<out>/round-k` and adopts round k-1, so a
  turn budget becomes a pause rather than the end of the work. `--rounds 0` is
  refused rather than rounded up to one, since rounding up spends a model run
  the caller asked not to have. `loop.json` records every round and why the
  loop stopped. Rounds get slower as they go: adopting replays every earlier
  act for real, which is the price of the exact hash-checked reproduction that
  makes it trustworthy.
- `rounds.py` holds the loop's stopping rules, once, because two callers apply
  them: `simagent agent --rounds N` and the evaluation arms that measure
  whether rounds help. Two copies would drift, and the eval would then be
  scoring a loop nobody runs. All three rules are mechanical and none reads the
  model's opinion of being done: a `verified_by` other than `none` in that
  round's `metrics.json`, a round that recorded no act of its own (the next one
  would only replay the same history at the same price), or the round budget
  the caller declared. Everything fails toward "nothing established": no
  metrics file, an unreadable one, or a non-zero exit credits no stamp, and
  metrics are ignored entirely when the runtime exited non-zero, because the
  file may be a previous invocation's.
- `visualize/` — `mpl.py` (always-on PNG), `manim_gen.py` (generates a
  self-contained ThreeDScene). Manim runs from a repo-local conda-forge env
  `.manim-env/` (micromamba, no sudo — pip manim is impossible here: no cairo
  headers); `_manim_python()` resolves SIMAGENT_MANIM_PYTHON → current
  interpreter → `.manim-env`. Degrade gracefully if absent.

**Agent mode and the web notebook**

- `agent.py` (`AgentRun`) owns kernel-side tool state: sandbox actions, trace,
  proof candidates, finalization. No provider, no model loop. `AgentRun(...,
  images=False)` is the numbers-first switch: `look`/`view`/`imagine` always
  WRITE their render (the notebook and trace need it) and attach it to the
  model's content only when `images` is on, so `system_prompt(images)` must
  describe the senses that run actually has.
- `kernel_transport.py` is the provider-free, strict JSONL kernel boundary. It
  also owns ADOPT (`--adopt RUN_DIR`, journal version 4): a later run replays a
  finished run's whole journal, hash-checked like any branch, and then writes an
  `adopt` event that re-opens the world. The re-opening is the point — replay
  alone restores the ENDING too, so the next model would be refused at its first
  act with "session already finished". The boundary is a journalled, replayable
  event rather than quiet setup, because it changes kernel state; the earlier
  ending is kept in the record and cleared from the state, so no run can finish
  under a summary it never wrote. The header records the SEED, because the seed
  is the starting world and cannot be recovered from the state: adopting takes
  the earlier run's seed rather than asking a caller who has a directory to
  remember a number. Version 3 journals still replay (nothing about the hashed
  state changed) and one started from a non-default seed fails saying exactly
  that. `_adoption_note` tells the model where the inherited steps end and how
  the earlier run stopped, since a model told nothing would read those steps as
  its own; it says what was ESTABLISHED is still held by the kernel, because
  the deductive proof state is part of the replayed state and claiming
  otherwise would be false.
- `agent/` is the TypeScript pi runtime, with
  `@earendil-works/pi-coding-agent` and `@earendil-works/pi-ai` exact-pinned
  at 0.82.0. Pi owns provider auth, model turns, events, steering, and
  conversation sessions. Inside: `tools.ts` (the closed tool schemas, checked
  against Python), `kernel-client.ts` (spawns and talks to the Python kernel),
  `runtime.ts` (model turns), `controller.ts` (run lifecycle), `service.ts`
  (the HTTP control service), `cli.ts`, `index.ts`.
- `pi_agent.py` is the web app's thin Python client for that service. It
  transports commands only; no response from it can mint a verdict.
- Closed agent tools (21): plan, look, sample, set_var, nudge, check, measure,
  view, imagine, refine, hunt, exhaust, certify, sum_of_squares,
  prove_by_cases, prove_by_induction, submit_lean_proof, construct, expect,
  recall, finish. TypeScript exposes no pi coding tools and no discovered
  resources. `recall` is the memory the harness owes: compaction is off (it
  would break branch hashes), so without it a long run's own journal is
  unreachable by the model that wrote it. It RESTATES journalled state via
  `explain.result_rows` and can neither stamp nor advise.
- Every model-facing result goes through `agent._fit`, which drops whole
  fields and NAMES them rather than slicing JSON mid-value: a cut reply that
  cannot say it was cut reads as a complete one. `_status` carries the free
  coordinates, because without them the model can read the margin but not
  where its own points are, and every deliberate move becomes a guess read off
  a PNG.
- Every run writes `trace.jsonl` (thought, action, scene, equation, diff
  cells) and `kernel-journal.jsonl` (replayable calls and state hashes), plus,
  at EVERY ending, `handoff.md` (what this run leaves the next one) and
  `metrics.json` (its own mechanical counts). Both matter most in the ending
  that used to write nothing: `finish` is the only ending that produces a
  summary, so a run killed by its turn budget left an empty narrative and a
  journal nobody could read. `AgentRun.ending()` names which of the three
  endings happened, `refusals()` lists every instrument that ran and
  established nothing WITH the instrument's own reason, and `evaluate.py` reads
  `metrics.json` instead of recounting the journal, because two counters over
  one journal are two numbers that can disagree. Metrics count THIS run's own
  acts: an adopted run replays the earlier run's acts into its own journal, so
  counting them all would credit a round with work nobody did in it, and the
  loop's no-progress rule reads exactly that number. `Journal.flush_pending()`
  runs before the count so a closing narrative is not one row the journal has
  and the metrics do not.
  Comments enter pi with `session.steer()` and are journaled as
  `user_comment`; the annotation must preserve the full kernel state hash.
  `pause()`/`resume()` hold the model at its NEXT tool call, which is a settled
  boundary: the previous action is journaled and the next has not begun. A tool
  parked at that gate leaves the active batch, or a human move would wait for
  the model that is waiting for the human. A picked 3D point carries its
  variable and row (`scene.points(binds=...)`), so the human's move, nudge and
  construct go through the same journaled user-action boundary as the model's.
  A human may also MOVE the world mid-run (`userAction` op → journal event
  `user_action`, tools limited to sample/set_var/nudge/construct): a comment
  can only suggest, and a stuck run often needs someone to place the point.
  It changes state, so it is a replayable hash-checked event rather than an
  annotation, every trace step carries an `actor`, and the model is told in
  the same boundary so it never mistakes the move for its own.
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
  The same reason must survive the run: `AgentRun.refusals()` carries it into
  `handoff.md`, or the next run pays for the same dead end again.
- Continuing a run must never invent state. Adopt replays and hash-checks; it
  does not restore a snapshot. A stopping rule for a loop must be mechanical (a
  kernel stamp, or a budget declared before the run), never the model's own
  sense that it is finished, and a missing artifact must read as "nothing was
  established" rather than as a stamp.
- New formalization vocabulary means a registry entry for a measure,
  constraint, constructor, certifier, Lean hook, or scene. Give it an accurate
  `doc` string, because `llm.py` generates the model's menu from those docs.
- Tests must stay offline: no API calls, no manim requirement.
- A UI change is not done until the PAGE is checked, not the API. Three
  separate bugs shipped green because endpoints returned 200 while the page
  was broken: a cell built and never appended to its parent, a server bound
  to an address the browser did not resolve to, and pictures drawn in the
  old style. `tests/test_ui_browser.py` loads the real page in headless
  Chromium and asserts on the rendered DOM; it skips when no browser is
  present. Run it, and take a screenshot, before calling UI work finished.

## Roadmap

Adopt landed (2026-07-28): `--adopt` continues a finished run, `--rounds` loops
it until a kernel stamp or a declared budget stops it, and every run now leaves
`handoff.md` plus `metrics.json`. P7 multi-agent lanes and merge remain
unbuilt, and the notebook cannot yet start an adopted run: adopt is CLI-only
until the UI change is built and checked in a real browser. The pi service
permits one active controlled run at a time.


# Claude Instructions
this instruction is the guideline development of this simAgent project


## Rule Priority

Follow system, developer, safety, and tool rules first. Then follow this file and the user's current request.

This project is built around the eight atoms described above.

## Communication

- Address the user as **Mr. President**.
- **Always write in simple English, in an explanatory tone.** Both, always,
  not only when asked.
  - Simple English: common words, short sentences, one idea per sentence. If
    a plain word will do, the technical one is wrong. When a technical term is
    unavoidable, say what it means the first time in the same breath.
  - Explanatory tone: never state a fact and stop. Say what it means or why it
    matters, in the same short space. "X is false" is a fact; "X is false, so
    the model gets a dead end it cannot act on" explains. The reader should
    finish knowing WHY, not just WHAT.
  - The two work together, they do not fight. Explaining is not padding: it is
    one short clause carrying the reason. Cut adjectives, keep reasons.
  - Prefer a small concrete example over an abstract description. One real
    number, file, or line beats a paragraph of characterization.
- Keep answers short by default. Short and explanatory at once: fewer claims,
  each carrying its reason.
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

if im typing "-discuss" always answer with explaning using purely english in simple explanatory paragraph with step by step progression
if im typing "-ss" always answer with explaning using purely english in simple explanatory short sentences with step by step progression