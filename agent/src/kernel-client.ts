import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";

import type { ImageContent, TextContent } from "@earendil-works/pi-ai";

export type KernelContent = TextContent | ImageContent;

export interface KernelToolDescription {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

export interface KernelDescription {
  protocolVersion: number;
  journalVersion: number;
  specId: string;
  title: string;
  systemPrompt: string;
  taskPrompt: string;
  tools: KernelToolDescription[];
  journalPath: string;
}

export interface KernelSnapshot {
  journalSeq: number;
  traceStep: number;
  journalPath: string;
  state: Record<string, unknown>;
  stateHash: string;
  finished: boolean;
}

export interface KernelToolResult {
  toolCallId: string;
  content: KernelContent[];
  isError: boolean;
  finished: boolean;
  journalSeq: number;
  traceStep: number;
  journalPath: string;
  state: Record<string, unknown>;
  stateHash: string;
}

export interface KernelFinalizeResult extends KernelSnapshot {
  proof: unknown;
  report: unknown;
  artifacts: Record<string, string>;
  alreadyFinalized?: boolean;
}

interface ProtocolResponse<T = unknown> {
  id: string | null;
  ok: boolean;
  result?: T;
  error?: { type: string; message: string };
}

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
}

export interface KernelClientOptions {
  problemId?: string;
  specPath?: string;
  outDir: string;
  repoRoot?: string;
  pythonPath?: string;
  replayJournal?: string;
  replayThrough?: number;
  env?: NodeJS.ProcessEnv;
}

function defaultRepoRoot(): string {
  // Works from both agent/src under Vitest and agent/dist after tsc.
  return resolve(dirname(fileURLToPath(import.meta.url)), "../..");
}

function protocolError(response: ProtocolResponse): Error {
  const kind = response.error?.type ?? "KernelProtocolError";
  const message = response.error?.message ?? "kernel request failed without an error message";
  return new Error(`${kind}: ${message}`);
}

/**
 * Strict LF-delimited client for ``python -m simagent.kernel_transport``.
 *
 * The subprocess is private to one Pi session and therefore owns exactly one
 * mutable world. Calls may be requested concurrently, but Pi configures every
 * kernel tool and the global loop as sequential; the client still correlates
 * protocol responses by request id as a defensive boundary.
 */
export class KernelClient {
  readonly process: ChildProcessWithoutNullStreams;
  readonly repoRoot: string;
  readonly pythonPath: string;
  tip!: KernelSnapshot;

  private descriptionValue?: KernelDescription;
  private readonly pending = new Map<string, PendingRequest>();
  private stdoutBuffer = "";
  private stderrBuffer = "";
  private requestSequence = 0;
  private exited = false;
  private closing = false;
  private readonly exitPromise: Promise<void>;

  private constructor(
    child: ChildProcessWithoutNullStreams,
    repoRoot: string,
    pythonPath: string,
    exitPromise: Promise<void>,
    settleExit: () => void,
  ) {
    this.process = child;
    this.repoRoot = repoRoot;
    this.pythonPath = pythonPath;
    this.exitPromise = exitPromise;
    this.installProcessHandlers(settleExit);
  }

  get description(): KernelDescription {
    if (!this.descriptionValue) throw new Error("kernel client has not completed startup");
    return this.descriptionValue;
  }

  static async start(options: KernelClientOptions): Promise<KernelClient> {
    const repoRoot = resolve(options.repoRoot ?? defaultRepoRoot());
    const pythonPath = resolve(options.pythonPath ?? join(repoRoot, ".venv/bin/python"));
    if ((options.problemId === undefined) === (options.specPath === undefined)) {
      throw new Error("provide exactly one of problemId or specPath");
    }
    const args = ["-m", "simagent.kernel_transport"];
    if (options.problemId !== undefined) args.push("--problem-id", options.problemId);
    if (options.specPath !== undefined) args.push("--spec", resolve(options.specPath));
    args.push("--out-dir", resolve(options.outDir));
    if (options.replayJournal !== undefined) {
      args.push("--replay-journal", resolve(options.replayJournal));
    }
    if (options.replayThrough !== undefined) {
      args.push("--replay-through", String(options.replayThrough));
    }

    const child = spawn(pythonPath, args, {
      cwd: repoRoot,
      env: { ...process.env, ...options.env },
      stdio: ["pipe", "pipe", "pipe"],
      shell: false,
    });

    let settleExit!: () => void;
    const exitPromise = new Promise<void>((resolveExit) => {
      settleExit = resolveExit;
    });

    const client = new KernelClient(child, repoRoot, pythonPath, exitPromise, settleExit);
    try {
      client.descriptionValue = await client.request<KernelDescription>({ op: "describe" });
      client.tip = await client.request<KernelSnapshot>({ op: "snapshot" });
      return client;
    } catch (error) {
      child.kill();
      await exitPromise;
      throw error;
    }
  }

