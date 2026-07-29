# SimAgent architecture

SimAgent is an **agent harness for experience-based math**: a small kernel
with a strict responsibility split, where correctness beats features. A model
solves math by ACTING in a world that answers every move with exact numbers —
place, nudge, refine, read the margin — and only then formalizes (equations
are the *translation* of thought, never the medium). See plan.md for the full
v2 design and decision log.

core idea of sim agent is this :
1. simagent is the harness that gives a routed llm the best way to solve a
   math problem by EXPERIENCING it rather than reading a text file, from first
   principles. NUMBERS-FIRST (decided 2026-07-27, todo.md step 0): the model's
   senses are text and coordinates — exact margins, exact positions, `measure`
   words — because current models read numbers exactly and pixels coarsely.
   Pictures come from the same kernel state but their audience is the HUMAN;
   sending them to the model is a per-run flag, default off.
2. as a tool human and ai agent collaborate on solving: sometimes the human is
   stuck and the agent helps, sometimes the human gives the idea while the
   agent is stuck. this happens in a seamless ui where the human comments on,
   pauses at, and directly moves the exact step the agent took.

**Measured, not assumed** (2026-07-28, `runs/eval-live/eval.json`): on
`circumcenter-near-centroid`, automatic search certified 0 of 3 seeds while a
model acting in the world certified 3 of 3, median 9 turns. Images did not
separate from text (3 of 3, median 11 turns), which is why numbers-first is
the default and the image channel is a flag rather than a deletion.


## The eight atoms

Everything in the domain — harnessing an LLM to do math through visualization
— composes from eight primitives (`src/simagent/core/`). Dimension-aware code
exists ONLY at the two boundaries: Space (input) and View (output); everything
between is dimension-blind.

