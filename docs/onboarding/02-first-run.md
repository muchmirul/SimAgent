# Your first run

Everything on this page runs offline. No API key, no account, no network.

## 1. Install

You need Python 3.11 or newer. The project uses [uv](https://docs.astral.sh/uv/)
to build the virtual environment.

```bash
cd /path/to/SimAgent
uv venv .venv
uv pip install -p .venv/bin/python -e ".[dev]"
```

**Always call the tool as `.venv/bin/simagent`, not bare `simagent`.** Your shell
PATH may resolve to a different project's environment. The same goes for
`.venv/bin/python`. This is the single most common way a first session goes
wrong here.

Check the install:

```bash
.venv/bin/simagent list
```

You should see eleven bundled problems:

```
circumcenter-in-triangle          [forall]  Circumcenter lies inside every triangle
circumcenter-in-tetrahedron       [forall]  Circumcenter lies inside every tetrahedron
circumcenter-in-4simplex          [forall]  Circumcenter lies inside every 4-simplex (R^4)
orthocenter-in-triangle           [forall]  Orthocenter lies inside every triangle
euler-characteristic-hull         [forall]  Euler characteristic of convex polyhedra (V - E + F = 2)
sum-of-odds-square                [forall]  Sum of the first n odd numbers equals n^2 (n <= 200)
sum-of-squares-vs-linear          [forall]  x^2 + y^2 + 1 exceeds 2(x + y) for all real x, y
positive-quadratic                [forall]  x^2 + y^2 + 1 exceeds x + y for all real x, y
conditional-cubic                 [forall]  x^3 + 1 exceeds x for every nonnegative x
graph-triangle-threshold          [forall]  Every 5-vertex graph with 5+ edges has a triangle
unbounded-quadratic               [forall]  n^2 + 1 exceeds n for every natural number n
```

Every bundled problem is a known answer test. The ground truth is documented and
the test suite asserts the machine reaches it.

## 2. Solve one

```bash
.venv/bin/simagent solve circumcenter-in-triangle --trials 800 --seed 7
```

Real output:

```
== Circumcenter lies inside every triangle ==
  searching: 800 trials, seed 7 (forall)
  verdict: DISPROVED - certified counterexample (exact rational arithmetic)
  proof: counterexample - verified by sandbox+lean
  rendered preview.png (matplotlib)
  manim scene written (render skipped; pass --render-manim)

Run dir: runs/circumcenter-in-triangle-seed7
```

If you have no Lean toolchain installed the stamp reads `sandbox` instead of
`sandbox+lean`, and the answer says why. Nothing else changes.

## 3. Read the run directory

The run directory is the whole story of the run. Nothing is hidden in a database.

| File | What it is |
|---|---|
| `spec.json` | The conjecture as a native claim: spaces, recipe, registry keys. No code |
| `report.json` | The search report: verdict, witness, margin range, certification detail |
| `answer.md` | The readable verdict, witness, and method. **Read this first** |
| `answer.tex` | The same thing as a classical LaTeX write up |
| `proof.json` | The proof record, including the `verified_by` stamp |
| `certificate.lean` | The generated Lean file the kernel accepted. Only present when one was made |
| `conjecture.lean` | A Lean 4 skeleton of the original statement. Always flagged unchecked |
| `preview.png` | matplotlib 3D render of the decisive configuration |
| `scene.json` | The scene graph, the same data the browser and Manim draw |
| `scene_manim.py` | A self contained Manim scene you can render any time |

Open `answer.md`:

```markdown
## Verdict: DISPROVED - certified counterexample (exact rational arithmetic)

**Proof method:** counterexample
**Verified by:** sandbox+lean

A single explicit instance violates the universally quantified statement. The
instance was found by sandbox search, snapped to rational coordinates, and the
violation re-decided in exact arithmetic.

Lean certificate: `certificate.lean` - accepted by the Lean kernel, axiom-free.

**Witness** (exact rationals):
- `T` = (3/10, 15/16), (2/3, -2/3), (-7/15, 9/10)
```

## 4. See all four shapes of answer

There are exactly four things the harness can tell you. Run one of each and
compare the verdict lines.

```bash
.venv/bin/simagent solve circumcenter-in-triangle    # counterexample
.venv/bin/simagent solve sum-of-odds-square          # exhaustion
.venv/bin/simagent solve positive-quadratic          # direct, sum of squares
.venv/bin/simagent solve euler-characteristic-hull   # evidence only
```

| Problem | Verdict line | Method | Stamp |
|---|---|---|---|
| `circumcenter-in-triangle` | DISPROVED, certified counterexample | counterexample | `sandbox+lean` |
| `sum-of-odds-square` | PROVED on the declared finite domain, every case checked | exhaustion | `sandbox+lean` |
| `positive-quadratic` | PROVED for every configuration, direct proof checked by the Lean kernel | direct | `sandbox+lean` |
| `euler-characteristic-hull` | no counterexample found, evidence for the conjecture, not a proof | none | none |

The last row is the important one. The claim is true, and the machine still
refuses to call it proved, because sampling is not a proof. That refusal is the
product.

## 5. Play by hand

```bash
.venv/bin/simagent play circumcenter-in-tetrahedron
```

This opens a REPL on the same world. **Open `runs/play-<id>/preview.png` in your
editor and leave it open.** It re-renders after every command, so the 3D view
updates live as you type. VS Code reloads changed images by itself.

An example session, with the shape of the replies you get:

```
(sandbox) nudge T[3] 0 0 -0.5      # flatten the tetrahedron by hand
  status: holds=True  margin=+0.0812
(sandbox) refine                   # let the annealer push it over the edge
  status: holds=False margin=-0.4310
(sandbox) certify                  # exact verdict for what is on screen
CERTIFIED in exact rationals: property FAILS for this configuration
(sandbox) hunt 2000                # or let the machine search from scratch
(sandbox) manim                    # cinematic render of the current state
(sandbox) help                     # everything else
```

Human and machine share the same moves. You place points, the harness hunts and
refines, and `certify` turns whatever is on screen into an exact verdict. That
symmetry is deliberate: it is the same tool set the LLM gets in agent mode.

## 6. Run the tests

```bash
.venv/bin/python -m pytest -q
```

The suite is offline by design: no API calls, no Manim requirement. If you also
work on the TypeScript runtime:

```bash
(cd agent && PI_OFFLINE=1 npm run build && PI_OFFLINE=1 npm test)
```

## Optional extras

You do not need any of these to use the machine, but each unlocks something.

**Lean 4** raises verdicts from `sandbox` to `sandbox+lean`. Certificates need
only Lean core, no Mathlib and no lake project, so setup is one command:

```bash
curl -sSf https://elan.lean-lang.org/elan-init.sh | sh -s -- -y --default-toolchain stable
```

SimAgent finds `~/.elan/bin/lean` by itself. Override with `SIMAGENT_LEAN`.

**Manim** renders the cinematic scenes. It needs system cairo and pango, which
pip cannot provide, so the no root route is a conda-forge environment:

```bash
curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj -C ~/.local bin/micromamba
~/.local/bin/micromamba create -y -p ./.manim-env -c conda-forge python=3.12 manim ffmpeg
```

SimAgent auto detects `./.manim-env`, or set `SIMAGENT_MANIM_PYTHON`. Without it,
`scene_manim.py` is still written on every run, it just is not rendered.

**Node 22.19 or newer** builds the pi runtime, which is what lets an LLM drive
the sandbox:

```bash
(cd agent && npm ci --ignore-scripts && npm run build)
```

**A Claude API key** (`ANTHROPIC_API_KEY` or an `ant auth login` profile) enables
turning plain English into a claim:

```bash
.venv/bin/simagent formalize "the incenter of every triangle lies inside it"
```

Next: [how it works](03-how-it-works.md).
