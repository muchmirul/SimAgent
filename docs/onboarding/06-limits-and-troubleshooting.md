# Limits and troubleshooting

## What this machine can and cannot serve

SimAgent is not a general mathematics tool, and it was never built as one. The
scope is fixed, and it follows from the machine described in
[what SimAgent is](01-what-is-simagent.md). Before proposing a problem or a
feature, apply this test. A claim is in scope only if **all four** hold.

| # | Test | It fails when |
|---|---|---|
| 1 | **Finite configuration.** The free variables form a finite dimensional Space that can be sampled and enumerated | Stating the claim needs a function, a limit, or an infinite family |
| 2 | **Scalar margin.** One real number whose sign decides the property | The property cannot be reduced to a single sign |
| 3 | **Renderable state.** The configuration can be drawn, or honestly projected with the projection labeled | There is nothing to look at, so the visual approach buys nothing over a text tool |
| 4 | **Exactly checkable.** The margin evaluates in exact rational or algebraic arithmetic at a rational point | It needs transcendental values or floating point only, so no verdict can rise above evidence |

Failing test 1 **only** because the object needs a Space nobody has built yet, a
graph, a permutation, a polytope, a lattice, is a fixable gap: build the Space.
Failing test 2, 3, or 4 is permanent, and no new Space repairs it.

| Status | Domains |
|---|---|
| **Served today** | Geometry of points in R^d, algebraic inequalities, linear algebra, optimization, bounded integer claims |
| **In scope, Space not built yet** | Discrete and extremal geometry, combinatorics, graph theory |
| **Out permanently** | Calculus, real and complex analysis, topology, abstract algebra, set theory, logic, cryptography, number theory beyond bounded claims |

None of the seven Millennium problems is admissible, and no amount of building
changes that. They live in analysis, topology, number theory, and logic, which
are infinite in exactly the way this machine is finite.

What the scope *is* aimed at: one explicit finite object that settles a real
question. Euler's sum of powers conjecture stood about 200 years and fell to a
single line of numbers. Borsuk's stood 60 years and fell to one finite point set.
The Hirsch conjecture stood 53 years and fell to one polytope. That is the shape
of this machine, and discrete and extremal geometry is where such questions are
still open.

## Reading verdicts honestly

The wording in `answer.md` is chosen carefully and is never rounded up.

| Wording | What it means | Is it a proof |
|---|---|---|
| CERTIFIED counterexample | Proved false by an exact rational instance | Yes, done |
| PROVED on the declared finite domain | Every case checked | Yes, on that domain only |
| PROVED for every configuration, checked by the Lean kernel | A direct proof the kernel accepted | Yes |
| numeric candidate | Looks false, but the exact check did not confirm it | No |
| no counterexample found | Evidence it may be true | No, and it never becomes one by running longer |

Three ceilings will show up in real runs, and all are stated in the output rather
than hidden:

- **Above dimension 3 the simplex certificate is not generated yet.** The verdict
  tops out at `sandbox`, meaning exact rational arithmetic.
  `circumcenter-in-4simplex` is the bundled example.
- **A recipe built from an unpinned constructor tops out at `sandbox`.** Lean
  takes only free variables as atoms, so the certificate must pin each
  construction to its defining equations. Fourteen of the nineteen constructors
  carry pins today: `circumcenter`, `orthocenter`, `barycentric`, `centroid`,
  `midpoint`, `sub`, `dot`, `cross2`, `distance_sq`, `segment`, `foot`,
  `reflect`, `intersect_lines`, `simplex_volume`. The other five raise rather
  than accept a weaker certificate, and each says why: `incenter` is weighted by
  side lengths, which are square roots, so it is algebraic and never rational;
  `vertex` picks a row by a value this encoding cannot select on; and the three
  graph counts have no Lean encoding yet. `orthocenter-in-triangle` is the
  bundled example of a pinned recipe reaching `sandbox+lean`.
- **`GraphSpace` claims have no Lean hook yet.** `graph-triangle-threshold`
  produces a certified counterexample stamped `sandbox`.

## Troubleshooting

### The wrong Python or the wrong simagent runs

Symptom: import errors, a missing `simagent` command, or behavior that does not
match this repository.

Always use the explicit path, `.venv/bin/simagent` and `.venv/bin/python`. A bare
`simagent` on your PATH may belong to another project's environment. This is the
most common first session problem.