| primitive | physical analogy | role |
|---|---|---|
| **Space** | configuration space | input boundary: `sample / valid / perturb / exact / enumerate_cases`. `Box(ℝᵈ)`, `IntBox(ℤᵈ)`, `GraphSpace` (adjacency matrix, moves flip edges) — the discrete one exists because a graph is an object the box types cannot state at all |
| **Entity** | particle | named, stable id; *free* (value in a Space) or *derived* (recipe over entities — coordinates are consequences, the CAD lesson) |
| **Op** | force | THE only mutation channel (Blender lesson) = the agent's action vocabulary; a closed registry replaces exec'd code |
| **Derive** | physical law | dependency graph; derived entities recompute when ancestors move |
| **Measure** | observable | perception as calibrated compression: margins + qualitative predicates, each measure kind describing its own state through the registry's `qualitative` entry |
| **Claim** | hypothesis under test | quantifier + free Spaces + recipe + a distinguished measure, all from closed registries |
| **Journal** | worldline / lab notebook | dynamics first-class: state = replay(journal) = save format = undo = notebook feed; `imagine` branches = thought experiments; annotations = plan/expect/user_comment |
| **View** | detector | output boundary: identity (d≤3), **field** (margin painted over a config-space slice, fixed diverging colormap centered at 0, zero-contour = the theorem's shape — the Ansys lesson), sweep, ghost, trajectory |

Derivations (features as compositions): sample = Op(Space.sample) · refine =
loop{perturb → Measure → keep} · hunt = sampleⁿ + refine · exhaust =
Space.enumerate_cases × Measure · certify = Space.exact + exact Measure · construct
= Op(add derived) + Derive · diff = Journal[n] − Journal[n−1] · imagine = Ops
on a World fork, journaled `mode:"imagine"`, never merged · expect = journal
annotation scored mechanically on later commits · undo/branch = journal
prefix replay + fork.

## The responsibility split

```
LLM / human   — reasons, conjectures, chooses proof methods, writes Lean
harness      — executes, enumerates, certifies, kernel-checks; keeps state
Lean kernel  — the only authority on deductive truth
```

The harness **never evaluates prose**. An argument becomes a proof only when
machinery checks it. UIs (web, terminal REPL, CLI) are thin shells over the
kernel; they can display state but cannot mint verdicts.

## The three pillars

| pillar | role | trust |
|---|---|---|
| **Python** | computation: sandbox, search, exact rationals (sympy) | trusted for *mechanized* methods only |
| **Lean 4** | formulation + deductive verification (`decide`, core-only certificates) | the kernel is the root of trust |
| **Manim** | visualization: the presentation renderer over the shared scene graph | no trust role — pictures explain, never prove |

## Scope: which mathematics this harness serves

SimAgent is not a general mathematics tool and was never built as one. Strip
away the words and it is one machine: **a finite-dimensional configuration
space, a scalar margin whose sign decides the claim, a picture of that space,
and exact arithmetic to settle it.** That machine decides the scope, and the
scope is fixed. This section is the standard; do not re-open it per feature.

### The admission test

A claim, a domain, or a proposed capability is in scope only if **all four**
hold. Apply the test before writing code, not after.

| # | Test | Fails when |
|---|---|---|
| 1 | **Finite configuration.** The free variables form a finite-dimensional Space that can be sampled and enumerated. | Stating the claim needs a function, a limit, or an infinite family. |
| 2 | **Scalar margin.** One real number whose sign decides the property (`margin > 0 ⇔ holds`). | The property cannot be reduced to a single sign. |
| 3 | **Renderable state.** The configuration can be drawn, or honestly projected with the projection labelled. | There is nothing to look at, so the visual thesis gives no advantage over a text-only tool. |
| 4 | **Exactly checkable.** The margin evaluates in exact rational (or algebraic) arithmetic at a rational point. | It needs transcendental values or floating point only, so no verdict can rise above evidence. |

Failing test 1 **only** because the object needs a Space that does not exist
yet (a graph, a permutation, a polytope, a lattice) is an in-scope extension:
build the Space. Failing test 2, 3 or 4 is permanent; no Space fixes it.

### What that admits, and what it does not

| status | domains |
|---|---|
| **Served today** | Geometry (points in ℝᵈ) · algebraic inequalities · linear algebra · optimization · bounded integer claims |
| **In scope, Space not built yet** | Discrete and extremal geometry · combinatorics · graph theory |
| **Out permanently** | Calculus, real and complex analysis · topology · abstract algebra · set theory · logic · cryptography · number theory beyond bounded claims |

None of the seven Millennium problems is admissible, and no amount of building
changes that: they live in analysis, topology, number theory and logic, which
are infinite in exactly the way this machine is finite. Recording that here so
nobody spends a session rediscovering it.

### What the scope is aimed at

One explicit finite object that settles a real question. Euler's sum of powers
conjecture stood ~200 years and fell to a single line of numbers; Borsuk's
stood 60 and fell to one finite point set; the Hirsch conjecture stood 53 and
fell to one polytope. That is this machine's shape, and discrete and extremal
geometry is where such questions are still open.

**"Settles" cuts both ways, and the aim is not refutation.** A sum-of-squares
certificate is an explicit finite object too: a short list of squares in exact
rationals that a reader checks by hand in ten seconds, with no Lean and no trust
in this code. `positive-quadratic` is settled that way, in the positive
direction, by the same kind of object. Those three famous counterexamples are
cited because they show the SIZE of what one finite object can decide, not
because disproof is the goal. Both directions now answer a move with a number,
which is what lets a model work its way toward either: see "Refuting and proving
are one motion with unequal instruments" under the proof kernel.

Olympiad inequalities are the benchmark that earns credibility, not the
destination.

## The harness answers nothing

**SimAgent is only a harness. It does not answer the question. Every answer
comes from the model pi routes.** This is the first standard, not the fourth,
and everything else here is downstream of it.

The split is not "the harness is dumb". The harness is allowed to be powerful,
and it is: it samples, anneals, enumerates every case of a finite domain,
rationalizes a witness, certifies in exact arithmetic, generates a Lean
certificate and draws the configuration. All of that is EXECUTION. None of it
is reasoning, and the difference is what this section fixes.

| the harness owes | the model owes |
|---|---|
| capability (act on the world), perception (see it), verification (settle it mechanically), memory (replay it) | which claim to attack, which configuration to try, which of the ten methods, what the picture means, what to conclude |

The rules that follow, each of which has bitten or nearly bitten:

1. **No mathematical thinking lives in this repository.** No hardcoded answers,
   no hints in a tool description, no "the trick is to flatten it" in a spec's
   notes. A bundled claim documents its ground truth because it is a
   known-answer TEST of the machine, not a worked solution for the model.
2. **An instrument reports its own limits, and never the next move.** "No
   certificate found; the Gram matrix was short of positive semidefinite by
   -0.0033" is information the model needs. "Try induction instead" is the
   model's decision, taken from it. Both `sos.find_sos` and `proof.sos_proof`
   append reasons to `notes` and a distance to `progress` for exactly this
   reason: a measurement is a fact, a recommendation is the model's job.
3. **A mechanical check is not an answer to the question.** `run_search`
   finding a counterexample is the harness executing, and the WITNESS is a
   fact. That the conjecture was worth attacking that way, and what it means,
   is the model's.
4. **Prose never becomes a verdict**, whoever wrote it: the model's narrative,
   the user's comment, a contributor's docstring. Only `proof.py` stamps, and
   `explain.py` may restate that stamp but never raise it.
5. **Whoever edits this repository is bound by the same rule.** A human or a
   coding agent working on SimAgent builds instruments; it does not solve the
   user's mathematics inside the harness. If a problem needs insight, that is
   the routed model's job, and shipping the insight as code is how a harness
   quietly turns into an answer key.

Pinned by `test_harness_never_picks_the_method_for_the_model` and
`test_no_surface_the_model_reads_tells_it_what_to_do`.

## Which model runs it: any model pi routes

SimAgent harnesses whatever model pi selects. There is no blessed provider and
no blessed model, and a coding model driving a run is normal rather than a
compromise: the harness is the subject of the work, so the model is a variable
in it. Docs that name one model do so as an EXAMPLE, never as a requirement.

That freedom has one cost, and the harness pays it by recording. With no
`--provider/--model` the numbers-first runtime takes the first authenticated
model pi has. An image-channel run takes the first authenticated vision model.
That is convenient and silent, and silent is the problem: a transcript
with no model attached cannot be compared with anything. So the choice is run
PROVENANCE. `KernelTransport.set_runtime` records provider, model and thinking
level; `AgentRun.finalize` writes `runtime.json` and puts the same line at the
top of `agent_summary.md`; `simagent agent` prints it when the run ends. When
nothing was reported the summary says so in words ("not recorded") instead of
leaving a blank, because a blank reads as "unknown model" and "no model" alike.

It is deliberately **not** a journal record. The journal's sequence numbers are
what a branch prefix means, so inserting a provenance entry would renumber
every step and change which state a branch replays. Provenance is about the run;
the journal is about the world.

The rule that follows: any claim about agent behaviour must name the model, or
it is not a claim about anything.

## Every output explains itself (`explain.py`)

A stamp is a word and a witness is a list of fractions. Neither tells a reader
what happened, and asking them to reconstruct it is asking them to do the
harness's job: perception is calibrated compression, and a number without its
meaning is only shortened, not compressed.

So a result and every state in a progression carry an explanation in plain
English, and it is a STANDARD, not a nicety. `explain.py` writes them, and the
same module serves `answer.md` and the notebook, because two wordings of one
verdict would be two claims.

- **A result** gets fact rows (what was found, what verified it, the witness in
  exact fractions, each derived value, the margin) and one closing sentence
  that says whether this is an answer or only evidence.
- **A state** gets one line: which variables moved, what the margin did, and
  whether this is the state that crossed zero.

Both are built from kernel state only: `proof.json`, the search report, and the
check the sandbox recorded per step. `explain.py` reads no model prose and
decides nothing. It restates the stamp `proof.py` assigned and **cannot raise
it**: an explanation of a `verified_by: none` result says, in words, that
nothing checked it. `test_the_result_and_every_state_explain_themselves` pins
that.

## The proof kernel (`proof.py`)

Every answer names one of the ten classical proof methods and carries a
`verified_by` stamp that **only `proof.py` assigns**:

| method | who can verify it here | how |
|---|---|---|
| counterexample | harness (+ Lean) | exact-rational violation of a ∀; Lean pair-arithmetic certificate |
| construction | harness (+ Lean) | exact-rational witness of an ∃; same certificate machinery |
| exhaustion | harness (+ Lean) | every case of a finite integer domain checked; Lean `decide` over the bounded statement |
| direct | Lean only | `sos_proof()`: the margin certified as a sum of squares in exact rationals, then kernel-checked. This is the ONLY route to proving a `∀` over a continuous domain — search can refute one but never establish one |
| induction | Lean only | `induction_proof()`: base case positive and `margin(n+1) - margin(n)` a sum of squares, so an UNBOUNDED claim over ℕ is settled |
| cases | Lean only | `cases_proof()`: the model picks the split coordinate and value, the harness certifies both halves by the same SOS machinery |
| contradiction | Lean only | no instrument; the model writes the Lean |
| contrapositive | Lean only | no instrument; the model writes the Lean |
| combinatorial | Lean only | no instrument; the model writes the Lean |
| infinite descent | Lean only | no instrument; the model writes the Lean |

`verified_by` values, strongest first:

- `sandbox+lean` — harness check AND a generated certificate accepted by the
  Lean kernel with **no axioms** (`#print axioms` must come back clean).
- `sandbox` — complete mechanical check by the harness (exact rationals or
  full enumeration). Sound, but not independently checked.
- `lean` — a Lean proof (usually LLM-written) the kernel accepted; the
  *statement's* faithfulness to the conjecture still needs human review
  (`statement_review` field).
- `none` — an argument on record. Not a proof. The harness says so.

Sampling evidence ("no counterexample in N trials") is **never** a proof and
`mechanized_proof` returns `None` for it, deliberately.

### Refuting and proving are one motion with unequal instruments

For a `∀` claim the deciding quantity is the **minimum** of the margin over the
domain: negative means a counterexample exists, positive means the claim holds.
So `search.py` walking downhill is not a refutation move. It is the move that
looks for that minimum, and it serves both answers. What search actually
returns is the smallest margin it has SEEN, which settles the claim when that
value is negative and settles nothing when it is positive. Closing the gap
between the seen minimum and the true minimum is exactly the job of a
certificate.

The mathematics is symmetric, and each direction now answers with a quantity:

| direction | what the model can act with | what comes back |
|---|---|---|
| toward a counterexample | sample, set_var, nudge, refine, hunt, exhaust, construct | a margin number after every single move, so the next move is informed by the last |
| toward a proof | sum_of_squares, prove_by_cases, prove_by_induction, submit_lean_proof | accepted or refused, the reason in words, and `progress.gap`: how far the closest candidate Gram matrix stood from positive semidefinite |

**The proving side's margin is `gap`** (`sos._psd_gap`): the most negative
eigenvalue of the nearest Gram matrix the search actually built, and exactly
`0.0` once the EXACT rational split accepts one. A far-off claim reads about
-1, a claim that misses by a hair reads -3e-05, so a second attempt can be
compared with the first instead of starting from the same place. It is measured
on every candidate and on every rung of the strictness ladder, and the nearest
of them is what the refusal reports.

Three properties keep it honest, all enforced in `tests/test_sos.py`:

1. **Ordered.** Nearer to a certificate means nearer to zero, or the number
   would be noise the model cannot walk.
2. **Never a verdict.** A gap of -1e-5 is still a refusal. `(x-1)² + (y-1)² -
   1/10000` is FALSE and reads -3.3e-05, so a harness that treated small as
   settled would stamp a false claim proved. Only `proof.py` stamps, and only
   from the exact check.
3. **Numeric only where it may be.** The eigenvalue is floating point because
   it is perception. The decision stays exact rational arithmetic plus Lean.

`progress` travels as an out-parameter dict through `find_sos` →
`prove_positive` → `sos_proof` / `cases_proof` / `induction_proof` → the tool
result the model reads. For `prove_by_cases` it also names WHICH half fell
short, which makes the cut value itself walkable: a different `at` moves the
number.

This closed the last known instrument gap. It adds no proving power: what the
harness could certify before, it certifies now, and nothing more. What changed
is that a refused attempt is a position rather than a wall.

## Lean certificates (`sandbox/leangen.py`, `lean_check.py`)

Certificates target **Lean 4 core only** — no Mathlib, no Batteries, no lake.
Checking is one `lean file.lean` process; proofs are `by decide`, i.e. pure
kernel computation, which is why the axiom check can demand "does not depend
on any axioms".

Rationals are encoded as integer pairs `(p, q)` with `q > 0` asserted for
every atom; `qadd/qsub/qmul` multiply denominators so positivity is closed
under the operations, and cross-multiplied `qeq/qlt` then coincide with `=`/`<`
on ℚ. That two-line closure argument is the entire trusted modeling step —
everything else is kernel-checked arithmetic on explicit numerals.

The checker is **fail-closed**. Every source rejects proof holes and Lean
commands that can execute I/O before Lean starts. Closed generators then run
from a temporary working directory. Model-written Lean has a stronger rule: it
runs only inside working Linux bubblewrap isolation, with no network, no home
or checkout mounted, and only a temporary directory writable. If that sandbox
is missing or blocked, the attempt stays `verified_by: none` and says why.

Acceptance still requires a clean exit, at least one named `#print axioms
<thm>`, an axiom-free line for every named theorem, and no `depends on axioms`
line anywhere. Binding axiom-freedom to theorem names stops a source from
echoing the clean phrase to spoof the check.

**Trust vs. faithfulness.** A `sandbox+lean` stamp means the Lean kernel
accepted the certificate. For a bundled spec that certificate is reviewed, so
`statement_review = bundled-trusted`. For any other spec (disk-loaded, LLM-
authored) the Lean *statement itself* is spec-controlled, so the proof is
stamped `spec-generated-review-needed`: the arithmetic is kernel-checked, but a
human must confirm the Lean theorem actually states the conjecture. Trust is
by object identity with the bundled registry (`library.is_bundled`), never by
id string.

**Exhaustion soundness.** `run_exhaustive` fails closed: a found
counterexample/witness is `certified` only via an exact certifier or the
domain's integer-exactness (all inputs `|x| ≤ 2^40`, keeping float64 integer
arithmetic exact below `2^53`); a case whose `check` raises makes the whole
`∀`/`∃` verdict *incomplete* (not a proof); empty/inverted (`low > high`)
domains are rejected; case counting uses Python ints (no `np.prod` overflow).

