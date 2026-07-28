import { dirname, resolve } from "node:path";

import type { AssistantMessage, Model } from "@earendil-works/pi-ai";
import {
  createAgentSession,
  createExtensionRuntime,
  ModelRuntime,
  type ResourceLoader,
  SessionManager,
  SettingsManager,
  type AgentSession,
} from "@earendil-works/pi-coding-agent";

import {
  KernelClient,
  type KernelClientOptions,
  type KernelDescription,
  type KernelFinalizeResult,
  type KernelUserActionResult,
} from "./kernel-client.js";
import { createKernelTools, isKernelToolDetails, KERNEL_TOOL_NAMES } from "./tools.js";

const BUILTIN_TOOL_NAMES = ["read", "bash", "edit", "write", "grep", "find", "ls"] as const;

export class VisionCapabilityError extends Error {
  constructor(model: Model<any>) {
    super(
      `this run sends pictures, so it needs a vision model; ${model.provider}/${model.id} ` +
        `advertises input=${JSON.stringify(model.input)}. Drop --images to run it ` +
        `numbers-first, or pick a model that accepts images.`,
    );
    this.name = "VisionCapabilityError";
  }
}

export function assertVisionModel(model: Model<any>): void {
  if (!model.input.includes("image")) throw new VisionCapabilityError(model);
}

/** Resource loader with no discovery and no filesystem-backed customization. */
export function createIsolatedResourceLoader(systemPrompt: string): ResourceLoader {
  const extensions = {
    extensions: [],
    errors: [],
    runtime: createExtensionRuntime(),
  };
  return {
    getExtensions: () => extensions,
    getSkills: () => ({ skills: [], diagnostics: [] }),
    getPrompts: () => ({ prompts: [], diagnostics: [] }),
    getThemes: () => ({ themes: [], diagnostics: [] }),
    getAgentsFiles: () => ({ agentsFiles: [] }),
    getSystemPrompt: () => systemPrompt,
    getAppendSystemPrompt: () => [],
    extendResources: () => {},
    reload: async () => {},
  };
}

export interface BranchCheckpoint {
  id: string;
  piEntryId: string;
  kernelJournalSeq: number;
  kernelTraceStep: number;
  kernelStateHash: string;
  settled: true;
  safe: boolean;
}

export interface CreateSimAgentRuntimeOptions {
  problemId?: string;
  specPath?: string;
  outDir: string;
  cwd?: string;
  sessionDir?: string;
  sessionManager?: SessionManager;
  modelRuntime?: ModelRuntime;
  model?: Model<any>;
  thinkingLevel?: "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";
  pythonPath?: string;
  repoRoot?: string;
  /** Internal/public for deterministic prefix-replay tests and branch creation. */
  replayJournal?: string;
  replayThrough?: number;
  /** Continue an earlier run directory: replay it, then re-open it. This is
   * what makes a turn budget a pause rather than the end of the work. */
  adopt?: string;
  /** Product sessions use one kernel action per turn so every trace cell is branch-safe. */
  singleToolPerTurn?: boolean;
  /**
   * Send rendered pictures to the model too (default false). Numbers-first is
   * the decided default; this is the evaluation arm that turns the image
   * channel on, and it is also what makes vision a model requirement.
   */
  images?: boolean;
  /** Starting configuration seed. Two runs that differ only here are the
   * independent samples an evaluation needs; without it every seed is the
   * same experiment repeated. */
  seed?: number;
}

/**
 * Vision is required only when this run actually sends pictures. SimAgent is
 * numbers-first, so a text-only model is a normal driver; demanding vision
 * from it would reject a model that can do the whole run.
 */
async function selectModel(
  runtime: ModelRuntime,
  requested?: Model<any>,
  images = false,
): Promise<Model<any>> {
  if (requested) {
    if (images) assertVisionModel(requested);
    const auth = await runtime.checkAuth(requested.provider);
    if (auth === undefined) {
      throw new Error(`no standard Pi authentication is configured for ${requested.provider}`);
    }
    return requested;
  }
  const available = await runtime.getAvailable();
  if (!images) {
    const first = available[0];
    if (!first) throw new Error("no authenticated Pi model is available");
    return first;
  }
  const vision = available.find((candidate) => candidate.input.includes("image"));
  if (!vision) throw new Error("no authenticated Pi vision model is available");
  return vision;
}

