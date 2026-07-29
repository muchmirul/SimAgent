# SimAgent TODO

Ranked by what most directly blocks the project goal. Complete these in order.
Do not add broad new capability before real run traces show that it is needed.

## 0. Adopt the numbers-first decision

Decided 2026-07-27. The model reasons in text and coordinates; pictures are
rendered for the human. Rationale: current models read numbers exactly and
pixels coarsely, so the model's senses are margins, exact coordinates, and
`measure` text. The image channel is not deleted: it becomes a flagged arm
that item 2 will judge with evidence. Implement in this sequence, because the
docs are the contract the code is checked against and the eval must run
against the decided shape of the harness.

- [x] Rewrite CLAUDE.md and AGENTS.md (kept byte-identical): core idea says
      numbers are the model's channel and pictures are the human window.
- [x] Rewrite the agent system prompt in `agent.py`: senses are exact
      coordinates, margins, and `measure` text; `look`/`view` are optional
      instruments, not the model's identity ("use your eyes" goes).
- [x] Add a per-run images flag, default off: when off, `look`/`view`/
      `imagine` return text only and attach no image blocks to the model
      context. Renders are still written to disk for the trace and notebook.
      Threaded through `AgentRun`, `KernelTransport` (`--images`), the pi
      runtime, `simagent agent --images`, and `POST /api/agent/start`.
- [x] Vision is now required by the CHANNEL, not the harness: a text-only
      model drives a default run, and is refused only for an `--images` run.
- [x] Notebook unchanged: pictures remain the human channel. No code; this
      line records the ruling so nobody "fixes" the renders away.

**Done when:** a run with the flag off sends zero image blocks to the model,
the saved trace still shows every render, and both doc files state the
numbers-first rule.

## 1. Make the entered problem a trustworthy contract

The kernel can correctly prove a generated Claim while that Claim differs from
what the user entered. The original wording and formalizer provenance must stay
visible, and a nearby bounded claim must never be accepted silently.

- [x] Save an `intake.json` artifact with the exact user text, formalizer
      provider/model, generated Claim, validation result, and Claim hash.
      (`intake.py`, written by `solve`, `agent`, and the notebook.)
- [x] Let formalization return either a supported Claim or a typed refusal.
      (`FormalizationModel` + `FormalizeRefused`; a refusal is not retried.)
- [x] Remove the instruction to silently choose the nearest bounded form.
- [x] Show the original text beside the executable Claim before the run.
- [x] Show its quantifier, domain, assumptions, constraint, margin meaning, and
      verification limits in plain English. (`intake.describe_claim`.)
- [x] Require explicit human approval of the Claim hash before starting an
      agent on plain-English input. (`--approve-claim HASH`; the notebook
      answers 428 and renders the claim with a yes/no, checked in a real
      browser over CDP.)
- [x] Print both the source text and review state in final outputs.
      (`answer.md` header and the end of a `solve` run.)
- [x] Keep this review separate from `verified_by`. Approval confirms the
      translation, not the mathematics.

**Done when:** a fake formalizer that changes a bound or inequality cannot start
silently, changing the Claim invalidates prior approval, and every run can name
both the original question and the model that formalized it.

## 2. Measure whether the experiential loop helps

The offline benchmark checks known answers and kernel strength. It does not
show that acting in the world (sample, nudge, refine, margins back) helps a
routed model discover an answer, and it does not show whether images ever earn
their tokens over the numbers-first default from step 0.

- [x] Add an online `simagent eval` runner with a versioned task manifest.
      (`evaluate.py`, `eval/1`, `simagent eval --arms ...`.)
- [x] Use problems that are not bundled examples and whose initial state does
      not already settle the claim. (`seed_settles_the_claim` screens every
      seed and the skip is recorded in `eval.json`, never silent.)
- [x] Run several recorded initial seeds for each model and thinking level.
- [x] Add evaluation-only comparisons using the same model and budget:
      the tool loop with text-only senses (the default), the same loop with
      the images flag on, and automatic search alone. (Arms differ by one
      flag; a test asserts the two model commands are otherwise identical.)
- [x] Record provider, model, thinking level, seed, turn budget, elapsed time,
      tool errors, human interventions, and kernel result.
- [x] Score only mechanical outcomes: certified solve rate, `verified_by`,
      turns to result, and whether a branch improved the result.
- [x] Set the required improvement before looking at the results.
      (`required_improvement` lives in the manifest; `compare()` reads it from
      there, never from the results.)
- [x] Use failure traces to decide which harness capability comes next.
      MEASURED LIVE on 2026-07-28, openai-codex/gpt-5.6-sol, three seeds on
      `circumcenter-near-centroid` (`runs/eval-live/eval.json`):

      | arm | runs | certified | rate | median turns |
      |---|---|---|---|---|
      | search | 3 | 0 | 0.00 | - |
      | text | 3 | 3 | 1.00 | 9 |
      | images | 3 | 3 | 1.00 | 11 |

      Both model arms beat the threshold declared before the run (+1.00
      against a required +0.25). The floor is honest: search draws 1641 valid
      samples out of 2000 and anneals 500 steps, and its closest margin is
      still 565 against a target of 0. So on this task the loop does something
      search cannot.
      Images did NOT separate from text: same 3/3, slightly more median turns
      (11 vs 9). With n=3 that is not evidence against pictures, only the
      absence of evidence for them, so numbers-first stays the default.
      What this does NOT show: one task, one model, one provider, 25-turn
      budget. A wider manifest is the next measurement, not a new feature.

