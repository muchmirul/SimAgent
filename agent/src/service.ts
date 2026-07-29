#!/usr/bin/env node
import { resolve } from "node:path";

import {
  ControllerError,
  RunController,
  type BranchRunRequest,
  type RunControllerOptions,
  type StartRunRequest,
} from "./controller.js";

interface RequestFrame {
  id?: unknown;
  op?: unknown;
  [key: string]: unknown;
}

interface ErrorBody {
  code: string;
  type: string;
  message: string;
}

function options(argv: string[]): Map<string, string> {
  const parsed = new Map<string, string>();
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      throw new Error(`expected --name value pairs, got ${argv.slice(index).join(" ")}`);
    }
    parsed.set(key.slice(2), value);
  }
  return parsed;
}

function errorBody(error: unknown): ErrorBody {
  if (error instanceof ControllerError) {
    return { code: error.code, type: error.name, message: error.message };
  }
  return {
    code: "INTERNAL",
    type: error instanceof Error ? error.name : "Error",
    message: error instanceof Error ? error.message : String(error),
  };
}

function writeFrame(frame: Record<string, unknown>): void {
  process.stdout.write(`${JSON.stringify(frame)}\n`);
}

const parsed = options(process.argv.slice(2));
const runsRoot = parsed.get("runs-root");
if (!runsRoot) throw new Error("missing required --runs-root");
const controllerOptions: RunControllerOptions = { runsRoot: resolve(runsRoot) };
const cwd = parsed.get("cwd");
const repoRoot = parsed.get("repo-root");
const pythonPath = parsed.get("python-path");
const sessionDir = parsed.get("session-dir");
if (cwd !== undefined) controllerOptions.cwd = cwd;
if (repoRoot !== undefined) controllerOptions.repoRoot = repoRoot;
if (pythonPath !== undefined) controllerOptions.pythonPath = pythonPath;
if (sessionDir !== undefined) controllerOptions.sessionDir = sessionDir;
const controller = new RunController(controllerOptions);

const THINKING_LEVELS = new Set(["off", "minimal", "low", "medium", "high", "xhigh", "max"]);

let input = "";
let shuttingDown = false;

async function dispatch(frame: RequestFrame): Promise<unknown> {
  const op = frame.op;
  if (op === "start") {
    const request: StartRunRequest = {};
    if (typeof frame.problemId === "string") request.problemId = frame.problemId;
    if (typeof frame.specPath === "string") request.specPath = frame.specPath;
    if (typeof frame.provider === "string") request.provider = frame.provider;
    if (typeof frame.model === "string") request.model = frame.model;
    if (typeof frame.thinkingLevel === "string") {
      if (!THINKING_LEVELS.has(frame.thinkingLevel)) {
        throw new ControllerError("VALIDATION", `invalid thinking level ${frame.thinkingLevel}`);
      }
      request.thinkingLevel = frame.thinkingLevel as NonNullable<StartRunRequest["thinkingLevel"]>;
    }
    if (typeof frame.maxTurns === "number") request.maxTurns = frame.maxTurns;
    if (typeof frame.runBase === "string") request.runBase = frame.runBase;
    if (typeof frame.images === "boolean") request.images = frame.images;
    if (typeof frame.adopt === "string") request.adopt = frame.adopt;
    return controller.start(request);
  }
  if (op === "status") return controller.status(String(frame.run ?? ""));
  if (op === "events") {
    return controller.events(
      String(frame.run ?? ""),
      typeof frame.after === "number" ? frame.after : 0,
    );
  }
  if (op === "comment") {
    return controller.comment(String(frame.run ?? ""), {
      text: String(frame.text ?? ""),
      target:
        typeof frame.target === "object" && frame.target !== null
          ? frame.target as Record<string, unknown>
          : {},
    });
  }
  if (op === "userAction") {
    if (typeof frame.tool !== "string" || !frame.tool) {
      throw new ControllerError("VALIDATION", "userAction needs a tool name");
    }
    return controller.userAction(String(frame.run ?? ""), {
      tool: frame.tool,
      args:
        typeof frame.args === "object" && frame.args !== null
          ? (frame.args as Record<string, unknown>)
          : {},
    });
  }
  if (op === "pause") return controller.pause(String(frame.run ?? ""));
  if (op === "resume") return controller.resume(String(frame.run ?? ""));
  if (op === "stop") return controller.stop(String(frame.run ?? ""));
  if (op === "branch") {
    const request: BranchRunRequest = { step: Number(frame.step) };
    if (typeof frame.comment === "string") request.comment = frame.comment;
    if (typeof frame.target === "object" && frame.target !== null) {
      request.target = frame.target as Record<string, unknown>;
    }
    return controller.branch(String(frame.run ?? ""), request);
  }
  if (op === "structured") {
    for (const field of ["system", "prompt", "toolName", "toolDescription"] as const) {
      if (typeof frame[field] !== "string" || !frame[field]) {
        throw new ControllerError("VALIDATION", `structured needs a non-empty ${field}`);
      }
    }
    if (typeof frame.schema !== "object" || frame.schema === null) {
      throw new ControllerError("VALIDATION", "structured needs a schema object");
    }
    const request = {
      system: frame.system as string,
      prompt: frame.prompt as string,
      toolName: frame.toolName as string,
      toolDescription: frame.toolDescription as string,
      schema: frame.schema as Record<string, unknown>,
    } as Parameters<typeof controller.structured>[0];
    if (typeof frame.provider === "string") request.provider = frame.provider;
    if (typeof frame.model === "string") request.model = frame.model;
    return controller.structured(request);
  }
  if (op === "models") return controller.listModels();
  if (op === "shutdown") {
    shuttingDown = true;
    await controller.shutdown();
    return { status: "stopped" };
  }
  throw new ControllerError("VALIDATION", `unsupported operation ${String(op)}`);
}

function consume(line: string): void {
  let frame: RequestFrame;
  try {
    frame = JSON.parse(line) as RequestFrame;
    if (typeof frame !== "object" || frame === null || typeof frame.id !== "string") {
      throw new Error("request must be an object with a string id");
    }
  } catch (error) {
    writeFrame({ id: null, ok: false, error: errorBody(error) });
    return;
  }
  void dispatch(frame)
    .then((result) => {
      writeFrame({ id: frame.id, ok: true, result });
      if (shuttingDown) process.stdout.write("", () => process.exit(0));
    })
    .catch((error: unknown) => {
      writeFrame({ id: frame.id, ok: false, error: errorBody(error) });
    });
}

process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk: string) => {
  input += chunk;
  for (;;) {
    const boundary = input.indexOf("\n");
    if (boundary < 0) break;
    const line = input.slice(0, boundary);
    input = input.slice(boundary + 1);
    if (line) consume(line);
  }
});
process.stdin.on("end", () => {
  void controller.shutdown().finally(() => process.exit(0));
});
for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    void controller.shutdown().finally(() => process.exit(0));
  });
}
