# SimAgent - simple guide

This guide assumes you know what SimAgent is and want to operate it. If you do
not, read [docs/onboarding/](docs/onboarding/) first: it starts from zero and
explains the ideas this page only uses.

## 1. How pi fits into SimAgent

Pi is embedded inside SimAgent as the model runtime. The normal `pi` terminal
is used only to log in. Do not type the math problem there and expect the web
notebook to start. Start SimAgent's web server, then enter the problem in the
browser. The browser launches and controls the pi session.

First-time setup requires `uv` and Node.js 22.19 or newer:

```bash
cd /mnt/Tforce/dev/SimAgent
uv venv .venv
uv pip install -p .venv/bin/python -e ".[dev]"
(cd agent && npm ci --ignore-scripts && npm run build)
(cd agent && npx pi)
```

The last command opens the exact pi version pinned by SimAgent. Inside pi,
enter `/login`, authenticate whichever provider you have, then quit pi. Any
provider pi supports will do: SimAgent has no blessed model, and it harnesses
whatever pi routes. The one real requirement is **vision**, because the agent
works by looking at the scene, so the notebook only offers models that accept
images.

Check that a provider and model are usable, without printing credentials
(substitute your own, this is only an example):

```bash
node agent/dist/cli.js auth-check \
  --provider openai-codex \
  --model gpt-5.6-sol
```

Start the notebook for each working session:

```bash
./start.sh          # or: .venv/bin/simagent web
```

`start.sh` is the one-command version. It kills any server still running from
an earlier session, rebuilds the pi runtime if `agent/src` changed, warns when
pi has no authenticated provider, and opens the browser with the thinking level
and turn limit filled in.

It does **not** pick the problem, because which problem to work on is your
choice: the dropdown stays on "choose a bundled problem" and waits for you.
Preset it only if you want to, with `PROBLEM=circumcenter-in-triangle
./start.sh`. The same goes for `THINKING`, `TURNS`, `PORT`, and
`MODEL=provider/model` to pin a model instead of letting pi route one.

Your browser opens the **reasoning notebook** at **http://localhost:8642**.
If it does not open, enter that address manually. If the port is busy, use
`.venv/bin/simagent web --port 8700`. The default address is local-only; do
not expose the notebook publicly because it has no user authentication.

## 2. The idea

A coding agent shows its work as diffs. SimAgent shows a math agent's work as
a **visual reasoning trace**: the agent lives in a sandbox, and the notebook
streams its recorded narrative and actions step by step. Equations appear in
every cell as translations of the executable scene. The scene is the working
state, and the symbols are its record.

The sandbox is not limited to 3D: claims live in any dimension (there is a
bundled ℝ⁴ problem). For d ≤ 3 the pictures are faithful; above that they are
honest projections and the numbers lead. Above d = 3 no Lean certificate is
generated yet: the verdict tops out at exact rational arithmetic, and the
answer says so explicitly.

The agent's senses and hands, beyond looking and moving points:

- **measure**: the qualitative description ("outside, beyond the face
  opposite vertex 2, margin −0.41")
- **view field**: the claim's margin painted over a slice of configuration
  space: blue where it HOLDS, red where it FAILS, the amber **zero-contour is
  the shape of the theorem's boundary** (for the triangle claim it is
  literally the Thales circle)
- **view sweep / trajectory**: margin along one coordinate / over the session
- **imagine**: an Einstein thought experiment, ops run on a *fork* of the
  world, shown as a dashed **Im[n]** cell with a ghost image; the real
  configuration is untouched
- **construct**: the sketching hand, add a midpoint / centroid / circumcenter
  to the scene; it renders from then on and follows its ancestors
- **expect**: a falsifiable prediction (◌ chip) that the harness scores
  mechanically against later states (✓/✗ chips). Prediction error is how the
  agent learns the scene

## 3. Run an agent on a bundled problem

1. Under **pi model**, pick any model in the dropdown. It lists only the
   vision-capable models pi has authenticated for you, so anything there works.
   Whichever you pick is written into the run's `runtime.json`, because a
   transcript without a model name cannot be compared with another run.
2. Under **thinking**, select **max**. Maximum thinking is slower and can use
   more account quota.
3. Set **max turns**. Start with 40.
4. In the **In [ ]:** cell, pick a problem, such as *Circumcenter lies inside
   every tetrahedron*.
5. Press **Run agent**. **■ stop** ends the running session while preserving
   kernel results established so far. **⟳ restart** stops it and runs the same
   problem in a fresh notebook.
6. Cells stream in, one per recorded reasoning step:
   - **approach** (amber box): the agent's declared line of attack, one of
     the ten proof methods plus its idea, re-declared when it switches
     strategy. This is intent; the end verdict shows *declared vs established*.
   - **thinking** (dim italic) and **says**: the model's narrative before the act
   - **act**: the tool it chose, `look()`, `set_var(…)`, `hunt(…)`, `certify()` …
   - the **picture**: for `look` steps, the exact image the agent saw;
     otherwise the scene after the act. **Click any picture** to open it as an
     interactive 3D view (drag to orbit, scroll to zoom, Esc to close).
   - the **equations** the harness wrote down for that state (amber box)
   - a **diff**: which points moved (`- before` / `+ after`) and the margin change
   - a **HOLDS / FAILS** badge with the margin (margin > 0 ⇔ the property holds)
