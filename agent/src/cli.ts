#!/usr/bin/env node
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { ModelRuntime } from "@earendil-works/pi-coding-agent";

import { createSimAgentRuntime, type CreateSimAgentRuntimeOptions } from "./runtime.js";

function parseOptions(argv: string[]): Map<string, string> {
  const result = new Map<string, string>();
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      throw new Error(`expected --name value pairs, got ${argv.slice(index).join(" ")}`);
    }
    result.set(key.slice(2), value);
  }
  return result;
}

function required(options: Map<string, string>, name: string): string {
  const value = options.get(name);
  if (!value) throw new Error(`missing required --${name}`);
  return value;
}

async function resolveStandardModel(provider: string, modelId: string) {
  // No custom credential path: this is deliberately Pi's standard
  // ~/.pi/agent/auth.json + environment + models.json resolution.
  const modelRuntime = await ModelRuntime.create();
  const model = modelRuntime.getModel(provider, modelId);
  if (!model) throw new Error(`Pi model not found: ${provider}/${modelId}`);
  const auth = await modelRuntime.checkAuth(provider);
  return { modelRuntime, model, auth };
}

async function authCheck(argv: string[]): Promise<number> {
  const options = parseOptions(argv);
  const provider = required(options, "provider");
  const modelId = required(options, "model");
  const { model, auth } = await resolveStandardModel(provider, modelId);
  const result = {
    provider,
    model: modelId,
    configured: auth !== undefined,
    authType: auth?.type ?? null,
    authSource: auth?.source ?? null,
    input: model.input,
    vision: model.input.includes("image"),
  };
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  // Vision is reported, not required: SimAgent is numbers-first, so a
  // text-only model can drive a whole run. It is only required for a run
  // started with `--images true`.
  return result.configured ? 0 : 2;
}

/**
 * Command line -> runtime options, with no model and no side effects.
 *
 * Exported so a test can check that every flag actually ARRIVES. A flag that
 * is parsed but never assigned looks exactly like a fresh default from the
 * outside, and no test that starts from `createSimAgentRuntime` can see the
 * difference.
 */
export function runtimeOptionsFrom(options: Map<string, string>): CreateSimAgentRuntimeOptions {
  const problemId = options.get("problem-id");
  const specPath = options.get("spec");
  if ((problemId === undefined) === (specPath === undefined)) {
    throw new Error("provide exactly one of --problem-id or --spec");
  }
  const provider = options.get("provider");
  const modelId = options.get("model");
  if ((provider === undefined) !== (modelId === undefined)) {
    throw new Error("--provider and --model must be given together");
  }
  const runtimeOptions: CreateSimAgentRuntimeOptions = {
    outDir: resolve(required(options, "out-dir")),
    thinkingLevel: (options.get("thinking") ?? "medium") as NonNullable<CreateSimAgentRuntimeOptions["thinkingLevel"]>,
    singleToolPerTurn: true,
    // numbers-first by default; `--images true` turns the picture channel on
    images: options.get("images") === "true",
    seed: Number(options.get("seed") ?? 0),
  };
  if (problemId !== undefined) runtimeOptions.problemId = problemId;
  if (specPath !== undefined) runtimeOptions.specPath = resolve(specPath);
  // continue an earlier run directory instead of starting from a fresh world
  const adopt = options.get("adopt");
  if (adopt !== undefined) runtimeOptions.adopt = resolve(adopt);
  return runtimeOptions;
}