## Data flow

The shape is below; **[docs/data-flow.md](docs/data-flow.md) walks the same two
paths naming the FORMAT on every boundary**, with a real value from a real run
at each one.

A batch run (`simagent solve`):

```
conjecture ──(llm.formalize, sandbox-validated)──▶ Claim (recipe + registry keys, no exec'd code)
Claim ──▶ search: run_exhaustive (finite int domains: EVERY case)
                        run_search    (continuous: sample + anneal + certify)
report ──▶ proof.mechanized_proof ──▶ Proof {method, claim, verified_by}
                    │                        │
                    └── leangen certificate ─┴─▶ lean_check (kernel, axiom-free)
Proof + report ──▶ answer.md / answer.tex / conjecture.lean / proof.json
scene graph ──▶ matplotlib preview │ Manim still/video │ three.js live view
```

An agent run reaches that same kernel through four processes. The last hop
lands back in PYTHON, which is the trust argument in one line: the model is in
the middle of the chain, never at the end of it.

```
browser
  │ HTTP: a problem id, or free text that llm.py formalizes into a Claim first
  ▼
web/app.py ──JSONL──▶ pi_agent.py ──JSONL──▶ agent/dist/service.js
                                                │ model chosen ONCE at start;
                                                │ one model turn = one tool call
                                                ▼
                                          kernel-client.ts ──spawn (one kernel per run)
                                                │ JSONL
                                                ▼
                                     kernel_transport.py ──▶ AgentRun
                                                │
  Ops mutate the world · derive recomputes · the measure returns the margin
                                                │
  ├──▶ tool result to the model (text always; tool PNGs only when images are on)
  ├──▶ kernel-journal.jsonl (call + state hash) and trace.jsonl (the cell)
  └──▶ finish: mechanized_proof stamps verified_by ──▶ proof.json + answer.md ──▶ verdict cell
```

