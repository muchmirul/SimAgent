# SimAgent onboarding

Start here if you have never seen this project. These pages assume no prior
knowledge of the codebase, of Lean, or of proof assistants. They explain what
SimAgent is, what it does when you run it, and how to read what comes out.

## SimAgent in 60 seconds

You give it a math conjecture. It builds a small world you can look at and poke,
searches that world, and returns an answer with an honest label on it.

| Step | What happens |
|---|---|
| Input | A conjecture, either a bundled one or plain English |
| World | The conjecture becomes points in space plus one number called the margin |
| Search | The machine samples and nudges the points, trying to break the claim |
| Picture | Every state is drawn (matplotlib, Manim, or live 3D in a browser) |
| Answer | A verdict with a trust stamp: it never calls evidence a proof |

The margin is the whole trick. It is one real number: **margin > 0 means the
property holds, margin < 0 means it fails**. Search just pushes that number
downhill until it crosses zero, and then exact fraction arithmetic decides the
case for real.

## Reading order

1. [What SimAgent is](01-what-is-simagent.md) - the idea, and one worked example end to end.
2. [Your first run](02-first-run.md) - install, run, and read the output files.
3. [How it works](03-how-it-works.md) - the pipeline, the eight atoms, the trust ladder.
4. [The notebook and agent mode](04-notebook-and-agent.md) - watching an LLM work, and steering it.
5. [Glossary](05-glossary.md) - every term this project uses in its own way.
6. [Limits and troubleshooting](06-limits-and-troubleshooting.md) - what it cannot do, and what to do when a command fails.

## The other docs, and who they are for

| File | Audience |
|---|---|
| [../../README.md](../../README.md) | Project pitch and feature summary |
| [../../GUIDE.md](../../GUIDE.md) | Day to day operating guide for the web notebook |
| [../../ARCHITECTURE.md](../../ARCHITECTURE.md) | Kernel design and the rules a contributor must not break |
| [../../CLAUDE.md](../../CLAUDE.md) | The module by module map, for anyone editing code |
| [../../plan.md](../../plan.md), [../../list.md](../../list.md) | Roadmap and ranked work list |
| [../P0_PI_SPIKE_REPORT.md](../P0_PI_SPIKE_REPORT.md) | Why the pi runtime was chosen |

This onboarding folder does not repeat the module map. When you are ready to
edit code, read ARCHITECTURE.md and CLAUDE.md.
