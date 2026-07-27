# The notebook and agent mode

So far you have driven the sandbox yourself. This page is about the other half
of the project: letting a language model live in that sandbox, watching it work,
and stepping in when it gets stuck.

## The collaboration idea

A coding agent shows its work as diffs. A math agent should show its work as
pictures. That is what the notebook is for.

The intent is two way. Sometimes the human is stuck and the agent finds the
move. Sometimes the agent is stuck and the human sees it from the outside. The
notebook makes both possible by letting you comment on any single step the agent
took, or branch the run from exactly that state.

## Start the notebook

```bash
.venv/bin/simagent web
```

Your browser opens `http://localhost:8642`. If it does not, type that address
in. If the port is busy, use `--port 8700`. The address is local only and the
notebook has **no user authentication**, so do not expose it publicly.

The pi runtime must be built first, and authenticated once:

```bash
(cd agent && npm ci --ignore-scripts && npm run build)
(cd agent && npx pi)     # inside pi: /login, authenticate, then quit
```

`npx pi` opens the exact pi version this project pins. You log in there and
nowhere else. Do not type your math problem into the pi terminal and expect the
notebook to notice it. The browser starts and controls the session.

Check a provider and model without printing credentials:

```bash
node agent/dist/cli.js auth-check --provider openai-codex --model gpt-5.6-sol
```

## Run an agent

1. Pick a **pi model** in the header dropdown.
2. Pick a **thinking** level. Higher is slower and uses more account quota.
3. Set **max turns**. Forty is a reasonable start.
4. In the `In [ ]:` cell, choose a bundled problem, or type a conjecture in plain
   words. Free text is formalized first, which needs
   one model pi has authenticated. Without any authenticated model,
   use a bundled problem.
5. Press **Run agent**.

Cells then stream in, one per recorded reasoning step.

## What a cell shows

| Part | Meaning |
|---|---|
| **approach** (amber box) | The agent's declared line of attack: one of the ten proof methods plus its idea. Re-declared when it changes strategy. This is *intent*, and the final verdict shows declared against established |
| **thinking** and **says** | The model's narrative before it acted |
| **act** | The tool it chose: `look()`, `set_var(...)`, `hunt(...)`, `certify()` |
| **the picture** | For `look` steps, the exact image the agent saw. Otherwise the scene after the act. Click it to open an interactive 3D view: drag to orbit, scroll to zoom, Esc to close |
| **equations** | The harness's symbolic translation of that state |
| **diff** | Which points moved, as `- before` and `+ after`, plus the margin change |
| **badge** | HOLDS or FAILS, with the margin |

The final **verdict cell** is built only from kernel artifacts, `proof.json` and
`answer.md`. The model's prose never upgrades a claim, and neither do your
comments.

## Steering a run

Select text, or double click a cell, thought, action, or equation line. In the 3D
overlay, click a point or a primitive. Then either:

- **comment**, which is delivered to the model as a steering turn before its next
  move, or
- **branch with comment**, which rewinds and continues from that exact state.

Branching is exact, not approximate. It copies the settled pi conversation
prefix, replays the matching kernel journal prefix, verifies the state hash
agrees, and records the source run, step, journal sequence, and hash as
provenance. If the hash disagrees, the branch is refused.

Controls: **stop** ends the session while keeping the kernel results established
so far. **restart** stops it and re-runs the same problem in a fresh notebook.

## The agent's tool set

The model gets no shell, no file access, no web, and none of pi's coding tools.
It gets these twenty, and nothing else.

| Group | Tools | What they give the model |
|---|---|---|
| Intent | `plan`, `expect`, `finish` | Declare a method and idea, make a falsifiable prediction the harness scores mechanically, end the run |
| Perception | `look`, `check`, `measure`, `view` | See the scene as an image, get the full check, get a qualitative description, paint the margin as a `field`, `sweep`, or `trajectory` |
| Action | `sample`, `set_var`, `nudge`, `construct` | Draw a new configuration, place a point exactly, move a point by a delta, add a derived entity such as a midpoint or circumcenter |
| Imagination | `imagine` | Run ops on a *fork* of the world and look at the result. The real configuration is untouched and the branch is never merged |
| Search | `refine`, `hunt`, `exhaust` | Anneal from here, search from scratch, enumerate every case of a finite domain |
| Proof | `certify`, `sum_of_squares`, `prove_by_cases`, `prove_by_induction`, `submit_lean_proof` | Turn the current state into an exact verdict, or attempt a deductive route |