function deterministicSettings(): SettingsManager {
  return SettingsManager.inMemory({
    compaction: { enabled: false },
    retry: { enabled: false },
    steeringMode: "one-at-a-time",
    followUpMode: "one-at-a-time",
    images: { blockImages: false, autoResize: false },
    enableInstallTelemetry: false,
  });
}

/**
 * Pi control plane paired with one Python kernel subprocess.
 *
 * Checkpoints are emitted at settled ``turn_end`` boundaries and at a
 * persisted steering-user boundary after the current tool batch. Branching
 * while the session is streaming, from a terminal state, or from an unknown
 * checkpoint is rejected.
 */
export class SimAgentRuntime {
  readonly session: AgentSession;
  readonly kernel: KernelClient;
  readonly modelRuntime: ModelRuntime;
  readonly model: Model<any>;
  readonly description: KernelDescription;
  readonly resourceLoader: ResourceLoader;

  private checkpoints: BranchCheckpoint[] = [];
  private checkpointSequence = 0;
  private readonly unsubscribe: () => void;
  private readonly narratedMessages = new WeakSet<object>();
  private narrativeQueue: Promise<void> = Promise.resolve();
  private steeringBoundary: Promise<void> = Promise.resolve();
  private readonly steeringSourceToolCalls = new Set<string>();
  private readonly activeToolCalls = new Set<string>();
  private toolBatchWaiters: Array<() => void> = [];
  private disposed = false;
  private readonly singleToolPerTurn: boolean;
  private readonly bundledProblemId: string | undefined;
  /** Whether this run's instruments send pictures; a branch must inherit it. */
  readonly images: boolean;
  /** The starting-configuration seed, so a branch replays the same world. */
  readonly seed: number;
  /**
   * Pause held open while a human works. It gates the model's NEXT tool call,
   * which is the settled boundary: the previous action is journaled and the
   * next has not started, so the human can move the world and the model's
   * first sight of it is the move itself.
   */
  private pauseGate: Promise<void> | null = null;
  private releasePause: (() => void) | null = null;
  /**
   * Tool calls parked at that gate. They are NOT part of the active batch: a
   * human action waits for the batch to drain, and a tool waiting for the
   * human to finish would then be waiting for the human, who is waiting for
   * it. Pausing would deadlock the very thing it exists to allow.
   */
  private readonly pausedToolCalls = new Set<string>();

  constructor(
    session: AgentSession,
    kernel: KernelClient,
    modelRuntime: ModelRuntime,
    model: Model<any>,
    resourceLoader: ResourceLoader,
    singleToolPerTurn: boolean,
    bundledProblemId: string | undefined,
    images = false,
    seed = 0,
  ) {
    this.images = images;
    this.seed = seed;
    this.session = session;
    this.kernel = kernel;
    this.modelRuntime = modelRuntime;
    this.model = model;
    this.description = kernel.description;
    this.resourceLoader = resourceLoader;
    this.singleToolPerTurn = singleToolPerTurn;
    this.bundledProblemId = bundledProblemId;
    this.unsubscribe = session.subscribe((event) => {
      if (event.type === "tool_execution_start") {
        this.activeToolCalls.add(event.toolCallId);
      } else if (event.type === "tool_execution_end") {
        this.activeToolCalls.delete(event.toolCallId);
        this.pausedToolCalls.delete(event.toolCallId);
        this.releaseToolBatchWaiters();
      } else if (event.type === "turn_end") {
        void this.flushAssistantNarrative(event.message).then(() => this.recordCheckpoint());
      }
    });
    this.installBeforeToolHook();
  }

  private flushAssistantNarrative(message: unknown): Promise<void> {
    if (typeof message !== "object" || message === null || this.narratedMessages.has(message)) {
      return this.narrativeQueue;
    }
    const assistant = message as AssistantMessage;
    if (assistant.role !== "assistant" || !Array.isArray(assistant.content)) {
      return this.narrativeQueue;
    }
    this.narratedMessages.add(message);
    const blocks: Array<{ kind: "text" | "thinking"; text: string }> = [];
    for (const block of assistant.content) {
      if (block.type === "thinking" && block.thinking.trim()) {
        blocks.push({ kind: "thinking", text: block.thinking });
      } else if (block.type === "text" && block.text.trim()) {
        blocks.push({ kind: "text", text: block.text });
      }
    }
    for (const block of blocks) {
      this.narrativeQueue = this.narrativeQueue.then(async () => {
        await this.kernel.noteThought(block.text, block.kind);
      });
    }
    return this.narrativeQueue;
  }