7. When the run ends, a final **Out [all]** cell always appears. It draws
   every state the run reached in **one** picture: pale for early, deep for
   late. A run that never moved the configuration still gets the cell, saying
   so plainly, because "nothing moved" is information: it means the answer came
   from proving rather than from searching. A single cell
   answers "what did it do"; only this one answers "where was it going". Click
   it for the interactive version, which lists each state with a switch, so you
   can isolate any one of them or compare two. Colour means time there, never
   holds or fails: the margin printed beside each state carries that.
8. To steer the run, select text or double-click a cell, thought, action, or
   equation line. In 3D, click a point or primitive. Send a comment for the
   next pi turn, or choose **branch with comment** to rewind and continue from
   that exact state. Comments are visible narrative, never proof material.
9. The final **verdict cell** comes only from the kernel (`proof.json`):
   *method: verified by sandbox+lean* means exact arithmetic plus a Lean
   kernel certificate. If nothing was certified, it says so. The agent's
   prose never upgrades a claim.

Whichever model you picked, its environment is different from a general coding
session: it receives only SimAgent's closed geometry and proof tools, no coding
tools and no file access. Python remains the authority for state changes and
verdicts, so the model's choice changes how well the run goes, never what the
run is allowed to claim.

## 4. Run your own problem

Drop a `claim/1` spec file in `problems/` and it appears in the dropdown,
marked `(from problems/)`. Refresh the page and pick it like any other problem.
`problems/README.md` explains the fields, and `problems/three-xy.json` is a
working example to copy.

That path needs no formalizer model, because you wrote the claim yourself instead
of asking a model to write it. The stamp differs though: a file here is not
bundled, so a Lean-checked result says `statement_review =
spec-generated-review-needed`. The arithmetic is kernel checked either way, but
for your own file a human still has to confirm the Lean theorem says what you
meant.

## 5. Type your own problem in plain words

Type the problem in the SimAgent browser text box, not in the normal pi
terminal. For example:

> the incenter of every triangle lies inside the triangle

Then press **Run agent**. There are two model stages, and they can be
different models on purpose:

1. A model formalizes the sentence into a native claim, which is then
   validated against the closed sandbox registries.
2. Pi launches the model you selected, at the thinking level you selected, to
   investigate that claim.

Both stages go through pi, so neither is tied to a particular vendor. Stage 1
needs no vision, because it reads words and writes JSON; stage 2 does, because
it looks at the scene. With no `--provider/--model` each stage takes pi's
first suitable authenticated model. If nothing is authenticated, use a bundled
problem: those are already formalized, so stage 1 is skipped entirely.

## 6. Replay past runs

The header dropdown lists every recorded run, including web-started and
CLI-started runs. Pick one to read the notebook; if its trace is still being
written, the page follows it live. Deep-link with `?run=<name>`.

Start runs from the browser when you need live comments, stopping, restarting,
or exact branches. Keep that web-server process running while using these
controls. Restarting the server preserves traces for replay, but it does not
restore control of an old pi session. A separately launched CLI session can be
viewed in the browser, but it is owned by a different controller and cannot be
steered there.

## 7. Without the browser

```bash
.venv/bin/simagent list                              # see the problems
.venv/bin/simagent solve circumcenter-in-tetrahedron # full automatic run
.venv/bin/simagent play circumcenter-in-triangle     # hands-on REPL sandbox

.venv/bin/simagent agent circumcenter-in-triangle \
  --provider openai-codex \
  --model gpt-5.6-sol \
  --thinking max \
  --out "runs/agent-triangle-$(date +%Y%m%d-%H%M%S)"
```

The provider and model above are an example, and the two flags go together or
not at all. Leave both out and pi routes the first authenticated vision model
it has; the command says so before it starts, and prints `Model:
<provider>/<model>` when it ends, so you never have to guess afterwards which
model produced the run.

The normal pi terminal does not open the SimAgent browser automatically. Use
`simagent web` for the full live notebook and steering workflow.

`solve` writes a folder under `runs/` with the picture, `answer.md`,
`answer.tex`, `conjecture.lean`, and `report.json`. `agent` additionally
writes `trace.jsonl`, the reasoning trace the notebook replays. Manim stills and
videos render via `simagent solve --render-manim` (see README for the no-sudo
Manim env).

## 8. Reading the verdicts honestly

- **CERTIFIED counterexample**: proved false. Done.
- **numeric candidate**: looks false, but exact check did not confirm. Not proof.
- **no counterexample found**: evidence it may be true. **Never** a proof;
  proving still needs math/Lean (that's the roadmap).

One more thing to read, in every agent run: **which model produced it**. The
header of `agent_summary.md`, and the whole of `runtime.json`, name the
provider, the model and the thinking level. If the run could not report them,
that line says "not recorded" in words rather than going blank. This matters
because "the agent got stuck here" is a statement about one model, so without
the name it is not a statement about anything, and two runs cannot be compared.
It never touches the verdict: `proof.json` is the same whichever model ran.