The notebook server and the run's kernel are DIFFERENT Python processes. The
server renders and transports; it holds no world state, so no browser action
can reach a verdict except by going the whole way round.

**One state, four representations.** The same configuration is rewritten at
each stage, and each rewrite buys one specific thing: float (numpy) buys speed
for search and can only ever PROPOSE; exact rational (sympy) buys a verdict
independent of floating point; Lean integer pairs buy a verdict independent of
this codebase; the scene graph buys perception, and feeds mpl, Manim and
three.js from one source so the human views one kernel state. When images are
on, tool pictures from that same state also reach the model.
`equation_of_state` adds a fifth, for reading only: symbols follow the world,
never the reverse.

## Agent mode (pi control plane)

The TypeScript package under `agent/` owns provider authentication, model
turns, event streaming, steering, and pi conversation sessions. It starts one
private Python `kernel_transport.py` process per run. The Python process owns
`AgentRun`, `SandboxSession`, exact checks, Lean checks, trace output, and
finalization. Pi transports messages but cannot stamp a verdict.

Product runs expose only the closed SimAgent tools and disable pi's coding
tools and resource discovery. Tool execution is sequential. One kernel action
is accepted per model turn, so each tool cell ends at a settled pi checkpoint.
A branch copies the pi conversation prefix, replays the matching Python
journal prefix, and rejects unless the state hash agrees exactly.