  private installBeforeToolHook(): void {
    const inherited = this.session.agent.beforeToolCall;
    this.session.agent.beforeToolCall = async (context, signal) => {
      // A comment can arrive after tool_execution_start but before this hook.
      // That current tool must finish to reach the comment boundary; only a
      // later tool waits for the annotation to be persisted.
      if (!this.steeringSourceToolCalls.has(context.toolCall.id)) {
        await this.steeringBoundary;
      }
      // The pause boundary: the previous action is journaled, this one has not
      // touched the kernel yet. Park here, and release the batch so a human
      // move can reach the kernel while the model waits.
      while (this.pauseGate) {
        const gate = this.pauseGate;
        this.pausedToolCalls.add(context.toolCall.id);
        this.releaseToolBatchWaiters();
        await gate;
      }
      this.pausedToolCalls.delete(context.toolCall.id);
      await this.flushAssistantNarrative(context.assistantMessage);
      const inheritedResult = await inherited?.(context, signal);
      if (inheritedResult?.block || !this.singleToolPerTurn) return inheritedResult;
      const first = context.assistantMessage.content.find((block) => block.type === "toolCall");
      if (first?.type === "toolCall" && first.id !== context.toolCall.id) {
        return {
          block: true,
          reason: "SimAgent accepts one world action per turn so every notebook cell is branch-safe; reissue this action next turn.",
        };
      }
      return inheritedResult;
    };
  }

  private recordCheckpoint(entryId?: string): void {
    const piEntryId = entryId ?? this.session.sessionManager.getLeafId();
    if (!piEntryId) return;
    const previous = this.checkpoints.at(-1);
    if (
      previous?.piEntryId === piEntryId &&
      previous.kernelJournalSeq === this.kernel.tip.journalSeq
    ) {
      return;
    }
    this.checkpoints.push({
      id: `checkpoint-${++this.checkpointSequence}`,
      piEntryId,
      kernelJournalSeq: this.kernel.tip.journalSeq,
      kernelTraceStep: this.kernel.tip.traceStep,
      kernelStateHash: this.kernel.tip.stateHash,
      settled: true,
      safe: !this.kernel.tip.finished,
    });
  }

  getCheckpoints(): readonly BranchCheckpoint[] {
    return this.checkpoints.map((checkpoint) => ({ ...checkpoint }));
  }

  latestCheckpoint(): BranchCheckpoint {
    const checkpoint = this.checkpoints.at(-1);
    if (!checkpoint) throw new Error("session has no settled branch checkpoint");
    return { ...checkpoint };
  }

  captureCheckpoint(): BranchCheckpoint {
    if (!this.session.isIdle) throw new Error("a checkpoint requires an idle pi session");
    this.recordCheckpoint();
    return this.latestCheckpoint();
  }

  async prompt(text: string): Promise<void> {
    await this.session.prompt(text, { expandPromptTemplates: false });
    await this.narrativeQueue;
    this.recordCheckpoint();
  }

  async promptTask(): Promise<void> {
    await this.prompt(this.description.taskPrompt);
  }

