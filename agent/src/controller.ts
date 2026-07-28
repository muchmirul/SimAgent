import { existsSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

import type { Model } from "@earendil-works/pi-ai";
import { ModelRuntime } from "@earendil-works/pi-coding-agent";

import {
  createSimAgentRuntime,
  type BranchCheckpoint,
  type CreateSimAgentRuntimeOptions,
  type SimAgentRuntime,
} from "./runtime.js";
import type { KernelFinalizeResult } from "./kernel-client.js";
import {
  structured,
  type StructuredRequest,
  type StructuredResult,
} from "./structured.js";

export type ManagedRunStatus = "running" | "stopping" | "stopped" | "done" | "failed";

export interface StartRunRequest {
  problemId?: string;
  specPath?: string;
  provider?: string;
  model?: string;
  thinkingLevel?: CreateSimAgentRuntimeOptions["thinkingLevel"];
  maxTurns?: number;
  runBase?: string;
  /** Send pictures to the model too. Default false: numbers-first. */
  images?: boolean;
}

export interface CommentRequest {
  text: string;
  target: Record<string, unknown>;
}

export interface UserActionRequest {
  tool: string;
  args: Record<string, unknown>;
}

export interface BranchRunRequest {
  step: number;
  comment?: string;
  target?: Record<string, unknown>;
}

export interface ControllerEvent {
  seq: number;
  type: string;
  data: Record<string, unknown>;
}

export interface RunStatusView {
  run: string;
  status: ManagedRunStatus;
  title: string;
  turns: number;
  log: string[];
  error: string | null;
  proof: { method: string; verified_by: string } | null;
  checkpoints: BranchCheckpoint[];
  /** True while the model is held at a settled boundary for a human to work. */
  paused: boolean;
}

export class ControllerError extends Error {
  constructor(
    readonly code: "BUSY" | "NOT_FOUND" | "CONFLICT" | "VALIDATION",
    message: string,
  ) {
    super(message);
    this.name = "ControllerError";
  }
}

interface ManagedRun {
  name: string;
  status: ManagedRunStatus;
  title: string;
  turns: number;
  maxTurns: number;
  log: string[];
  error: string | null;
  proof: RunStatusView["proof"];
  runtime: SimAgentRuntime;
  finalized?: KernelFinalizeResult;
  stopRequested: boolean;
  stopOperation?: Promise<void>;
  events: ControllerEvent[];
  eventSeq: number;
  settled: Promise<void>;
}

export interface RunControllerOptions {
  runsRoot: string;
  cwd?: string;
  repoRoot?: string;
  pythonPath?: string;
  sessionDir?: string;
  modelRuntime?: ModelRuntime;
  runtimeFactory?: (options: CreateSimAgentRuntimeOptions) => Promise<SimAgentRuntime>;
}

function cleanRunPart(value: string): string {
  const clean = value.toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "");
  return clean || "session";
}

function proofView(value: unknown): RunStatusView["proof"] {
  if (typeof value !== "object" || value === null) return null;
  const proof = value as Record<string, unknown>;
  let method = String(proof.method ?? "");
  if (method.startsWith("Method.")) method = method.slice("Method.".length).toLowerCase();
  const verified = String(proof.verified_by ?? proof.verifiedBy ?? "");
  if (!method || !verified) return null;
  return { method, verified_by: verified };
}

export class RunController {
  private readonly runsRoot: string;
  private readonly cwd: string;
  private readonly repoRoot: string | undefined;
  private readonly pythonPath: string | undefined;
  private readonly sessionDir: string | undefined;
  private readonly runtimeFactory: (options: CreateSimAgentRuntimeOptions) => Promise<SimAgentRuntime>;
  private modelRuntime: ModelRuntime | undefined;
  private readonly runs = new Map<string, ManagedRun>();
  private creatingRun = false;