There are two correlated records:

1. The pi session stores conversation, thinking, tool bracketing, steering,
   and the branch tree.
2. `kernel-journal.jsonl` and `trace.jsonl` store the reproducible world,
   pictures, equations, diffs, annotations, and proof candidates.

A targeted comment is written to the trace as `user_comment` and delivered
through `session.steer()` after the current tool batch. The annotation
operation asserts that the complete kernel state hash is unchanged. Branches
add a provenance annotation containing source run, step, journal sequence,
and hash. Neither annotation kind is verdict material.

The human may also move the world during a run, because a comment can only
suggest and a stuck run often needs someone to place the point. That is a real
state change, so it is not an annotation: `userAction` runs one of
sample/set_var/nudge/construct through the same dispatch as a tool call and
journals a `user_action` event with its own state hash, replayable like any
other. Every trace step carries an `actor`, and the model is told at the same
boundary that the move was not its own. The truth-making instruments
(certify, hunt, exhaust, the proof tools) stay the model's alone: what counts
as established is never the human's to assert either.

The reasoning notebook polls the kernel trace and can also consume pi events
through the `/api/agent/<run>/stream` websocket. A user can select a cell,
thought, action, or equation line, or raycast-pick a 3D primitive, then comment
or branch from that state. The verdict cell still reads only `proof.json` and
`answer.md`.