  async branch(checkpoint: BranchCheckpoint, outDir: string): Promise<SimAgentRuntime> {
    if (!this.session.isIdle) throw new Error("branching is allowed only after the current Pi run settles");
    const known = this.checkpoints.find((candidate) => candidate.id === checkpoint.id);
    if (!known) throw new Error(`unknown branch checkpoint ${checkpoint.id}`);
    if (
      known.piEntryId !== checkpoint.piEntryId ||
      known.kernelJournalSeq !== checkpoint.kernelJournalSeq ||
      known.kernelTraceStep !== checkpoint.kernelTraceStep ||
      known.kernelStateHash !== checkpoint.kernelStateHash
    ) {
      throw new Error("branch checkpoint metadata does not match this session");
    }
    if (!known.safe) throw new Error("cannot branch a terminal kernel checkpoint");
    if (!this.session.sessionManager.isPersisted()) {
      throw new Error("Pi session persistence is required for branch creation");
    }
    const sourceSessionFile = this.session.sessionFile;
    if (!sourceSessionFile) throw new Error("persisted Pi session has no session file");
    // SessionManager.createBranchedSession() replaces the manager it is called
    // on. Use a detached manager so the live source session remains untouched.
    const detachedSource = SessionManager.open(sourceSessionFile);
    const branchFile = detachedSource.createBranchedSession(known.piEntryId);
    if (!branchFile) throw new Error("Pi did not create a branched session file");
    const branchModel = this.session.model;
    if (!branchModel) throw new Error("source Pi session has no active model");
    if (this.images) assertVisionModel(branchModel);

    const branchOptions: CreateSimAgentRuntimeOptions = {
      outDir,
      cwd: this.session.sessionManager.getCwd(),
      sessionManager: SessionManager.open(branchFile),
      modelRuntime: this.modelRuntime,
      model: branchModel,
      thinkingLevel: this.session.thinkingLevel,
      repoRoot: this.kernel.repoRoot,
      pythonPath: this.kernel.pythonPath,
      replayJournal: this.kernel.tip.journalPath,
      replayThrough: known.kernelJournalSeq,
      singleToolPerTurn: this.singleToolPerTurn,
      images: this.images,
      seed: this.seed,
    };
    if (this.bundledProblemId !== undefined) branchOptions.problemId = this.bundledProblemId;
    else branchOptions.specPath = resolve(dirname(this.kernel.tip.journalPath), "spec.json");
    const branched = await createSimAgentRuntime(branchOptions);
    if (branched.kernel.tip.stateHash !== known.kernelStateHash) {
      await branched.dispose();
      throw new Error("branched kernel state does not match the source checkpoint");
    }
    return branched;
  }

  private waitForToolBatch(): Promise<void> {
    if (this.pendingToolCount() === 0) return Promise.resolve();
    return new Promise((resolveWaiter) => this.toolBatchWaiters.push(resolveWaiter));
  }

  private releaseToolBatchWaiters(): void {
    if (this.pendingToolCount() !== 0) return;
    const waiters = this.toolBatchWaiters;
    this.toolBatchWaiters = [];
    for (const resolveWaiter of waiters) resolveWaiter();
  }

  /** Active tools that are actually running, not parked at the pause gate. */
  private pendingToolCount(): number {
    let count = 0;
    for (const id of this.activeToolCalls) {
      if (!this.pausedToolCalls.has(id)) count += 1;
    }
    return count;
  }

  /** True while the model is held at a settled boundary. */
  get paused(): boolean {
    return this.pauseGate !== null;
  }

  /**
   * Hold the model before its next action. Already-running tools finish, so
   * the kernel is never left mid-write; what stops is the model taking a NEW
   * step, which is what a human needs in order to work on a settled state.
   */
  pause(): void {
    if (this.pauseGate) return;
    this.pauseGate = new Promise<void>((release) => {
      this.releasePause = release;
    });
  }

  resume(): void {
    const release = this.releasePause;
    this.pauseGate = null;
    this.releasePause = null;
    release?.();
    // A tool parked at the gate rejoins the batch; anyone waiting for the
    // batch to drain must now wait for it again.
    this.pausedToolCalls.clear();
  }

