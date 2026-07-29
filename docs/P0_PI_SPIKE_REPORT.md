# SimAgent v2 P0 — Pi 0.81.1 spike report

Date: 2026-07-24  
Branch: `feat/simagent-v2-p0-pi-spike`  
Scope: **P0 only**; no P1 core migration was started.

> Historical note: P6 has now landed. The pi runtime became the production
> control plane, and the temporary Python API and Claude Code agent backends
> described as fallbacks below were removed. Every pi version and limitation
> named below is the state of 0.81.1 on the date above; `agent/package.json`
> holds the version actually pinned today. The commands are reproduced as they
> were RUN that day, so some name provider and model ids that no longer exist:
> do not copy them. Where this report disagrees with the code, the code is
> right.

## Executive result

**Recommendation: GO for P1.**

The offline spike verifies the control-plane assumptions needed to keep Pi
outside the correctness boundary. Pi can run only SimAgent tools, carry image
results and unchanged tool-call IDs, execute a mutable world sequentially,
deliver steering after a batch, persist/branch conversations, and pair a
settled Pi branch with exact Python journal-prefix replay. Python still owns
all search, exact certification, Lean checking, proof construction, and
verdicts.

A paid/networked provider smoke was intentionally **not run**. The included
manual command validates an already-authenticated real vision model through
Pi's normal `ModelRuntime`; the retained legacy `claude-code` backend is the
fallback until that smoke is run in an authorized environment.

## Versions and commands

Validated runtime:

| component | version |
|---|---:|
| Node | 22.23.1 (`/home/dev/.local/node-v22.23.1-linux-x64/bin/node`) |
| npm | 10.9.8 |
| `@earendil-works/pi-coding-agent` | **0.81.1** |
| `@earendil-works/pi-ai` | **0.81.1** |
| `typebox` | **1.1.38** |
| TypeScript | **5.9.3** |
| Vitest | **4.1.9** |

Every direct Node dependency is exact-pinned in `agent/package.json`; npm
lockfile v3 is committed as `agent/package-lock.json`. Pi requires Node
`>=22.19.0`; commands use the installed Node 22 toolchain explicitly rather
than relying on an older system installation.

Baseline, before edits:

```bash
.venv/bin/python -m pytest -q
# 61 passed in 33.87s
```

Install/build/test commands:

```bash
cd agent
/home/dev/.local/node-v22.23.1-linux-x64/bin/npm ci --ignore-scripts
/home/dev/.local/node-v22.23.1-linux-x64/bin/npm run build
PI_OFFLINE=1 /home/dev/.local/node-v22.23.1-linux-x64/bin/npm test
cd ..
.venv/bin/python -m pytest -q
```

Final results:

- Python: **64 passed in 57.26s** (all original 61 plus 3 P0 transport tests).
- TypeScript: **9 passed in 14.85s**.
- TypeScript build: **passed** with strict `tsc` settings.
- Network/API calls in the faux-provider suite: **0**.

Non-interactive standard-auth inspection (does not print credentials or start
OAuth):

```bash
cd agent
node dist/cli.js auth-check --provider anthropic --model claude-sonnet-4-6
```

Optional paid/networked smoke, using an already-authenticated vision model:

```bash
cd agent
node dist/cli.js smoke \
  --provider anthropic \
  --model claude-sonnet-4-6 \
  --problem-id circumcenter-in-triangle \
  --out-dir ../runs/pi-p0-manual-smoke
```

No automated test invokes login, reads a real credential, or calls a provider.

## Implemented architecture

```text
Pi AgentSession (TypeScript)
  ModelRuntime: built-in/custom providers + standard Pi auth
  isolated ResourceLoader: no discovered extensions/skills/prompts/context
  in-memory SettingsManager
  explicit SimAgent tool allowlist
  global + per-tool sequential execution
  Pi events / steering / JSONL conversation session tree
                 |
                 | private strict LF-delimited JSONL, one subprocess/session
                 | toolCallId unchanged; text/image result blocks
                 v
Python KernelTransport
  existing AgentRun + SandboxSession tool handlers
  append-only kernel-journal.jsonl
  state hash + prefix replay verification
  terminal finish guard
                 |
                 v
search / exact rational certification / Lean / proof.py
(the only verdict path; unchanged)
```