A FINISHED run can also be continued from the page: `POST /api/agent/start`
takes `{"adopt": RUN}`, which becomes `--adopt` on the kernel spawn. Two things
make that safe to expose to a browser. The client sends a run NAME, resolved by
`run_dir()` inside the runs root, so it cannot name a directory the server did
not offer; and the claim is rebuilt from that run's own `spec.json`, so naming a
problem beside it is refused rather than replaying a journal into a world some
other claim describes. `/api/runs` reports `continuable` per run, because a
control offered where it cannot work is worse than one not offered.

## Files

```
src/simagent/
  core/          SEVEN OF THE EIGHT ATOMS (View is the 8th, in views/; pure:
                 stdlib+numpy+sympy+sandbox leaves only, enforced by
                 tests/test_layering.py):
                   space.py entity.py op.py derive.py measure.py claim.py
                   journal.py
                 plus expr.py — the GENERAL vocabulary: one whitelisted
                 arithmetic AST, three evaluators (float / exact sympy / Lean
                 Q-term). Any rational inequality over a box is expressible
                 with no new code, so prefer it over a new one-off measure
  views/         the output boundary: identity, field, sweep, ghost, trajectory
                 (one calibrated visual language: diverging colormap centered
                 at margin 0 — blue HOLDS / red FAILS, zero-contour marked)
  search.py      sampled search + annealing (Space.perturb) + exact certify;
                 exhaustive enumeration (Space.enumerate_cases) — fail-closed
  proof.py       the proof kernel (methods, Proof, verified_by) — sole verdict authority
  lean_check.py  run generated Lean core; isolate model-written source;
                 fail-closed acceptance
  sandbox/       geometry.py (numeric, d-generic simplex math + hull_facets),
                 certify.py (sympy exact, any-ndim rationalization),
                 scene.py (scene graph), leangen.py (Lean certs; d<=3 cap
                 stated explicitly — the LU-witness encoding is the extension;
                 RECIPE_PINS ties 14 of 19 constructors to their defining
                 equations, UNPINNABLE says why the other five cannot be),
                 sos.py (exact rational sum-of-squares search: the engine
                 behind every DIRECT proof; incomplete, and every refusal
                 appends its reason to `notes`)
  answer.py      Markdown / LaTeX / Lean skeleton emitters; states the d>3
                 no-Lean cap explicitly in every verdict it touches
  explain.py     kernel state → plain English, for answer.md and the notebook;
                 restates a stamp, never raises one
  intake.py      the problem CONTRACT: the user's exact words, the claim hash,
                 and the approval gate a natural-language run must pass
  pipeline.py    one run = claim → search → proof → viz → answers → report.json
  rounds.py      the stopping rules for --rounds, in one place because the CLI
                 loop and the evaluation arms both apply them
  evaluate.py    does ACTING in the world help? one manifest, arms on the same
                 tasks and budget, mechanical outcomes only, threshold declared
                 before the run
  benchmark.py   `simagent bench`: every bundled Claim run end to end, scored
                 on verdict AND strength — the one number a change is judged by
  llm.py         formalize (native Claim synthesis from the closed vocabulary,
                 sandbox-vetted) and attempt_proof (Lean-checked, never trusted)
  library/       bundled native Claims — zero exec'd code; known-answer tests
                 incl. circumcenter-in-4simplex (the dimension-agnostic gate)
  visualize/     mpl.py (always-on PNG), manim_gen.py (generated ThreeDScene)
  agent.py       kernel-side tool state over one SandboxSession; no provider loop
  kernel_transport.py  strict JSONL kernel bridge: tools, human world moves,
                 annotations, stop, hash-verified prefix replay, toolCallId
                 correlation
  pi_agent.py    thin client for the TypeScript pi control service
  cli.py         the command surface: list, bench, eval, solve, play, agent,
                 web, formalize
  play.py, web/  shells: terminal REPL and the reasoning-notebook UI over the
                 same kernel (trace replay/live-follow via /api/runs,
                 /api/trace; agent sessions via /api/agent/start)
agent/           TypeScript pi runtime and session service (exact-pinned)
```