  constructor(options: RunControllerOptions) {
    this.runsRoot = resolve(options.runsRoot);
    this.cwd = resolve(options.cwd ?? options.repoRoot ?? process.cwd());
    this.repoRoot = options.repoRoot === undefined ? undefined : resolve(options.repoRoot);
    this.pythonPath = options.pythonPath === undefined ? undefined : resolve(options.pythonPath);
    this.sessionDir = options.sessionDir === undefined ? undefined : resolve(options.sessionDir);
    this.modelRuntime = options.modelRuntime;
    this.runtimeFactory = options.runtimeFactory ?? createSimAgentRuntime;
  }

  private active(): ManagedRun | undefined {
    return [...this.runs.values()].find((run) => run.status === "running" || run.status === "stopping");
  }

  private allocate(base: string): string {
    const stem = cleanRunPart(base);
    let name = stem;
    let suffix = 1;
    while (this.runs.has(name) || existsSync(resolve(this.runsRoot, name))) {
      name = `${stem}-${++suffix}`;
    }
    return name;
  }

  private pushEvent(run: ManagedRun, type: string, data: Record<string, unknown> = {}): void {
    run.events.push({ seq: ++run.eventSeq, type, data });
    if (run.events.length > 500) run.events.splice(0, run.events.length - 500);
  }

  private log(run: ManagedRun, text: string): void {
    run.log.push(text.slice(0, 300));
    if (run.log.length > 30) run.log.splice(0, run.log.length - 30);
    this.pushEvent(run, "log", { text: text.slice(0, 300) });
  }

  private async getModelRuntime(): Promise<ModelRuntime> {
    this.modelRuntime ??= await ModelRuntime.create();
    return this.modelRuntime;
  }

  private async resolveModel(provider?: string, modelId?: string): Promise<{
    modelRuntime?: ModelRuntime;
    model?: Model<any>;
  }> {
    if (provider === undefined && modelId === undefined) return {};
    const runtime = await this.getModelRuntime();
    let model: Model<any> | undefined;
    if (provider !== undefined && modelId !== undefined) {
      model = runtime.getModel(provider, modelId);
    } else {
      const available = await runtime.getAvailable();
      model = available.find(
        (candidate) =>
          (provider === undefined || candidate.provider === provider) &&
          (modelId === undefined || candidate.id === modelId),
      );
    }
    if (!model) {
      throw new ControllerError(
        "VALIDATION",
        `pi model not found or not authenticated: ${provider ?? "*"}/${modelId ?? "*"}`,
      );
    }
    if (!model.input.includes("image")) {
      throw new ControllerError("VALIDATION", `${model.provider}/${model.id} has no image input`);
    }
    return { modelRuntime: runtime, model };
  }

  private bindEvents(run: ManagedRun): void {
    run.runtime.session.subscribe((event) => {
      if (event.type === "turn_end") {
        run.turns += 1;
        this.pushEvent(run, "turn_end", {
          turns: run.turns,
          journalSeq: run.runtime.kernel.tip.journalSeq,
          traceStep: run.runtime.kernel.tip.traceStep,
          stateHash: run.runtime.kernel.tip.stateHash,
        });
        if (run.turns >= run.maxTurns && !run.stopRequested) {
          run.stopRequested = true;
          run.status = "stopping";
          this.log(run, `maximum turn count reached (${run.maxTurns})`);
          run.stopOperation = run.runtime
            .stop(`maximum turn count reached (${run.maxTurns})`)
            .catch(() => undefined);
        }
      } else if (event.type === "tool_execution_start") {
        this.log(run, `[tool] ${event.toolName}`);
        this.pushEvent(run, "tool_start", {
          toolCallId: event.toolCallId,
          tool: event.toolName,
        });
      } else if (event.type === "tool_execution_end") {
        this.pushEvent(run, "tool_end", {
          toolCallId: event.toolCallId,
          tool: event.toolName,
          error: event.isError,
        });
      } else if (event.type === "message_end" && event.message.role === "assistant") {
        const text = event.message.content
          .filter((block) => block.type === "text")
          .map((block) => (block.type === "text" ? block.text : ""))
          .join("\n")
          .trim();
        if (text) this.log(run, `[agent] ${text}`);
      } else if (event.type === "queue_update") {
        this.pushEvent(run, "queue", {
          steering: event.steering.length,
          followUp: event.followUp.length,
        });
      }
    });
  }