### `unknown problem 'x'`

Run `.venv/bin/simagent list` for the exact ids. They are hyphenated and case
sensitive.

### The verdict says `sandbox` where you expected `sandbox+lean`

Either Lean is not installed, or the claim hits one of the two ceilings above.
Install Lean core with:

```bash
curl -sSf https://elan.lean-lang.org/elan-init.sh | sh -s -- -y --default-toolchain stable
```

No Mathlib and no lake project are needed. SimAgent finds `~/.elan/bin/lean`
automatically. Override the path with `SIMAGENT_LEAN`. Without a toolchain,
everything still works, verdicts just stop one rung lower and say so.

### No Manim video

`scene_manim.py` is written on every run whether or not Manim exists. Rendering
needs system cairo and pango, which pip cannot install, so use the conda-forge
route from [your first run](02-first-run.md), or set `SIMAGENT_MANIM_PYTHON` to a
Python that already has Manim. Then:

```bash
.venv/bin/simagent solve circumcenter-in-tetrahedron --render-manim
.manim-env/bin/manim -qm runs/<dir>/scene_manim.py ConjectureScene
```

### The notebook loads but no models appear

The TypeScript runtime is not built or not authenticated:

```bash
(cd agent && npm ci --ignore-scripts && npm run build)
(cd agent && npx pi)     # then /login inside pi, and quit
node agent/dist/cli.js auth-check --provider <provider> --model <model>
```

Node 22.19 or newer is required. Note that only one controlled pi run is allowed
at a time.

### The run fails naming a function that does not exist

A message like `session failed: AttributeError: module 'simagent.agent' has no
attribute 'run'` usually means the server is old, not that the code is broken.
Python loads a module once when the process starts, so a `simagent web` left
running for days keeps executing the code as it was that day. Editing a file
changes nothing until you restart.

```bash
pkill -f "simagent web"
.venv/bin/simagent web
```

Check the age of the process before you go hunting for the function:

```bash
ps -eo pid,etime,cmd | grep "simagent web" | grep -v grep
```

The rule: restart the notebook after any Python change. It does not hot reload.
Also read the terminal running the server, since the browser shows only the last
line of the error while the full traceback stays in the terminal.

### Typing a conjecture in plain words fails

That path asks a pi-routed model to formalize the sentence, so it needs
one model pi has authenticated. Without one, use a bundled
problem, or write the spec JSON yourself and pass `--spec`.

If the formalizer runs but the claim is rejected, that is the validator working.
Output is checked against the closed registries and smoke tested in the sandbox,
and errors are fed back for repair before anything is accepted. A conjecture that
cannot be expressed in the closed vocabulary needs new vocabulary, which means a
new registry entry, not a workaround.

### Port 8642 is busy

```bash
.venv/bin/simagent web --port 8700
```

The notebook binds locally and has no authentication. Do not expose it.

### You cannot steer a run you started from the CLI

Correct, and expected. The browser can view and replay any recorded run, but a
CLI run is owned by a different controller. Restarting the web server also
preserves traces for replay while dropping control of old sessions. Start runs in
the browser when you want comments, stopping, or branching.

### A test fails

The suite must stay offline: no API calls and no Manim requirement. If a failure
mentions network access or a missing renderer, that is a bug in the test, not a
missing dependency on your machine.

## Before you change code

Read [../../ARCHITECTURE.md](../../ARCHITECTURE.md) and
[../../CLAUDE.md](../../CLAUDE.md) first. The short version of the rules that
must not regress:

1. Only `proof.py` writes `verified_by`. Never fake a stamp anywhere else.
2. New capability means a new mechanized check or a new certificate shape, not a
   new claim the harness cannot check. Fail closed.
3. Every bundled claim is a known answer test, and the suite asserts the machine
   reaches that answer.
4. Shells (CLI, REPL, web) may render state. They must not compute verdicts.
5. Every change must serve a domain the scope section admits. Run the four part
   test first.
6. The harness never does the model's thinking. Ask whether a change gives the
   model something it cannot get by thinking. Capability, perception,
   verification, and memory belong to the harness. Strategy, insight, and the
   choice of proof method belong to the model.
7. New formalization vocabulary means a registry entry with an accurate `doc`
   string, because the model's menu is generated from those docs.