  async comment(text: string, target: Record<string, unknown>): Promise<void> {
    if (!this.session.isStreaming) throw new Error("comments can steer only a running pi session");
    if (this.kernel.tip.finished) throw new Error("cannot comment on a finished kernel session");
    const clean = text.trim();
    if (!clean) throw new Error("comment text must be non-empty");
    const batch = this.waitForToolBatch();
    const sourceToolCalls = [...this.activeToolCalls];
    const existingEntries = new Set(
      this.session.sessionManager.getEntries().map((entry) => entry.id),
    );
    const steeringText =
      `User comment on ${JSON.stringify(target)}:\n${clean}\n` +
      "Treat this as steering only; use kernel tools for every conclusion.";
    for (const toolCallId of sourceToolCalls) this.steeringSourceToolCalls.add(toolCallId);
    const queued = this.session.steer(steeringText);
    const boundary = this.steeringBoundary.then(async () => {
      await queued;
      await batch;
      if (this.kernel.tip.finished) throw new Error("the kernel finished before the comment boundary");
      await this.kernel.annotate("user_comment", { text: clean, target });
      const findSteeringEntry = () =>
        [...this.session.sessionManager.getBranch()].reverse().find((entry) => {
          if (existingEntries.has(entry.id) || entry.type !== "message") return false;
          if (entry.message.role !== "user") return false;
          const content = entry.message.content;
          if (typeof content === "string") return content === steeringText;
          return content.some((block) => block.type === "text" && block.text === steeringText);
        });
      let steeringEntry = findSteeringEntry();
      for (let attempt = 0; steeringEntry === undefined && attempt < 100; attempt += 1) {
        await new Promise((resolveWait) => setTimeout(resolveWait, 10));
        steeringEntry = findSteeringEntry();
      }
      if (!steeringEntry) {
        throw new Error("Pi did not persist the steering user boundary");
      }
      this.recordCheckpoint(steeringEntry.id);
    });
    this.steeringBoundary = boundary
      .catch(() => undefined)
      .finally(() => {
        for (const toolCallId of sourceToolCalls) this.steeringSourceToolCalls.delete(toolCallId);
      });
    await boundary;
  }

  /**
   * Let the human move the world mid-run, and tell the model it happened.
   *
   * Comments can only suggest; sometimes the collaborator has to just place
   * the point. The kernel journals the move under the user's name, and the
   * model is told in the same boundary so it never mistakes the new
   * configuration for one of its own.
   */
  async userAction(tool: string, args: Record<string, unknown>): Promise<KernelUserActionResult> {
    if (this.kernel.tip.finished) throw new Error("cannot act on a finished kernel session");
    const batch = this.waitForToolBatch();
    const sourceToolCalls = [...this.activeToolCalls];
    for (const toolCallId of sourceToolCalls) this.steeringSourceToolCalls.add(toolCallId);
    const boundary = this.steeringBoundary.then(async () => {
      await batch;
      if (this.kernel.tip.finished) throw new Error("the kernel finished before the action boundary");
      const result = await this.kernel.userAction(tool, args);
      const reported = result.content
        .filter((block): block is Extract<typeof block, { type: "text" }> => block.type === "text")
        .map((block) => block.text)
        .join("\n");
      const notice =
        `A human collaborator moved the world: ${tool}(${JSON.stringify(args)}).\n` +
        `Kernel result: ${reported}\n` +
        "This move is theirs, not yours. Check it rather than assuming it is right.";
      if (this.session.isStreaming) {
        await this.session.steer(notice);
      } else {
        await this.session.sendCustomMessage(
          {
            customType: "simagent-user-action",
            content: notice,
            display: true,
            details: { tool, args },
          },
          { triggerTurn: false },
        );
      }
      return result;
    });
    this.steeringBoundary = boundary
      .then(() => undefined)
      .catch(() => undefined)
      .finally(() => {
        for (const toolCallId of sourceToolCalls) this.steeringSourceToolCalls.delete(toolCallId);
      });
    return boundary;
  }

  async seedComment(text: string, target: Record<string, unknown>): Promise<void> {
    if (!this.session.isIdle) throw new Error("a branch comment requires an idle pi session");
    const clean = text.trim();
    if (!clean) throw new Error("comment text must be non-empty");
    await this.kernel.annotate("user_comment", { text: clean, target });
    await this.session.sendCustomMessage(
      {
        customType: "simagent-user-comment",
        content: `User steering comment on ${JSON.stringify(target)}:\n${clean}`,
        display: true,
        details: { target },
      },
      { triggerTurn: false },
    );
  }

  async annotateProvenance(payload: Record<string, unknown>): Promise<void> {
    await this.kernel.annotate("provenance", payload);
  }

  async stop(summary = "session stopped by the user"): Promise<void> {
    if (!this.kernel.tip.finished) await this.kernel.stop(summary);
    if (!this.session.isIdle) await this.session.abort();
  }

  async dispose(): Promise<KernelFinalizeResult> {
    if (this.disposed) throw new Error("SimAgent runtime is already disposed");
    if (!this.session.isIdle) throw new Error("cannot dispose while Pi is streaming");
    await this.steeringBoundary;
    await this.narrativeQueue;
    this.disposed = true;
    this.unsubscribe();
    this.session.dispose();
    try {
      return await this.kernel.close();
    } catch (error) {
      await this.kernel.terminate();
      throw error;
    }
  }
}