  private installProcessHandlers(settleExit: () => void): void {
    this.process.stdout.setEncoding("utf8");
    this.process.stderr.setEncoding("utf8");
    this.process.stdout.on("data", (chunk: string) => this.consumeStdout(chunk));
    this.process.stderr.on("data", (chunk: string) => {
      // Keep diagnostics bounded and never reflect them into model context.
      this.stderrBuffer = (this.stderrBuffer + chunk).slice(-64 * 1024);
    });
    this.process.on("error", (error) => this.rejectAll(error));
    // `close` is emitted after stdio closes and also follows spawn failures;
    // unlike `exit`, it gives startup errors a reliable settlement boundary.
    this.process.on("close", (code, signal) => {
      this.exited = true;
      const expected = this.closing && code === 0;
      if (!expected && this.pending.size > 0) {
        const suffix = this.stderrBuffer.trim();
        this.rejectAll(
          new Error(
            `kernel subprocess exited (code=${String(code)}, signal=${String(signal)})` +
              (suffix ? `: ${suffix}` : ""),
          ),
        );
      }
      settleExit();
    });
  }

  private consumeStdout(chunk: string): void {
    this.stdoutBuffer += chunk;
    for (;;) {
      const boundary = this.stdoutBuffer.indexOf("\n");
      if (boundary < 0) return;
      const line = this.stdoutBuffer.slice(0, boundary);
      this.stdoutBuffer = this.stdoutBuffer.slice(boundary + 1);
      if (!line) continue;

      let response: ProtocolResponse;
      try {
        response = JSON.parse(line) as ProtocolResponse;
      } catch (error) {
        this.rejectAll(new Error(`invalid JSON from kernel: ${String(error)}`));
        this.process.kill();
        return;
      }
      if (typeof response.id !== "string") {
        this.rejectAll(new Error("kernel response is missing a request id"));
        this.process.kill();
        return;
      }
      const pending = this.pending.get(response.id);
      if (!pending) {
        this.rejectAll(new Error(`unexpected kernel response id ${response.id}`));
        this.process.kill();
        return;
      }
      this.pending.delete(response.id);
      if (!response.ok) pending.reject(protocolError(response));
      else pending.resolve(response.result);
    }
  }

  private rejectAll(error: Error): void {
    for (const pending of this.pending.values()) pending.reject(error);
    this.pending.clear();
  }

  private request<T>(payload: Record<string, unknown>): Promise<T> {
    if (this.exited) return Promise.reject(new Error("kernel subprocess is not running"));
    const id = `request-${++this.requestSequence}`;
    return new Promise<T>((resolveRequest, rejectRequest) => {
      this.pending.set(id, {
        resolve: (value) => resolveRequest(value as T),
        reject: rejectRequest,
      });
      const frame = `${JSON.stringify({ id, ...payload })}\n`;
      this.process.stdin.write(frame, "utf8", (error) => {
        if (!error) return;
        this.pending.delete(id);
        rejectRequest(error);
      });
    });
  }

  async callTool(toolCallId: string, name: string, args: Record<string, unknown>): Promise<KernelToolResult> {
    const result = await this.request<KernelToolResult>({
      op: "call",
      toolCallId,
      name,
      args,
    });
    if (result.toolCallId !== toolCallId) {
      throw new Error(`kernel returned toolCallId ${result.toolCallId}, expected ${toolCallId}`);
    }
    this.tip = {
      journalSeq: result.journalSeq,
      traceStep: result.traceStep,
      journalPath: result.journalPath,
      state: result.state,
      stateHash: result.stateHash,
      finished: result.finished,
    };
    return result;
  }

  async snapshot(): Promise<KernelSnapshot> {
    const snapshot = await this.request<KernelSnapshot>({ op: "snapshot" });
    this.tip = snapshot;
    return snapshot;
  }

  async noteThought(
    text: string,
    kind: "text" | "thinking" | "user" = "text",
  ): Promise<KernelSnapshot> {
    const snapshot = await this.request<KernelSnapshot>({ op: "note", text, kind });
    this.tip = snapshot;
    return snapshot;
  }

  /** Record which model pi routed, as run provenance (not a journal event). */
  async setRuntime(payload: Record<string, unknown>): Promise<KernelSnapshot> {
    const snapshot = await this.request<KernelSnapshot>({ op: "runtime", payload });
    this.tip = snapshot;
    return snapshot;
  }

  async annotate(
    kind: "user_comment" | "provenance",
    payload: Record<string, unknown>,
  ): Promise<KernelSnapshot> {
    // A user can comment while a tool is still running. Queue a snapshot after
    // that tool, then the annotation, so the comparison is never against a
    // stale pre-tool tip. Python independently enforces the same invariant.
    const before = await this.snapshot();
    const snapshot = await this.request<KernelSnapshot>({ op: "annotate", kind, payload });
    if (snapshot.stateHash !== before.stateHash) {
      throw new Error(`${kind} annotation changed kernel state`);
    }
    this.tip = snapshot;
    return snapshot;
  }

  async stop(summary = "session stopped by the user"): Promise<KernelSnapshot> {
    const snapshot = await this.request<KernelSnapshot>({ op: "stop", summary });
    this.tip = snapshot;
    return snapshot;
  }

  async close(): Promise<KernelFinalizeResult> {
    if (this.exited) throw new Error("kernel subprocess exited before finalization");
    this.closing = true;
    const result = await this.request<KernelFinalizeResult>({ op: "finalize" });
    this.tip = result;
    this.process.stdin.end();
    await this.exitPromise;
    return result;
  }

  async terminate(): Promise<void> {
    if (this.exited) return;
    this.closing = true;
    this.process.kill();
    await this.exitPromise;
  }
}