## Rules for contributors (human or LLM)

1. Only `proof.py` sets `verified_by`. Never fake a stamp in a shell or spec.
2. New capability = new *mechanized check* or new *Lean certificate shape*,
   not a new claim the harness can't check. Fail closed.
3. Every bundled spec is a known-answer test: its ground truth is documented
   and the test suite asserts the machine reaches it.
4. Certificates must stay core-Lean and `decide`-based unless a stronger,
   equally-checkable scheme replaces them repo-wide.
5. Shells (CLI/REPL/web) may render state; they must not compute verdicts.
6. Every change must serve a domain the scope section admits. Run the
   four-part admission test first. A feature aimed at an out-of-scope domain is
   rejected on scope, however good it is; the answer is not "later", it is no.
7. The harness never does the model's thinking. Ask: *does this give the model
   something it cannot get by thinking?* Capability, perception, verification
   and memory are the harness's job. Strategy, insight and the choice of proof
   method are the model's. An instrument may report its own limits (that is
   information); it may not say which method to reach for next (that is
   steering). Pinned by `test_harness_never_picks_the_method_for_the_model`.
8. Every change lands with a test that fails without it, and CI must stay
   green. `.github/workflows/ci.yml` runs the Python suite twice (with Lean and
   with `SIMAGENT_LEAN=off`, because the toolchain is optional and the degraded
   path is the one most users get), `simagent bench` at 11/11, and the pi suite
   offline. A UI change is not done until the PAGE is checked: CI fails when no
   browser is present rather than letting the browser test skip.