  private drive(run: ManagedRun, prompt: string | undefined): Promise<void> {
    return (async () => {
      try {
        if (prompt === undefined) await run.runtime.promptTask();
        else await run.runtime.prompt(prompt);
      } catch (error) {
        if (!run.stopRequested) {
          run.error = error instanceof Error ? error.message : String(error);
          this.log(run, `[error] ${run.error}`);
        }
      }
      try {
        if (run.stopOperation) {
          await run.stopOperation.catch((error: unknown) => {
            run.error ??= error instanceof Error ? error.message : String(error);
          });
        }
        if (!run.runtime.session.isIdle) await run.runtime.stop();
        run.finalized = await run.runtime.dispose();
        run.proof = proofView(run.finalized.proof);
      } catch (error) {
        run.error ??= error instanceof Error ? error.message : String(error);
        await run.runtime.kernel.terminate().catch(() => undefined);
      }
      run.status = run.error ? "failed" : run.stopRequested ? "stopped" : "done";
      this.pushEvent(run, run.status, {
        proof: run.proof,
        error: run.error,
      });
    })();
  }

  async start(request: StartRunRequest): Promise<{ run: string }> {
    if ((request.problemId === undefined) === (request.specPath === undefined)) {
      throw new ControllerError("VALIDATION", "provide exactly one of problemId or specPath");
    }
    const active = this.active();
    if (active || this.creatingRun) {
      throw new ControllerError(
        "BUSY",
        active ? `an agent session is already running (${active.name})` : "an agent session is starting",
      );
    }
    this.creatingRun = true;
    try {
      const maxTurns = Math.max(1, Math.min(request.maxTurns ?? 40, 200));
      const base = request.runBase ?? `agent-${request.problemId ?? "conjecture"}`;
      const name = this.allocate(base);
      const outDir = resolve(this.runsRoot, name);
      await mkdir(this.runsRoot, { recursive: true });
      const selected = await this.resolveModel(request.provider, request.model);
      const runtimeOptions: CreateSimAgentRuntimeOptions = {
        outDir,
        cwd: this.cwd,
        thinkingLevel: request.thinkingLevel ?? "medium",
        singleToolPerTurn: true,
        images: request.images === true,
      };
      if (request.problemId !== undefined) runtimeOptions.problemId = request.problemId;
      if (request.specPath !== undefined) runtimeOptions.specPath = request.specPath;
      if (this.repoRoot !== undefined) runtimeOptions.repoRoot = this.repoRoot;
      if (this.pythonPath !== undefined) runtimeOptions.pythonPath = this.pythonPath;
      if (this.sessionDir !== undefined) runtimeOptions.sessionDir = this.sessionDir;
      if (selected.modelRuntime !== undefined) runtimeOptions.modelRuntime = selected.modelRuntime;
      if (selected.model !== undefined) runtimeOptions.model = selected.model;
      const runtime = await this.runtimeFactory(runtimeOptions);
      const run: ManagedRun = {
        name,
        status: "running",
        title: runtime.description.title,
        turns: 0,
        maxTurns,
        log: [],
        error: null,
        proof: null,
        runtime,
        stopRequested: false,
        events: [],
        eventSeq: 0,
        settled: Promise.resolve(),
      };
      this.runs.set(name, run);
      this.bindEvents(run);
      this.pushEvent(run, "started", {
        provider: runtime.model.provider,
        model: runtime.model.id,
        specId: runtime.description.specId,
      });
      run.settled = this.drive(run, undefined);
      return { run: name };
    } finally {
      this.creatingRun = false;
    }
  }