### Transport choice

Pi 0.81.1 intentionally has no built-in MCP client. P0 therefore does **not**
retain MCP for the new runtime and adds no MCP dependency. It uses a smaller
private JSONL subprocess bridge in `src/simagent/kernel_transport.py`.
Requests and responses are correlated independently at the protocol layer;
Pi's original `toolCallId` passes through unchanged into `transcript.jsonl`,
`trace.jsonl`, and `kernel-journal.jsonl`.

The transport wraps the existing `AgentRun`; it does not reimplement a tool,
search, proof, or verdict. Journal replay invokes the same handlers and fails
closed if any replayed state hash or error status differs.

### Full-control Pi construction

`agent/src/runtime.ts` supplies:

- an explicit no-discovery `ResourceLoader` (empty extensions, skills,
  templates, themes, and context files);
- `SettingsManager.inMemory(...)` with retry/compaction disabled for tests;
- an explicit allowlist containing only the 12 kernel tools;
- all built-in coding tools excluded from the active model tool set;
- the existing SimAgent system prompt, not Pi's coding prompt;
- Pi's default `ModelRuntime` when a test runtime is not injected;
- `session.agent.toolExecution = "sequential"` plus
  `executionMode = "sequential"` on every kernel tool.

Pi still keeps inactive built-in definitions in its internal registry, but
none appear in `AgentSession.state.tools`, the active tool list, or provider
requests. The test asserts the model-visible set exactly.

### Branch safety

A `BranchCheckpoint` is recorded only on `turn_end`, after Pi has emitted and
persisted all tool results for that assistant message. Branching is rejected
while streaming, from unknown/tampered checkpoints, from terminal checkpoints,
or without a persisted Pi session.

Pi's `SessionManager.createBranchedSession()` mutates the manager on which it
is called. The spike opens a detached copy before invoking it, preserving the
live source session. The branch starts a new Python process, replays only the
checkpoint's journal prefix, and checks the resulting hash against the source
checkpoint before exposing the branch.

## Assumption matrix

| P0 assumption | result | evidence | fallback if it fails later |
|---|---|---|---|
| Explicit kernel tools can be registered with no accidental active built-ins or discovered resources | **PASS** | faux-provider test compares the exact active/provider-visible set and empty loader resources | construct the lower-level `Agent` directly with the same `ModelRuntime` stream function |
| `look` image tool results reach the next model context | **PASS** | real Python render becomes Pi `{type:"image", data, mimeType}` and is observed by the next faux response | return an artifact path and have the TS layer attach it explicitly to the next user turn |
| One mutable world executes tool calls sequentially | **PASS** | global and per-tool modes set; sibling `set_var` then `nudge` events are strictly start/end ordered and final state includes both | serialize calls in the JSONL client and permit only one mutating call per assistant turn |
| Steering is delivered after the current tool batch | **PASS** | queued steering appears after the correlated tool result in the next faux-provider context | UI-owned queue injected as the next ordinary user turn after `turn_end` |
| `toolCallId` survives events, Pi session entries, and kernel journal | **PASS** | one fixed ID is asserted in all three records | maintain an explicit Pi-ID ↔ transport-ID map and reject uncorrelated results |
| Pi sessions persist and can branch at safe checkpoints | **PASS** | persistent session file, parent-session header, detached branch creation test | copy the active Pi path into an application-owned session file |
| Kernel journal prefix replay reproduces source world state | **PASS** | Python and TS tests compare full state and SHA-256 hash after replay | disable branch continuation and retain replay-only viewing until fixed |
| `finish` prevents later mutations, including a sibling in the same batch | **PASS** | `[finish, set_var]` yields two complete results; second is an error and coordinates are unchanged | kernel terminal flag remains authoritative; controller synthesizes matching rejected results |
| Vision can be gated using `model.input.includes("image")` | **PASS** | text-only faux model is rejected before a Python process starts | current policy is already the safe fallback: reject; a future explicit degraded mode may return status text/artifact links |
| Offline tests make no network/API calls | **PASS** | Pi faux provider plus a `fetch` stub that throws; final assertion sees zero attempts | run tests in a network-disabled container as an additional CI boundary |
| Standard Pi auth/model routing can be used without provider-specific loops | **PASS (structural/offline)** | default `ModelRuntime.create()`, `checkAuth()`, all built-in catalogs retained, and non-interactive auth-check command | keep the existing `claude-code` backend behind its current flag |
| An already-authenticated real vision provider works end to end | **NOT RUN (manual/optional)** | explicit smoke command supplied; no credential/network use was authorized in tests | existing API and `claude-code` backends remain untouched until a manual smoke passes |