export async function createSimAgentRuntime(
  options: CreateSimAgentRuntimeOptions,
): Promise<SimAgentRuntime> {
  const cwd = resolve(options.cwd ?? options.repoRoot ?? process.cwd());
  // Default construction deliberately uses Pi's standard auth/models locations.
  const modelRuntime = options.modelRuntime ?? (await ModelRuntime.create());
  const images = options.images === true;
  const model = await selectModel(modelRuntime, options.model, images);

  if ((options.problemId === undefined) === (options.specPath === undefined)) {
    throw new Error("provide exactly one of problemId or specPath");
  }
  const kernelOptions: KernelClientOptions = { outDir: options.outDir };
  if (options.problemId !== undefined) kernelOptions.problemId = options.problemId;
  if (options.specPath !== undefined) kernelOptions.specPath = options.specPath;
  if (options.pythonPath !== undefined) kernelOptions.pythonPath = options.pythonPath;
  if (options.repoRoot !== undefined) kernelOptions.repoRoot = options.repoRoot;
  if (options.replayJournal !== undefined) kernelOptions.replayJournal = options.replayJournal;
  if (options.replayThrough !== undefined) kernelOptions.replayThrough = options.replayThrough;
  if (options.adopt !== undefined) kernelOptions.adopt = options.adopt;
  if (images) kernelOptions.images = true;
  if (options.seed !== undefined) kernelOptions.seed = options.seed;
  const kernel = await KernelClient.start(kernelOptions);

  try {
    const resourceLoader = createIsolatedResourceLoader(kernel.description.systemPrompt);
    const settingsManager = deterministicSettings();
    const sessionManager =
      options.sessionManager ??
      (options.sessionDir === undefined
        ? SessionManager.create(cwd)
        : SessionManager.create(cwd, resolve(options.sessionDir)));
    const customTools = createKernelTools(kernel);
    const { session } = await createAgentSession({
      cwd,
      model,
      thinkingLevel: options.thinkingLevel ?? "off",
      modelRuntime,
      resourceLoader,
      customTools,
      tools: [...KERNEL_TOOL_NAMES],
      excludeTools: [...BUILTIN_TOOL_NAMES],
      sessionManager,
      settingsManager,
    });

    // Pi defaults to parallel execution. The kernel owns one mutable world,
    // so force both the global loop and every individual tool to be
    // sequential (the latter is set in createKernelTools()).
    session.agent.toolExecution = "sequential";

    // Put the model on the record. SimAgent harnesses whatever model pi
    // routes, so a run is only attributable and comparable if it says which
    // one produced it; without this the only trace lives outside the run dir.
    await kernel.setRuntime({
      provider: model.provider,
      model: model.id,
      thinkingLevel: options.thinkingLevel ?? "off",
    });

    // Tool implementations return kernel error metadata instead of throwing so
    // image/text blocks and terminal hints survive. Convert that metadata into
    // Pi's canonical isError flag in the post-tool hook.
    const inheritedAfterToolCall = session.agent.afterToolCall;
    session.agent.afterToolCall = async (context, signal) => {
      const inherited = await inheritedAfterToolCall?.(context, signal);
      const details = inherited?.details ?? context.result.details;
      if (!isKernelToolDetails(details)) return inherited;
      return {
        ...inherited,
        details,
        isError: details.kernel.isError || inherited?.isError === true,
        terminate: details.kernel.finished || inherited?.terminate === true,
      };
    };

    const active = session.getActiveToolNames();
    const accidental = active.filter((name) => !KERNEL_TOOL_NAMES.includes(name));
    if (accidental.length > 0 || active.length !== KERNEL_TOOL_NAMES.length) {
      session.dispose();
      throw new Error(`Pi exposed an unexpected tool set: ${active.join(", ")}`);
    }
    return new SimAgentRuntime(
      session,
      kernel,
      modelRuntime,
      model,
      resourceLoader,
      options.singleToolPerTurn ?? false,
      options.problemId,
      images,
      options.seed ?? 0,
    );
  } catch (error) {
    await kernel.terminate();
    throw error;
  }
}
