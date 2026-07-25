# What SimAgent is

## The problem it attacks

Most math tools work in symbols. You write a statement, you push symbols around,
and you hope. That is hard for people and hard for language models, because
nothing pushes back. A wrong step looks exactly like a right step.

Many math problems, geometry above all, are not really symbolic. They are
*visual*. You can build the object, move it, and watch what happens. SimAgent is
built on that idea:

> Build the conjecture as a small executable world. Look at it. Play with it.
> Let a search play with it too. Write the equations at the end, as a record of
> what happened, not as the medium of work.

## The one machine underneath

Strip away the words and SimAgent is a single machine with four parts:

1. **A finite configuration space.** The free variables of the claim, for
   example the three corners of a triangle, which is 6 numbers.
2. **A scalar margin.** One real number whose *sign* decides the claim.
   Positive means the property holds, negative means it fails.
3. **A picture.** The configuration can be drawn, or honestly projected and
   labeled as a projection when it lives above 3 dimensions.
4. **Exact arithmetic.** The margin can be recomputed in exact fractions at a
   rational point, so a verdict does not rest on floating point.

If a claim fits that machine, SimAgent can serve it. If it does not, SimAgent
says no. See [limits](06-limits-and-troubleshooting.md) for the full test.

## One worked example

Take a classic that sounds true and is false:

> The circumcenter of a triangle lies inside the triangle.

The circumcenter is the point equally far from all three corners. Here is what
SimAgent does with it, in order.

**1. It becomes a world.** The free variable is `T`, a 3 by 2 matrix: three
corners in the plane. That is the configuration space.

**2. It becomes a margin.** A recipe computes the circumcenter from `T`, then
its barycentric coordinates with respect to the triangle. The margin is the
smallest of those three coordinates. If all three are positive the center is
inside. So margin > 0 means the claim holds here.

**3. Search plays.** The machine samples random triangles and then anneals:
nudge a corner, keep the move if the margin dropped, repeat. It is not proving
anything yet, it is hunting for a triangle where that number goes negative.

**4. It finds one and snaps it to fractions.** A floating point near miss proves
nothing, so the winning triangle is rounded to rational coordinates with small
denominators, and the margin is recomputed in exact fractions with sympy.

**5. Lean re-decides it.** The harness writes a small Lean 4 file that encodes
those fractions as integer pairs and asks the Lean kernel to decide the
inequality by pure computation. The check is fail closed: no `sorry`, no
`native_decide`, and every named theorem must come back free of axioms.

**6. You get an answer.** Real output from `simagent solve
circumcenter-in-triangle --trials 800 --seed 7`:

```
Verdict: DISPROVED - certified counterexample (exact rational arithmetic)
Proof method: counterexample
Verified by: sandbox+lean

Witness (exact rationals):
  T = (3/10, 15/16), (2/3, -2/3), (-7/15, 9/10)
  holds=False  margin=-0.2670834250295946
```

That triangle is obtuse. The real theorem is that the circumcenter is inside
exactly when the triangle is acute. SimAgent did not know that. It found the
boundary by playing.

## Who is trusted

This is the part that makes the project unusual. Three pillars, and only one of
them is allowed to say what is true.

| Pillar | Job | Trusted for |
|---|---|---|
| **Python** | Compute, sample, search, exact fractions | Mechanized checks only: counterexample, construction, exhaustion |
| **Lean 4** | State and verify deduction | The kernel is the root of trust |
| **Manim / matplotlib / three.js** | Draw | Nothing. Pictures explain, they never prove |

The model, the human, the web UI, and the comments are all narrative. None of
them can stamp a verdict. Only [`src/simagent/proof.py`](../../src/simagent/proof.py)
assigns the `verified_by` field, and it refuses to round up. "No counterexample
in 5000 trials" is recorded as evidence, forever, never as a proof.

## What SimAgent is not

It is not a general math assistant, and it is not a proof search engine for open
problems in analysis or number theory. It is a harness. Its job is to give a
model or a person capability, perception, verification, and memory. Strategy and
insight stay with the reasoner.

Next: [your first run](02-first-run.md).
