# Glossary

Terms this project uses in its own specific way. Where a word has a general math
meaning, the entry says what SimAgent means by it.

## The core vocabulary

**Margin.** One real number returned by a claim's measure. The sign decides the
claim: `margin > 0` means the property holds, `margin < 0` means it fails. It is
continuous, which is what makes search possible. Everything in the harness is
built around this one convention.

**Claim.** A conjecture in the form the harness can run: a quantifier (`forall`
or `exists`), the free variables and their Spaces, a recipe of constructions, and
one distinguished measure. It is pure data. No code is stored and none is
executed.

**Spec.** The on-disk JSON form of a claim, written as `spec.json` in every run
directory. `claim/1` is the only executable format. Older run traces remain
readable, but their code-bearing problem files are refused because loading a
math question must never execute code from that file.

**Space.** The domain a free variable lives in, and the input boundary of the
system. It knows how to sample, validate, perturb, produce exact values, and
where finite, enumerate every case. Today: `Box` in R^d, `IntBox` in Z^d, and
`GraphSpace`.

**Entity.** A named thing in the world. *Free* means its value comes from a
Space. *Derived* means it is computed by a recipe from other entities, so its
coordinates are consequences, not inputs. Move an ancestor and a derived entity
follows.

**Recipe.** The ordered list of constructions that builds derived entities from
free ones. It is replayed in floats for search and again in exact fractions for
certification, which is how a margin over a derived value can still be certified.

**Measure.** The function that turns world state into the margin plus qualitative
words. It is deliberately compressive: the model gets a calibrated observation,
not a coordinate dump.

**Op.** The only channel that changes the world. It is also the agent's action
vocabulary. A closed registry of ops replaces the ability to execute code.

**Journal.** The append-only record of everything that happened. State equals
replaying the journal, which makes it the save format, the undo stack, the
notebook feed, and the thing a branch verifies by hash.

**View.** The output boundary. `identity` draws the scene as it is for dimension
3 or less. `field` paints the margin over a 2D slice of configuration space.
`sweep` plots the margin along one coordinate. `trajectory` plots it against the
step number. `ghost` overlays before and after.

**Zero contour.** The line where the margin is zero in a `field` view. It is the
boundary of the theorem, drawn. For the triangle claim it is the Thales circle.

## Proof vocabulary

**verified_by.** The trust stamp on a proof record. Only
[`proof.py`](../../src/simagent/proof.py) may write it. Values, strongest first:
`sandbox+lean`, `sandbox`, `lean`, `none`. See
[how it works](03-how-it-works.md) for what each means.

**Certify.** Recompute the margin at the current configuration in exact rational
arithmetic with sympy. This is what turns a floating point near miss into a real
verdict.

**Rationalize.** Snap a floating point configuration to nearby fractions with
small denominators, so it can be certified and written into a Lean certificate.

**Exhaust.** Check every case of a finite integer domain. Not sampling, not a
subset. If any case raises an error, the whole verdict is marked incomplete.

**Counterexample.** One explicit configuration that violates a `forall`. Enough
to disprove it outright.

**Construction.** One explicit configuration that satisfies an `exists`. The same
machinery, aimed the other way.

**Sum of squares (SOS).** How this harness *proves* a `forall` over a continuous
domain, since search can only refute one. It writes the margin as a sum of
squares, which makes non-negativity self evident. The `cases` and `induction`
instruments reuse the same machinery, on each half of a split and on the step
increase respectively. The search for a certificate is deliberately incomplete:
it pins free parameters at zero instead of solving a full semidefinite program,
so a failure means "no certificate found", never "none exists". The certificate
must be strict, because proving `margin >= 0` does not settle a strict claim.

**Pin.** The defining equations a certificate states for a derived entity, so
the Lean kernel checks how a number was constructed instead of taking the
harness's word for it. A pin must make its construction UNIQUE, which is why
the line pins also assert the line exists: if A and B coincided, "F is on line
AB and perpendicular to it" would be true of every point, and the certificate
would hold while establishing nothing. Without a pin, a recipe certificate is
refused and the claim keeps its `sandbox` stamp.

**Certificate.** The generated Lean file, `certificate.lean`. It restates the
decisive arithmetic in Lean 4 core and is checked by the Lean kernel.

**Skeleton.** `conjecture.lean`, a Lean statement of the original conjecture with
the proof left open. It is always flagged unchecked. Do not confuse it with the
certificate.

**Axiom free.** The Lean kernel's `#print axioms` reports the theorem depends on
nothing. The checker requires this per theorem, by name, and treats anything else
as a failure.

**statement_review.** A field on the proof record saying whether a human still
needs to confirm the Lean theorem states the intended conjecture.
`bundled-trusted` for reviewed bundled claims, `spec-generated-review-needed` for
everything else, including everything an LLM writes.

**Evidence.** A search found nothing. It is data, it is on the record, and it is
never called a proof.

## Agent vocabulary

**Harness.** This project. The layer that gives a reasoner capability,
perception, verification, and memory, and that does none of the reasoning.

**Instrument.** Any tool the harness exposes. An instrument reports its own
limits, including why it failed. It never names the next method to try.

**Imagine.** Run operations on a fork of the world, look, and throw it away. A
thought experiment. It appears as a dashed cell with a ghost image and can never
change the real state.

**Expect.** A falsifiable prediction the model registers, which the harness scores
mechanically against later states. The model cannot grade its own prediction.

**Trace.** `trace.jsonl`, the human readable mind trace the notebook replays.

**Kernel journal.** `kernel-journal.jsonl`, the replayable record of kernel calls
and state hashes. A branch replays a prefix of it and refuses to continue unless
the hash matches exactly.

**Branch.** Continue a run from an earlier step. It copies the pi conversation
prefix, replays the kernel journal prefix, verifies the state hash, and records
provenance.

**Adopt.** Continue a run that already ENDED. `--adopt RUN_DIR` replays the whole
earlier journal, hash checked like a branch, then writes an `adopt` event that
re-opens the world, because replay alone would restore the ending too and the
next model would be refused at its first move. A branch rewinds inside one run;
adopt picks up a finished one.

**Rounds.** `--rounds N` loops adopt: round k adopts round k-1. It stops on a
kernel stamp, on a round that took no act of its own, or on the budget you
declared, and never on the model's own sense of being finished.

**Handoff.** `handoff.md`, what one run leaves the next: what was established,
and every instrument that ran and established nothing, carrying that
instrument's own reason. Written at every ending, including running out of
turns, so a run killed by its budget no longer leaves an empty narrative.

**Gap.** The proving side's margin. When a sum of squares attempt is refused,
`progress.gap` says how far the closest candidate Gram matrix stood from being
a sum of squares: about -1 far off, -3e-05 for a near miss, exactly 0 once the
exact check accepts one. It is perception, never a verdict, and a claim that
misses by a hair is still false.

**pi.** The pinned TypeScript runtime under [`agent/`](../../agent/) that owns
provider authentication, model turns, events, steering, and conversation
sessions. It transports messages. It cannot stamp a verdict.

**Kernel.** In this project the word appears in two senses, and the difference
matters. The **proof kernel** is `proof.py`, the only module that assigns a
verdict. The **Lean kernel** is Lean 4's own checker, the only authority on
deductive truth. The Python process the pi service drives is called the kernel
process because it hosts the former.
