import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

import {
  fauxAssistantMessage,
  fauxProvider,
  fauxText,
  fauxToolCall,
  InMemoryCredentialStore,
  type Context,
  type FauxResponseStep,
} from "@earendil-works/pi-ai";
import { ModelRuntime, SessionManager } from "@earendil-works/pi-coding-agent";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import {
  assertVisionModel,
  createSimAgentRuntime,
  KERNEL_TOOL_NAMES,
  type SimAgentRuntime,
} from "../src/index.js";

const originalFetch = globalThis.fetch;
let networkAttempts = 0;
let providerSequence = 0;

beforeAll(() => {
  process.env.PI_OFFLINE = "1";
  globalThis.fetch = (async () => {
    networkAttempts += 1;
    throw new Error("network access is forbidden in P0 tests");
  }) as typeof fetch;
});

afterAll(() => {
  globalThis.fetch = originalFetch;
  delete process.env.PI_OFFLINE;
});

interface Harness {
  root: string;
  runtime: SimAgentRuntime;
  faux: ReturnType<typeof fauxProvider>;
  modelRuntime: ModelRuntime;
}

async function harness(
  responses: FauxResponseStep[] = [],
  options: {
    persistent?: boolean;
    input?: ("text" | "image")[];
    singleToolPerTurn?: boolean;
  } = {},
): Promise<Harness> {
  const root = await mkdtemp(join(tmpdir(), "simagent-p0-"));
  const provider = `simagent-faux-${++providerSequence}`;
  const faux = fauxProvider({
    provider,
    models: [{ id: "scripted", input: options.input ?? ["text", "image"] }],
  });
  faux.setResponses(responses);
  const modelRuntime = await ModelRuntime.create({
    credentials: new InMemoryCredentialStore(),
    modelsPath: null,
  });
  modelRuntime.registerNativeProvider(faux.provider);
  const model = modelRuntime.getModel(provider, "scripted");
  if (!model) throw new Error("faux model registration failed");
  const sessionManager = options.persistent
    ? SessionManager.create(process.cwd(), join(root, "sessions"))
    : SessionManager.inMemory(process.cwd());
  const runtime = await createSimAgentRuntime({
    problemId: "circumcenter-in-triangle",
    outDir: join(root, "kernel"),
    sessionManager,
    modelRuntime,
    model,
    singleToolPerTurn: options.singleToolPerTurn,
  });
  return { root, runtime, faux, modelRuntime };
}

async function cleanup(item: Harness, alreadyDisposed = false): Promise<void> {
  if (!alreadyDisposed && item.runtime.session.isIdle) {
    await item.runtime.dispose().catch(() => undefined);
  }
  await rm(item.root, { recursive: true, force: true });
}

async function journal(runtime: SimAgentRuntime): Promise<Record<string, unknown>[]> {
  const text = await readFile(runtime.kernel.description.journalPath, "utf8");
  return text
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line) as Record<string, unknown>);
}

async function journalTrace(runtime: SimAgentRuntime): Promise<Array<Record<string, any>>> {
  const text = await readFile(join(dirname(runtime.kernel.description.journalPath), "trace.jsonl"), "utf8");
  return text
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line) as Record<string, any>)
    .filter((entry) => entry.event === undefined);
}

function toolResults(context: Context) {
  return context.messages.filter((message) => message.role === "toolResult");
}