async function runSession(argv: string[]): Promise<number> {
  const options = parseOptions(argv);
  const runtimeOptions = runtimeOptionsFrom(options);
  const outDir = runtimeOptions.outDir;
  const provider = options.get("provider");
  const modelId = options.get("model");
  if (provider !== undefined && modelId !== undefined) {
    const selected = await resolveStandardModel(provider, modelId);
    if (!selected.auth) throw new Error(`no Pi authentication found for ${provider}`);
    runtimeOptions.modelRuntime = selected.modelRuntime;
    runtimeOptions.model = selected.model;
  }
  const runtime = await createSimAgentRuntime(runtimeOptions);
  const maxTurns = Math.max(1, Math.min(Number(options.get("max-turns") ?? 40), 200));
  let turns = 0;
  let limited = false;
  let limitStop: Promise<void> | undefined;
  runtime.session.subscribe((event) => {
    if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
      process.stdout.write(event.assistantMessageEvent.delta);
    } else if (event.type === "turn_end") {
      turns += 1;
      if (turns >= maxTurns && !limited) {
        limited = true;
        limitStop = runtime.stop(`maximum turn count reached (${maxTurns})`).catch(() => undefined);
      }
    }
  });
  try {
    await runtime.promptTask();
  } catch (error) {
    if (!limited) throw error;
  }
  if (limitStop) await limitStop;
  process.stdout.write("\n");
  const finalized = await runtime.dispose();
  const proof = finalized.proof as Record<string, unknown> | null;
  if (proof) {
    const rawMethod = String(proof.method);
    const method = rawMethod.startsWith("Method.")
      ? rawMethod.slice("Method.".length).toLowerCase()
      : rawMethod;
    process.stdout.write(
      `Proof: ${method} - verified by ${String(proof.verified_by ?? proof.verifiedBy)}\n`,
    );
  } else {
    process.stdout.write("No kernel-grade result was established in this session.\n");
  }
  process.stdout.write(`Run dir: ${outDir}\n`);
  process.stdout.write(`Pi session: ${runtime.session.sessionFile ?? "in-memory"}\n`);
  return 0;
}

async function smoke(argv: string[]): Promise<number> {
  const options = parseOptions(argv);
  const provider = required(options, "provider");
  const modelId = required(options, "model");
  const problemId = options.get("problem-id") ?? "circumcenter-in-triangle";
  const outDir = resolve(options.get("out-dir") ?? `runs/pi-p0-smoke-${Date.now()}`);
  const { modelRuntime, model, auth } = await resolveStandardModel(provider, modelId);
  if (!auth) {
    throw new Error(
      `no Pi authentication found for ${provider}; configure an API key or use Pi's /login first`,
    );
  }
  if (!model.input.includes("image")) {
    throw new Error(`${provider}/${modelId} is text-only; SimAgent smoke requires image input`);
  }

  const runtime = await createSimAgentRuntime({
    problemId,
    outDir,
    sessionDir: resolve(outDir, "pi-sessions"),
    modelRuntime,
    model,
    thinkingLevel: "medium",
  });
  runtime.session.subscribe((event) => {
    if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
      process.stdout.write(event.assistantMessageEvent.delta);
    }
  });
  try {
    await runtime.promptTask();
    process.stdout.write("\n");
    const finalized = await runtime.dispose();
    process.stdout.write(`kernel journal: ${finalized.journalPath}\n`);
    return 0;
  } catch (error) {
    if (runtime.session.isIdle) await runtime.dispose().catch(() => undefined);
    throw error;
  }
}

async function main(): Promise<number> {
  const [command, ...argv] = process.argv.slice(2);
  if (command === "auth-check") return authCheck(argv);
  if (command === "run") return runSession(argv);
  if (command === "smoke") return smoke(argv);
  process.stderr.write(
    "usage:\n" +
      "  cli.js auth-check --provider NAME --model ID\n" +
      "  cli.js run (--problem-id ID | --spec PATH) --out-dir PATH [--provider NAME --model ID] [--images true] [--seed N] [--adopt RUN_DIR]\n" +
      "  cli.js smoke --provider NAME --model ID [--problem-id ID] [--out-dir PATH]\n",
  );
  return 2;
}

// Only when this file IS the command. A test that imports it to check the flag
// surface must not run the command, print usage, and set an exit code.
if (process.argv[1] !== undefined && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main()
    .then((code) => {
      process.exitCode = code;
    })
    .catch((error: unknown) => {
      process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
      process.exitCode = 1;
    });
}