Calling an instrument **is** the declaration of method. `hunt` is a
counterexample attempt, `construct` plus `certify` is a construction, `exhaust`
is exhaustion, `sum_of_squares` is a direct proof, `prove_by_cases` is cases,
`prove_by_induction` is induction, and the remaining four methods
(contradiction, contrapositive, combinatorial, infinite descent) finish through
`submit_lean_proof`. No tool tells the model which method to reach for, and
adding one that did would break a rule the test suite pins.

The three deductive instruments are Lean or nothing. `prove_by_cases` splits one
coordinate at a value the *model* chooses and certifies both halves.
`prove_by_induction` proves an unbounded claim over the naturals: the base case
is positive and the step increase is a sum of squares. Both reuse the same sum of
squares and Lean machinery as `sum_of_squares`, so each still ends in a
kernel-accepted certificate or in nothing.

Two of these deserve a note for a newcomer.

**`imagine`** is the thought experiment. It runs on a fork, appears in the
notebook as a dashed `Im[n]` cell with a ghost image, and cannot change the real
world. It is how the model asks "what if" without paying for it.

**`expect`** is a prediction, drawn as a small chip. The harness scores it
against later states and marks it passed or failed. Prediction error is how the
model learns the scene, and it is mechanical, so the model cannot grade itself.

## From the command line

```bash
.venv/bin/simagent agent circumcenter-in-triangle

.venv/bin/simagent agent circumcenter-in-triangle \
  --provider openai-codex \
  --model gpt-5.6-sol \
  --thinking max \
  --max-turns 40 \
  --out "runs/agent-triangle-$(date +%Y%m%d-%H%M%S)"
```

It also accepts `--spec FILE` or `--conjecture "..."`.

The provider and model in the second command are only an example, and the two
flags go together or not at all. The first command gives neither, so pi routes
the first authenticated vision model it has, prints that it is doing so, and
prints `Model: <provider>/<model>` when the run ends. SimAgent has no blessed
model; it harnesses whichever one pi routes.

A CLI run is viewable in the browser, since the header dropdown lists every
recorded run and follows a live one. It cannot be steered there, because a
different controller owns it. Start runs from the browser when you want
comments, stopping, or branching.

## What a run leaves behind

On top of the normal run files, an agent run writes these:

| File | What it holds |
|---|---|
| `trace.jsonl` | The mind trace: thought, action, scene, equation, and diff cells. This is what the notebook replays |
| `kernel-journal.jsonl` | The replayable world: every kernel call and state hash. This is what a branch verifies against. Written by pi-driven runs, so very old recorded runs may not have one |
| `agent_summary.md` | The model's own summary of the session, with the model that produced it named in the header |
| `runtime.json` | Which model pi routed: provider, model, thinking level. Read this before comparing two runs, because "the agent stalled here" is a statement about one model |
| `transcript.jsonl` | The raw conversation |
| `looks/` | Every image the agent actually saw |

The first two are the correlated pair that matters.

The pi session stores the conversation, the thinking, the steering, and the
branch tree. The two journals store the reproducible world. Keeping them
separate is what makes the trust rule survive: a comment enters pi as a user
turn and is journaled as `user_comment`, and the annotation must leave the
kernel state hash unchanged. Narrative and proof state cannot touch.

## Where your problem actually goes

Pressing **Run agent** starts a chain of four processes. It is worth seeing
once, because the shape of the chain is the reason a model cannot fake a result.

1. The **browser** posts the problem to the notebook server.
2. The **notebook server**, Python and FastAPI, formalizes free text with a pi-routed model
   if you typed a sentence, then hands the claim to the pi service through a
   thin client.
3. The **pi service**, TypeScript, picks the model once, opens a session whose
   only tools are SimAgent's twenty, and runs the model turns.
4. For every tool the model calls, the service passes the call to a **private
   Python kernel** started for that run. The kernel changes the world, computes
   the margin, and sends the result back, with a real image for `look`.

The chain ends in Python, not in the model. The model sits in the middle: it
chooses what to try next, and the process at the far end decides what actually
happened. The notebook server and the run's kernel are also two separate Python
processes, so nothing you do in the browser reaches the world directly.

## Who owns what

| Side | Owns |
|---|---|
| **pi (TypeScript, `agent/`)** | Provider authentication, model turns, event streaming, steering, conversation sessions and branches |
| **Python kernel** | The mutable world, search, exact certification, Lean checking, journal replay, finalization |

The service starts one private Python kernel process per session and talks to it
over strict JSONL. Pi transports messages. It cannot stamp a verdict. A certified
counterexample a model picked by hand produces exactly the same `proof.json` and
Lean certificate as one found by a batch run.

Next: [glossary](05-glossary.md).