  status(name: string): RunStatusView {
    const run = this.runs.get(name);
    if (!run) throw new ControllerError("NOT_FOUND", "unknown agent job");
    return {
      run: run.name,
      status: run.status,
      title: run.title,
      turns: run.turns,
      log: [...run.log],
      error: run.error,
      proof: run.proof,
      checkpoints: [...run.runtime.getCheckpoints()],
      paused: run.runtime.paused,
    };
  }

  events(name: string, after = 0): { events: ControllerEvent[]; total: number } {
    const run = this.runs.get(name);
    if (!run) throw new ControllerError("NOT_FOUND", "unknown agent job");
    return {
      events: run.events.filter((event) => event.seq > after),
      total: run.eventSeq,
    };
  }

  async comment(name: string, request: CommentRequest): Promise<{ run: string; status: string }> {
    const run = this.runs.get(name);
    if (!run) throw new ControllerError("NOT_FOUND", "unknown agent job");
    if (run.status !== "running" || !run.runtime.session.isStreaming) {
      throw new ControllerError("CONFLICT", `session is not accepting steering (status: ${run.status})`);
    }
    try {
      await run.runtime.comment(request.text, request.target);
    } catch (error) {
      throw new ControllerError(
        "CONFLICT",
        error instanceof Error ? error.message : String(error),
      );
    }
    this.pushEvent(run, "comment", { target: request.target });
    return { run: name, status: "queued" };
  }

  /** The human's own move in the world, on the record and shown to the model. */
  async userAction(
    name: string,
    request: UserActionRequest,
  ): Promise<{ run: string; tool: string; traceStep: number; isError: boolean }> {
    const run = this.runs.get(name);
    if (!run) throw new ControllerError("NOT_FOUND", "unknown agent job");
    if (run.status !== "running") {
      throw new ControllerError("CONFLICT", `session is not accepting moves (status: ${run.status})`);
    }
    let result;
    try {
      result = await run.runtime.userAction(request.tool, request.args);
    } catch (error) {
      throw new ControllerError(
        "CONFLICT",
        error instanceof Error ? error.message : String(error),
      );
    }
    this.pushEvent(run, "user_action", { tool: request.tool, args: request.args });
    return {
      run: name,
      tool: result.tool,
      traceStep: result.traceStep,
      isError: result.isError,
    };
  }

  /**
   * Hold the model at its next settled boundary so a human can work on the
   * state. Running tools finish; only a NEW model action waits. Human moves
   * and comments still go through, which is the point of pausing.
   */
  pause(name: string): { run: string; paused: boolean } {
    const run = this.runs.get(name);
    if (!run) throw new ControllerError("NOT_FOUND", "unknown agent job");
    if (run.status !== "running") {
      throw new ControllerError("CONFLICT", `session is not running (status: ${run.status})`);
    }
    run.runtime.pause();
    this.pushEvent(run, "paused");
    return { run: name, paused: true };
  }

  resume(name: string): { run: string; paused: boolean } {
    const run = this.runs.get(name);
    if (!run) throw new ControllerError("NOT_FOUND", "unknown agent job");
    run.runtime.resume();
    this.pushEvent(run, "resumed");
    return { run: name, paused: false };
  }

  async stop(name: string): Promise<{ run: string; status: string }> {
    const run = this.runs.get(name);
    if (!run) throw new ControllerError("NOT_FOUND", "unknown agent job");
    if (run.status !== "running") {
      throw new ControllerError("CONFLICT", `session is not running (status: ${run.status})`);
    }
    run.stopRequested = true;
    run.status = "stopping";
    this.pushEvent(run, "stopping");
    run.stopOperation = run.runtime.stop();
    await run.stopOperation;
    return { run: name, status: "stopping" };
  }