### First evaluation case

Use `problems/circumcenter-near-centroid.json`. In the current audit, automatic
search missed the counterexample in 2,000 trials, while three successive
`refine` calls crossed the boundary and exact certification confirmed it. This
makes it a useful test of whether a model can discover a multi-step path from
the world rather than merely certify an initial sample.

**Done when:** repeated runs show whether the experiential loop improves
certified results or reduces work against the declared comparisons, and
whether images add anything over text-only senses. If the loop does not help,
revise action and perception tools before adding more features.

## 3. Make human-agent collaboration seamless

Comments, exact branches, and attributed human moves already work. The human
still cannot pause at a settled step, directly manipulate a picked object, or
work beside more than one agent lane.

- [x] Add pause and resume at settled tool boundaries. The gate is the
      model's NEXT tool call: the previous action is journaled and the next has
      not started. Running tools finish first, and a paused tool leaves the
      batch so a human move never waits on the model it is waiting for.
- [x] Bind a picked 3D primitive to its variable and row automatically.
      (`scene.points(binds=...)` names the free variable, so index i is row i.
      A derived point leaves it empty: it has no row to change.)
- [x] Support direct point movement, plus visible `nudge` and `construct`
      controls, through the existing journaled user-action boundary.
- [x] Show the agent's response to each human move or comment clearly. The
      panel names the trace step the move became and says the agent was told;
      opening a live run in a second tab now adopts its controls.
- [ ] Build P7 concurrent lanes after the single-lane workflow is measured.
      UNGATED as of 2026-07-28: item 2 measured the single lane and it works
      (0.00 -> 1.00 certified). This is now the next buildable item.
- [ ] Add compact peer summaries, fork-from-peer, and `adopt` with provenance.
      GATED: lanes must exist first.
- [ ] Re-certify every adopted witness in the receiving lane. GATED with adopt.
- [ ] Compute the claim-level best result from kernel reports only. GATED
      with lanes.

Found while building this: the soft circumsphere sits in front of every vertex,
so a raycast pick could never reach a point at all; picking now prefers a
primitive bound to a variable. The browser test swept the canvas and caught it,
which an API test could not have.

**Done when:** a browser test pauses a live run, moves a picked point, shows the
step as made by the human, resumes the model, and replays the exact state. The
multi-agent gate then requires two independent lanes, local recertification on
adoption, and stopping one lane without stopping the other.

## 4. Expand vocabulary only from observed failures

STILL GATED, for a reason that changed. The model arms have now run, and they
produced no failure to act on: every model run certified, none stalled, no
tool error, no missing Space. So the evidence these items ask for still does
not exist, and the honest next step is a WIDER evaluation manifest that finds
a task the harness cannot serve, not a guess at which capability to add.

The current closed vocabulary remains narrow. Natural-language formalization
cannot emit `GraphSpace` even though the core supports it, graph claims lack a
Lean hook, and certificates above dimension 3 stop at `sandbox`. Constructor
pins are no longer the gap (14 of 19 as of 2026-07-29): what is left there is
the three graph counts, `vertex`, and `incenter`, which is permanent.

- [ ] Expose `graph` and `graph_iso` in the formalizer schema and prompt.
- [ ] Add a known-answer formalization test for a graph Claim.
- [ ] Rank missing Spaces from repeated evaluation failures.
- [ ] Add permutation, subset, lattice, or polytope Spaces only when a current
      admitted problem needs one.
- [x] Add Lean pins for constructors that block real evaluated claims. Done
      2026-07-29 for the geometry kit: sub, dot, cross2, distance_sq, segment,
      foot, reflect, intersect_lines, simplex_volume. What remains needs a NEW
      encoding rather than another pin (graphs, and selecting a row by index).
- [ ] Add a graph certificate hook when a graph result needs independent Lean
      checking.
- [ ] Implement the documented LU-witness certificate shape when a result above
      dimension 3 needs a Lean stamp.
- [ ] Add instruments for the remaining proof methods only after a model trace
      shows that the missing execution support caused the stall.

**Done when:** each new vocabulary item has an accurate registry description,
exact checking where required, an honest view, a known-answer test, and one
current caller from the evaluation set.

## Execution order

0. Numbers-first pivot: docs, agent prompt, images flag.
1. Problem contract and approval gate.
2. Real model evaluation: loop and channel comparisons.
3. Human control improvements, then P7 collaboration.
4. Vocabulary and proof work selected by the resulting traces.

## Baseline checked before this list

- Python suite: 241 passed.
- Pi suite: 15 passed.
- Bundled benchmark: 11/11.