describe.sequential("Pi 0.82.0 SimAgent integration", () => {
  it("registers only explicit kernel tools with no discovered resources or active built-ins", async () => {
    const item = await harness();
    try {
      expect(item.runtime.session.agent.toolExecution).toBe("sequential");
      expect(item.runtime.session.getActiveToolNames()).toEqual(KERNEL_TOOL_NAMES);
      expect(item.runtime.session.state.tools.map((tool) => tool.name)).toEqual(KERNEL_TOOL_NAMES);
      expect(item.runtime.session.getActiveToolNames()).not.toContain("read");
      expect(item.runtime.session.getActiveToolNames()).not.toContain("bash");
      expect(item.runtime.resourceLoader.getExtensions().extensions).toEqual([]);
      expect(item.runtime.resourceLoader.getSkills().skills).toEqual([]);
      expect(item.runtime.resourceLoader.getPrompts().prompts).toEqual([]);
      expect(item.runtime.resourceLoader.getAgentsFiles().agentsFiles).toEqual([]);
      expect(item.runtime.session.systemPrompt).not.toContain("CLAUDE.md");
    } finally {
      await cleanup(item);
    }
  });

  it("delivers look image blocks to the next faux-provider context", async () => {
    let observed: Context | undefined;
    const item = await harness([
      fauxAssistantMessage(fauxToolCall("look", {}, { id: "call-look-image" }), {
        stopReason: "toolUse",
      }),
      (context) => {
        observed = JSON.parse(JSON.stringify(context)) as Context;
        return fauxAssistantMessage(fauxText("image received"));
      },
    ]);
    try {
      await item.runtime.promptTask();
      const results = toolResults(observed as Context);
      expect(results).toHaveLength(1);
      expect(results[0]?.toolCallId).toBe("call-look-image");
      expect(results[0]?.content.some((block) => block.type === "image")).toBe(true);
      const image = results[0]?.content.find((block) => block.type === "image");
      expect(image?.mimeType).toBe("image/png");
      expect(image?.data.length).toBeGreaterThan(100);
    } finally {
      await cleanup(item);
    }
  }, 30_000);

  it("executes sibling state mutations sequentially against one world", async () => {
    const item = await harness([
      fauxAssistantMessage(
        [
          fauxToolCall(
            "set_var",
            { name: "T", values: [-1, 0, 1, 0, 0, 0.2] },
            { id: "call-set" },
          ),
          fauxToolCall(
            "nudge",
            { name: "T", row: 2, delta: [0, 0.3] },
            { id: "call-nudge" },
          ),
        ],
        { stopReason: "toolUse" },
      ),
      fauxAssistantMessage(fauxText("mutations complete")),
    ]);
    const order: string[] = [];
    item.runtime.session.subscribe((event) => {
      if (event.type === "tool_execution_start") order.push(`start:${event.toolCallId}`);
      if (event.type === "tool_execution_end") order.push(`end:${event.toolCallId}`);
    });
    try {
      await item.runtime.promptTask();
      expect(order).toEqual([
        "start:call-set",
        "end:call-set",
        "start:call-nudge",
        "end:call-nudge",
      ]);
      const snapshot = await item.runtime.kernel.snapshot();
      expect(snapshot.state.vars).toEqual({ T: [[-1, 0], [1, 0], [0, 0.5]] });
    } finally {
      await cleanup(item);
    }
  });

  it("delivers steering only after the current tool batch", async () => {
    let continuation: Context | undefined;
    const item = await harness([
      fauxAssistantMessage(fauxToolCall("check", {}, { id: "call-before-steer" }), {
        stopReason: "toolUse",
      }),
      (context) => {
        continuation = JSON.parse(JSON.stringify(context)) as Context;
        return fauxAssistantMessage(fauxText("steering acknowledged"));
      },
    ]);
    let signalStarted!: () => void;
    const started = new Promise<void>((resolveStarted) => {
      signalStarted = resolveStarted;
    });
    let toolEnded = false;
    item.runtime.session.subscribe((event) => {
      if (event.type === "tool_execution_start" && event.toolCallId === "call-before-steer") {
        signalStarted();
      }
      if (event.type === "tool_execution_end" && event.toolCallId === "call-before-steer") {
        toolEnded = true;
      }
    });
    try {
      const prompting = item.runtime.promptTask();
      await started;
      await item.runtime.session.steer("Focus on the wide triangle.");
      await prompting;
      expect(toolEnded).toBe(true);
      const messages = continuation?.messages ?? [];
      const resultIndex = messages.findIndex(
        (message) => message.role === "toolResult" && message.toolCallId === "call-before-steer",
      );
      const steerIndex = messages.findIndex(
        (message) =>
          message.role === "user" &&
          JSON.stringify(message.content).includes("Focus on the wide triangle."),
      );
      expect(resultIndex).toBeGreaterThanOrEqual(0);
      expect(steerIndex).toBeGreaterThan(resultIndex);
    } finally {
      await cleanup(item);
    }
  });

  it("journals targeted steering and branches from the exact comment boundary", async () => {
    let continuation: Context | undefined;
    const item = await harness(
      [
        fauxAssistantMessage(
          [
            fauxText("I will inspect the current margin."),
            fauxToolCall(
              "set_var",
              { name: "T", values: [-1, 0, 1, 0, 0, 0.2] },
              { id: "call-comment-target" },
            ),
          ],
          { stopReason: "toolUse" },
        ),
        (context) => {
          continuation = JSON.parse(JSON.stringify(context)) as Context;
          return fauxAssistantMessage(fauxText("I will follow the user's equation hint."));
        },
      ],
      { persistent: true },
    );
    let signalStarted!: () => void;
    const started = new Promise<void>((resolveStarted) => {
      signalStarted = resolveStarted;
    });
    item.runtime.session.subscribe((event) => {
      if (event.type === "tool_execution_start" && event.toolCallId === "call-comment-target") {
        signalStarted();
      }
    });
    let branched: SimAgentRuntime | undefined;
    let disposed = false;
    try {
      const prompting = item.runtime.promptTask();
      await started;
      await item.runtime.comment("Check the sign on this line.", {
        step: 1,
        kind: "equation",
        index: 0,
      });
      await prompting;

      const commentCheckpoint = item.runtime
        .getCheckpoints()
        .find((checkpoint) => {
          if (checkpoint.kernelTraceStep !== 2) return false;
          const entry = item.runtime.session.sessionManager.getEntry(checkpoint.piEntryId);
          return entry?.type === "message" && entry.message.role === "user";
        });
      if (!commentCheckpoint) throw new Error("comment boundary checkpoint missing");
      const commentEntry = item.runtime.session.sessionManager.getEntry(commentCheckpoint.piEntryId);
      expect(commentEntry?.type).toBe("message");
      if (commentEntry?.type === "message") {
        expect(commentEntry.message.role).toBe("user");
        expect(JSON.stringify(commentEntry.message.content)).toContain("Check the sign on this line.");
      }

      branched = await item.runtime.branch(
        commentCheckpoint,
        join(item.root, "branched-from-comment"),
      );
      expect((await branched.kernel.snapshot()).traceStep).toBe(2);
      expect(JSON.stringify(branched.session.sessionManager.getEntries())).toContain(
        "Check the sign on this line.",
      );
      expect((await journalTrace(branched)).find((step) => step.kind === "user_comment")?.text).toBe(
        "Check the sign on this line.",
      );
      await branched.dispose();
      branched = undefined;

      await item.runtime.dispose();
      disposed = true;
      const messages = continuation?.messages ?? [];
      expect(
        messages.some(
          (message) =>
            message.role === "user" &&
            JSON.stringify(message.content).includes("Check the sign on this line."),
        ),
      ).toBe(true);
      const steps = await journalTrace(item.runtime);
      expect(steps.find((step) => step.kind === "user_comment")?.text).toBe(
        "Check the sign on this line.",
      );
      expect(steps.find((step) => step.tool === "set_var")?.thought?.[0]?.text).toContain(
        "inspect the current margin",
      );
      expect(steps.at(-1)?.thought?.[0]?.text).toContain("follow the user's equation hint");
    } finally {
      if (branched?.session.isIdle) await branched.dispose().catch(() => undefined);
      await cleanup(item, disposed);
    }
  });

  it("limits product sessions to one kernel action per turn", async () => {
    const item = await harness(
      [
        fauxAssistantMessage(
          [
            fauxToolCall("check", {}, { id: "single-first" }),
            fauxToolCall("sample", { seed: 9 }, { id: "single-blocked" }),
          ],
          { stopReason: "toolUse" },
        ),
        fauxAssistantMessage(fauxText("one action completed")),
      ],
      { singleToolPerTurn: true },
    );
    try {
      await item.runtime.promptTask();
      const calls = (await journal(item.runtime)).filter((entry) => entry.event === "call");
      expect(calls.map((entry) => entry.toolCallId)).toEqual(["single-first"]);
      const blocked = item.runtime.session.sessionManager.getEntries().find(
        (entry) =>
          entry.type === "message" &&
          entry.message.role === "toolResult" &&
          entry.message.toolCallId === "single-blocked",
      );
      expect(blocked?.type).toBe("message");
      if (blocked?.type === "message" && blocked.message.role === "toolResult") {
        expect(blocked.message.isError).toBe(true);
      }
      expect(item.runtime.latestCheckpoint().kernelTraceStep).toBe(1);
    } finally {
      await cleanup(item);
    }
  });

  it("preserves toolCallId across Pi events, session entries, and the kernel journal", async () => {
    const toolCallId = "correlation-id-42";
    const item = await harness([
      fauxAssistantMessage(fauxToolCall("check", {}, { id: toolCallId }), {
        stopReason: "toolUse",
      }),
      fauxAssistantMessage(fauxText("checked")),
    ]);
    const eventIds: string[] = [];
    item.runtime.session.subscribe((event) => {
      if (event.type === "tool_execution_start" || event.type === "tool_execution_end") {
        eventIds.push(event.toolCallId);
      }
    });
    try {
      await item.runtime.promptTask();
      expect(eventIds).toEqual([toolCallId, toolCallId]);
      const persisted = item.runtime.session.sessionManager
        .getEntries()
        .filter((entry) => entry.type === "message" && entry.message.role === "toolResult");
      expect(persisted).toHaveLength(1);
      if (persisted[0]?.type !== "message" || persisted[0].message.role !== "toolResult") {
        throw new Error("expected a persisted tool result");
      }
      expect(persisted[0].message.toolCallId).toBe(toolCallId);
      expect((persisted[0].message.details as { kernel: { toolCallId: string } }).kernel.toolCallId).toBe(
        toolCallId,
      );
      const call = (await journal(item.runtime)).find((entry) => entry.event === "call");
      expect(call?.toolCallId).toBe(toolCallId);
    } finally {
      await cleanup(item);
    }
  });

  it("persists Pi sessions and branches only from settled journal prefixes", async () => {
    const item = await harness(
      [
        fauxAssistantMessage(
          fauxToolCall(
            "set_var",
            { name: "T", values: [-1, 0, 1, 0, 0, 0.2] },
            { id: "branch-source-set" },
          ),
          { stopReason: "toolUse" },
        ),
        fauxAssistantMessage(fauxText("settled source branch")),
      ],
      { persistent: true },
    );
    let branched: SimAgentRuntime | undefined;
    try {
      await item.runtime.promptTask();
      expect(item.runtime.session.sessionFile).toBeTruthy();
      const checkpoint = item.runtime.latestCheckpoint();
      expect(checkpoint.settled).toBe(true);
      expect(checkpoint.safe).toBe(true);
      const source = await item.runtime.kernel.snapshot();
      await expect(
        item.runtime.branch(
          { ...checkpoint, kernelJournalSeq: checkpoint.kernelJournalSeq + 1 },
          join(item.root, "tampered-branch"),
        ),
      ).rejects.toThrow(/does not match/);

      branched = await item.runtime.branch(checkpoint, join(item.root, "branched-kernel"));
      const replayed = await branched.kernel.snapshot();
      expect(replayed.stateHash).toBe(source.stateHash);
      expect(replayed.state).toEqual(source.state);
      expect(branched.session.sessionManager.getHeader()?.parentSession).toBe(
        item.runtime.session.sessionFile,
      );
      expect(branched.session.sessionManager.getEntries().length).toBeGreaterThan(0);
      const calls = (await journal(branched)).filter((entry) => entry.event === "call");
      expect(calls.map((entry) => entry.toolCallId)).toEqual(["branch-source-set"]);
      expect(calls.at(-1)?.stateHash).toBe(checkpoint.kernelStateHash);
    } finally {
      if (branched?.session.isIdle) await branched.dispose().catch(() => undefined);
      await cleanup(item);
    }
  }, 30_000);

  it("finish rejects every later sibling mutation and leaves world coordinates unchanged", async () => {
    const item = await harness([
      fauxAssistantMessage(
        [
          fauxToolCall("finish", { summary: "done" }, { id: "call-finish" }),
          fauxToolCall(
            "set_var",
            { name: "T", values: [-1, 0, 1, 0, 0, 0.2] },
            { id: "call-after-finish" },
          ),
        ],
        { stopReason: "toolUse" },
      ),
    ]);
    try {
      const before = await item.runtime.kernel.snapshot();
      await item.runtime.promptTask();
      const after = await item.runtime.kernel.snapshot();
      expect(after.state.vars).toEqual(before.state.vars);
      expect(after.finished).toBe(true);
      const calls = (await journal(item.runtime)).filter((entry) => entry.event === "call");
      expect(calls).toHaveLength(2);
      expect(calls[1]?.toolCallId).toBe("call-after-finish");
      expect(calls[1]?.isError).toBe(true);
      expect(JSON.stringify(calls[1]?.result)).toContain("already finished");
      const laterResult = item.runtime.session.sessionManager
        .getEntries()
        .find(
          (entry) =>
            entry.type === "message" &&
            entry.message.role === "toolResult" &&
            entry.message.toolCallId === "call-after-finish",
        );
      expect(laterResult?.type).toBe("message");
      if (laterResult?.type === "message" && laterResult.message.role === "toolResult") {
        expect(laterResult.message.isError).toBe(true);
      }
      expect(item.runtime.latestCheckpoint().safe).toBe(false);
    } finally {
      await cleanup(item);
    }
  });

  it("journals a human world move under the user's name and tells the model", async () => {
    // Comments can only suggest. When the human places the point themselves the
    // record must say it was them, or the trace credits the model with a move
    // it never made.
    let observed: Context | undefined;
    const item = await harness([
      (context) => {
        observed = JSON.parse(JSON.stringify(context)) as Context;
        return fauxAssistantMessage(fauxText("noted, checking it myself"));
      },
    ]);
    try {
      const result = await item.runtime.userAction("set_var", {
        name: "T",
        values: [-1, 0, 1, 0, 0, 0.2],
      });
      expect(result.isError).toBe(false);
      expect(result.tool).toBe("set_var");

      const events = await journal(item.runtime);
      const move = events.find((entry) => entry.event === "user_action");
      expect(move).toBeDefined();
      expect(move?.tool).toBe("set_var");

      const steps = await journalTrace(item.runtime);
      expect(steps.at(-1)?.actor).toBe("user");

      // The model is told, in the same boundary, that the move was not its own.
      await item.runtime.prompt("carry on");
      const said = JSON.stringify((observed as Context).messages);
      expect(said).toContain("A human collaborator moved the world");
      expect(said).toContain("This move is theirs, not yours");
    } finally {
      await cleanup(item);
    }
  });

  it("refuses to let a human call the truth-making instruments", async () => {
    const item = await harness([fauxAssistantMessage(fauxText("idle"))]);
    try {
      await expect(item.runtime.userAction("certify", {})).rejects.toThrow(
        /not a human world move/,
      );
    } finally {
      await cleanup(item);
    }
  });

  it("rejects text-only models before starting a kernel process", async () => {
    const root = await mkdtemp(join(tmpdir(), "simagent-p0-vision-"));
    const provider = `simagent-text-${++providerSequence}`;
    const faux = fauxProvider({
      provider,
      models: [{ id: "text-only", input: ["text"] }],
    });
    const modelRuntime = await ModelRuntime.create({
      credentials: new InMemoryCredentialStore(),
      modelsPath: null,
    });
    modelRuntime.registerNativeProvider(faux.provider);
    const model = modelRuntime.getModel(provider, "text-only");
    if (!model) throw new Error("text-only faux model missing");
    expect(() => assertVisionModel(model)).toThrow(/requires a vision model/);
    await expect(
      createSimAgentRuntime({
        problemId: "circumcenter-in-triangle",
        outDir: join(root, "kernel"),
        sessionManager: SessionManager.inMemory(),
        modelRuntime,
        model,
      }),
    ).rejects.toThrow(/requires a vision model/);
    await expect(readFile(join(root, "kernel", "kernel-journal.jsonl"), "utf8")).rejects.toThrow();
    await rm(root, { recursive: true, force: true });
  });

  it("performs no network calls in the deterministic faux-provider suite", () => {
    expect(networkAttempts).toBe(0);
  });
});
