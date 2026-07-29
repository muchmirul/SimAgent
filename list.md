# SimAgent: what to do next

Snapshot: 2026-07-25. Baseline: 215 Python tests + 12 pi tests green, benchmark 11/11.

This file is the ranked work list. It is scored against the goal below, not
against what is interesting to build.

---

## The goal

1. SimAgent is the best **harness** for an AI model to solve math by
   *experiencing* it, seeing and doing, with equations as formalization rather
   than the medium of thought. First principles, not answers gathered from
   outside.
2. Human and agent unblock each other: the human helps when the agent is stuck,
   the agent helps when the human is stuck, through a UI where the human can
   comment on any step.

## Two decisions that scope every task below

**1. SimAgent is only a harness. It never does the model's thinking.**

> Does this give the model something it cannot get by thinking?
> If yes, the harness owes it. If no, hands off.

Capability, perception, verification and memory cannot be produced by thinking,
so they are the harness's job. Strategy, insight and choice of proof method are
the model's. Reporting an instrument's own limits is information and belongs to
the harness; naming which method to try next is steering and does not.
`test_harness_never_picks_the_method_for_the_model` pins this.

**2. The math domain is fixed.** The standard, the four-part admission test and
the served/not-yet/never lists live in ARCHITECTURE.md under "Scope: which
mathematics this harness serves". Stated once, there.

---

## Done

The previous ten tasks all landed. What each one actually bought:

| # | Task | Outcome |
|---|---|---|
| 1 | Readable certificates | `answer.md` carries the real sum-of-squares identity, checkable by hand in ten seconds with no Lean and no trust in this code. |
| 2 | One live session | The model ran `look → plan → hunt → sum_of_squares → finish` and proved the claim. Two harness defects fell out and were fixed. |
| 3 | Benchmark | `simagent bench`: 11/11, checking verdict AND strength. Its first run found a real kernel bug (see below). |
| 4 | Conditions as ingredients | `assume` on Claims; certificates of the form `p - eps = sigma_0 + sum sigma_k g_k`, so conditional claims are provable at all. |
| 5 | Discrete Space | `GraphSpace`: graphs as adjacency matrices, edge-flip moves, composable graph constructors, a graph scene. |
| 6 | Cases and induction | Six of the ten methods now have an instrument. Induction settles UNBOUNDED statements, which nothing here could do before. |
| 7 | Real certificate search | Alternating projection plus rational rounding replaced pinning free parameters at zero. |
| 8 | Packaging | Clean `pip install` verified from outside the checkout; `SIMAGENT_LEAN=off` makes the no-Lean path testable, and it degrades honestly. |
| 9 | Symmetry reduction | Graph enumeration up to isomorphism (1024 → 34 on five vertices), opt-in and guarded against label-sensitive claims. |
| 10 | Geometry Lean stamps | Recipe certificates PIN each construction to its defining equations, so geometry claims reach `sandbox+lean`. |

**The bug worth remembering.** `sp.nsimplify` was being applied to values that
were already exact rationals. It searches for a "nicer" closed form and on one
witness triangle returned an irrational surd merely CLOSE to the true
coordinate: exact arithmetic had silently left the rationals. Only the Lean
step crashing exposed it. Never point nsimplify at something already exact.

---

## What is left

| # | Task | Why it matters | Whose job |
|---|---|---|---|
| 1 | **Find something new.** Point the harness at an open finite-dimensional conjecture. | Reproducing known counterexamples makes a demo; one new result makes a tool. This is the only measure the community will care about, and everything above exists to make it possible. | Model |
| 2 | **More live sessions, on problems the model has not seen.** | One run is one data point, and it was on a bundled claim. The transcript is the only honest source of harness defects. Watch where it stalls; each stall with everything available is the model's limit, each stall for want of a tool is ours. | Harness (evaluation) |
| 3 | **Proving is a cliff, refuting is a progression.** Toward a counterexample the model has sample, nudge, refine, hunt and exhaust, each answering with a margin number. Toward a proof it has `sum_of_squares` and friends: accepted or refused, plus one sentence, with no quantity saying how close the attempt came. | The harness owes capability and perception in BOTH directions and today pays them unevenly, which is why the machine reads as a counterexample machine. A second certificate attempt starts from the same place as the first, so the model cannot work its way toward a proof the way it works its way toward a witness. Scope it right: the proving side WORKS (four of the five true bundled claims reach `sandbox+lean`), so this is a missing feedback signal, not a broken verifier. Not a guess: known now, without waiting for 1 and 2. | Harness |
| 4 | **Pi's coding-agent framing leaks in.** The model's first thought in the live run was "starting initial codebase exploration". | It recovered immediately, so this is small, but it means the session begins pointed at the wrong task. | Harness |
| 5 | **More Space types: permutations, subsets, lattices.** | GraphSpace proved the pattern works. Each new Space opens a class of objects a mathematician can finally state. Add on demand, not in advance. | Harness |
| 6 | **Pins for the remaining constructors.** `incenter` and the line constructors have no Lean pinning equations, so claims using them stop at `sandbox`. | Correct today (it fails closed), but it caps the strongest verdict for part of the geometry kit. | Harness |
| 7 | **The last four methods.** Contradiction, contrapositive, combinatorial, infinite descent have no instrument. | A model may declare a sound method and find the harness cannot help it execute. Lower priority than it looks: those four are harder to mechanize and rarer in this domain. | Harness |

### Order

**1 and 2 together**, then let what they reveal rank 4 to 7. Item 3 is the
exception: it is the one gap already established rather than guessed, so it does
not wait for a live session to justify it. Every other remaining item is a guess
until a model is watched failing on a problem that matters.