No required offline assumption failed. The only unexecuted item is the
explicitly optional real-provider smoke.

## Known Pi 0.81.1 limitations and mitigations

1. **No MCP client.** Mitigation: private exact-framed JSONL bridge; no MCP
   adapter to maintain or pin.
2. **Parallel tool execution is the default, and `createAgentSession()` has no
   `toolExecution` option.** Mitigation: set the public Agent property after
   construction and mark every tool sequential as defense in depth.
3. **Images sent to a text-only model are silently ignored by pi-ai.**
   Mitigation: reject unless `model.input.includes("image")`.
4. **`createBranchedSession()` mutates its SessionManager.** Mitigation: call it
   on a detached manager loaded from the source file.
5. **Tool-batch early termination requires every result to set `terminate`.
   If `finish` follows an earlier nonterminal sibling, Pi may make one extra
   model request.** Mitigation: Python is already terminal, so every later call
   is rejected; prompt guidance asks for `finish` as the final/sole action.
6. **Pi conversation state cannot restore Python world state by itself.**
   Mitigation: dual records correlated by tool ID; branch only after verified
   journal-prefix replay.
7. **The subprocess protocol cannot cancel a Python handler midway.**
   Mitigation: sequential calls, branch/dispose only while idle, and existing
   cooperative stop semantics. A future bridge can add process-level cancel
   without changing kernel APIs.
8. **Published Pi 0.81.1's npm dependency tree contains `protobufjs` 7.6.4,
   reported by `npm audit` as moderate GHSA-j3f2-48v5-ccww.** SimAgent never
   parses `.proto` input, so the vulnerable path is outside this spike. Keep
   the lockfile, avoid untrusted proto parsing, and move the exact Pi pin to a
   release carrying 7.6.5+ when available rather than silently changing Pi's
   published shrinkwrap.
9. **Real OAuth/provider behavior is credential- and network-dependent.**
   Mitigation: use `ModelRuntime` standard locations, never automate login,
   provide a manual smoke, and retain both legacy backends during P0.

## Correctness boundary audit

- TypeScript never imports or assigns `verified_by`.
- TypeScript does not compute verdicts; finalization merely transports the
  Python result.
- `KernelTransport` delegates to `AgentRun.finalize()`, which still reaches
  `proof.py` for mechanized proof construction.
- Existing API and Claude Code backends remain present and selectable.
- Existing hardening behavior and known-answer specs are untouched.

## Deviations from `plan.md`

These are intentional consequences of the corrected P0 architecture:

1. The primary dependency is `@earendil-works/pi-coding-agent`, not a new
   provider-specific loop over only `pi-ai`/`pi-agent-core`.
2. The P0 bridge is private JSONL, not `kernel/mcp_server.py`, because Pi has no
   MCP client and P0 does not need MCP interoperability.
3. The Python package was not moved into a top-level `kernel/` tree. P0 adds a
   wrapper beside existing code to minimize blast radius; directory/core
   migration belongs to later phases.
4. Legacy `api` and `claude-code` backends and the current web job runner were
   not deleted. Their removal remains gated on later integration and real
   smoke results.
5. No P1 `Space` work, v2 atom implementation, or UI migration was started.

## Gate decision

**GO for P1.** Keep the exact Pi pins and legacy backends through the planned
compatibility window. Before P6 removes either legacy backend, run the manual
smoke with at least one already-authenticated real vision model and record the
provider result without exposing credentials.