  async branch(name: string, request: BranchRunRequest): Promise<{ run: string }> {
    const source = this.runs.get(name);
    if (!source) throw new ControllerError("NOT_FOUND", "unknown agent job");
    if (!Number.isInteger(request.step) || request.step < 0) {
      throw new ControllerError("VALIDATION", "branch step must be a non-negative integer");
    }
    const other = this.active();
    if ((other && other !== source) || this.creatingRun) {
      throw new ControllerError(
        "BUSY",
        other && other !== source
          ? `an agent session is already running (${other.name})`
          : "another agent session is being created",
      );
    }
    this.creatingRun = true;
    let orphan: SimAgentRuntime | undefined;
    try {
      if (source.status === "running") {
        await this.stop(source.name);
        await source.settled;
      } else if (source.status === "stopping") {
        await source.settled;
      }
      const exactCheckpoints = source.runtime
        .getCheckpoints()
        .filter((candidate) => candidate.safe && candidate.kernelTraceStep === request.step);
      const checkpoint =
        exactCheckpoints.find((candidate) => {
          const entry = source.runtime.session.sessionManager.getEntry(candidate.piEntryId);
          return entry?.type === "message" && entry.message.role === "user";
        }) ?? exactCheckpoints[0];
      if (!checkpoint) {
        throw new ControllerError(
          "CONFLICT",
          `step ${request.step} has no exact safe pi checkpoint`,
        );
      }
      const branchName = this.allocate(`branch-${source.name}-step-${request.step}`);
      const branched = await source.runtime.branch(
        checkpoint,
        resolve(this.runsRoot, branchName),
      );
      orphan = branched;
      await branched.annotateProvenance({
        source: {
          run: source.name,
          requestedStep: request.step,
          step: checkpoint.kernelTraceStep,
          journalSeq: checkpoint.kernelJournalSeq,
          stateHash: checkpoint.kernelStateHash,
        },
      });
      const cleanComment = request.comment?.trim();
      const target = request.target ?? { step: request.step, kind: "cell" };
      if (cleanComment) await branched.seedComment(cleanComment, target);
      branched.captureCheckpoint();
      const run: ManagedRun = {
        name: branchName,
        status: "running",
        title: source.title,
        turns: 0,
        maxTurns: source.maxTurns,
        log: [],
        error: null,
        proof: null,
        runtime: branched,
        stopRequested: false,
        events: [],
        eventSeq: 0,
        settled: Promise.resolve(),
      };
      this.runs.set(branchName, run);
      orphan = undefined;
      this.bindEvents(run);
      this.pushEvent(run, "branched", {
        sourceRun: source.name,
        sourceStep: checkpoint.kernelTraceStep,
        stateHash: checkpoint.kernelStateHash,
      });
      const prompt = `Continue solving from the exact state at ${source.name} step ${checkpoint.kernelTraceStep}. Reassess the scene, incorporate any user steering comment already in context, and take the next useful kernel action.`;
      run.settled = this.drive(run, prompt);
      return { run: branchName };
    } catch (error) {
      if (orphan?.session.isIdle) await orphan.dispose().catch(() => undefined);
      throw error;
    } finally {
      this.creatingRun = false;
    }
  }

  /** One schema-shaped question to whatever model pi routes (no kernel, no run). */
  async structured(request: StructuredRequest): Promise<StructuredResult> {
    return structured(await this.getModelRuntime(), request);
  }

  async listModels(): Promise<Array<{ provider: string; id: string; vision: boolean }>> {
    const runtime = await this.getModelRuntime();
    return (await runtime.getAvailable()).map((model) => ({
      provider: model.provider,
      id: model.id,
      vision: model.input.includes("image"),
    }));
  }

  async shutdown(): Promise<void> {
    const active = this.active();
    if (active?.status === "running") await this.stop(active.name).catch(() => undefined);
    await Promise.all([...this.runs.values()].map((run) => run.settled.catch(() => undefined)));
  }
}
