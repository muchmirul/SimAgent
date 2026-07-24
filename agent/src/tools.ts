import { StringEnum } from "@earendil-works/pi-ai";
import { defineTool, type ToolDefinition } from "@earendil-works/pi-coding-agent";
import { Type, type TSchema } from "typebox";

import { KernelClient, type KernelDescription, type KernelToolResult } from "./kernel-client.js";

const METHODS = [
  "direct",
  "contradiction",
  "contrapositive",
  "induction",
  "cases",
  "construction",
  "counterexample",
  "exhaustion",
  "combinatorial",
  "infinite_descent",
] as const;

const VIEW_KINDS = ["field", "sweep", "trajectory"] as const;
const EXPECT_RELATIONS = ["<", "<=", ">", ">=", "holds", "fails"] as const;

const Empty = () => Type.Object({}, { additionalProperties: false });

const TOOL_SCHEMAS: Record<string, TSchema> = {
  plan: Type.Object(
    {
      method: StringEnum(METHODS),
      idea: Type.String(),
    },
    { additionalProperties: false },
  ),
  look: Empty(),
  sample: Type.Object({ seed: Type.Optional(Type.Integer()) }, { additionalProperties: false }),
  set_var: Type.Object(
    {
      name: Type.String(),
      row: Type.Optional(Type.Integer()),
      values: Type.Array(Type.Number()),
    },
    { additionalProperties: false },
  ),
  nudge: Type.Object(
    {
      name: Type.String(),
      row: Type.Integer(),
      delta: Type.Array(Type.Number()),
    },
    { additionalProperties: false },
  ),
  check: Empty(),
  measure: Empty(),
  view: Type.Object(
    {
      kind: StringEnum(VIEW_KINDS),
      var: Type.Optional(Type.String()),
      row: Type.Optional(Type.Integer()),
      xi: Type.Optional(Type.Integer()),
      yi: Type.Optional(Type.Integer()),
      coord: Type.Optional(Type.Integer()),
      resolution: Type.Optional(Type.Integer()),
    },
    { additionalProperties: false },
  ),
  imagine: Type.Object(
    {
      ops: Type.Array(Type.Unsafe({ type: "object" })),
      look: Type.Optional(Type.Boolean()),
    },
    { additionalProperties: false },
  ),
  refine: Type.Object({ steps: Type.Optional(Type.Integer()) }, { additionalProperties: false }),
  hunt: Type.Object({ trials: Type.Optional(Type.Integer()) }, { additionalProperties: false }),
  exhaust: Empty(),
  certify: Empty(),
  sum_of_squares: Empty(),
  prove_by_cases: Type.Object(
    {
      var: Type.String(),
      index: Type.Optional(Type.Integer()),
      at: Type.Number(),
    },
    { additionalProperties: false },
  ),
  prove_by_induction: Empty(),
  submit_lean_proof: Type.Object(
    {
      method: StringEnum(METHODS),
      argument: Type.String(),
      lean_code: Type.Optional(Type.String()),
    },
    { additionalProperties: false },
  ),
  construct: Type.Object(
    {
      name: Type.String(),
      ctor: Type.String(),
      args: Type.Array(Type.String()),
    },
    { additionalProperties: false },
  ),
  expect: Type.Object(
    {
      relation: StringEnum(EXPECT_RELATIONS),
      value: Type.Optional(Type.Number()),
      note: Type.Optional(Type.String()),
    },
    { additionalProperties: false },
  ),
  finish: Type.Object({ summary: Type.String() }, { additionalProperties: false }),
};

export const KERNEL_TOOL_NAMES = Object.freeze(Object.keys(TOOL_SCHEMAS));

export interface KernelToolDetails {
  kernel: {
    toolCallId: string;
    journalSeq: number;
    traceStep: number;
    stateHash: string;
    isError: boolean;
    finished: boolean;
  };
}

export function isKernelToolDetails(value: unknown): value is KernelToolDetails {
  if (typeof value !== "object" || value === null) return false;
  const kernel = (value as { kernel?: unknown }).kernel;
  return typeof kernel === "object" && kernel !== null && typeof (kernel as { toolCallId?: unknown }).toolCallId === "string";
}

function canonicalJson(value: unknown): string {
  const normalize = (item: unknown): unknown => {
    if (Array.isArray(item)) return item.map(normalize);
    if (typeof item !== "object" || item === null) return item;
    return Object.fromEntries(
      Object.entries(item as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, child]) => [key, normalize(child)]),
    );
  };
  return JSON.stringify(normalize(value));
}

function verifyDescription(description: KernelDescription): Map<string, KernelDescription["tools"][number]> {
  const definitions = new Map(description.tools.map((tool) => [tool.name, tool]));
  const expected = new Set(KERNEL_TOOL_NAMES);
  const actual = new Set(definitions.keys());
  const missing = [...expected].filter((name) => !actual.has(name));
  const unexpected = [...actual].filter((name) => !expected.has(name));
  if (missing.length > 0 || unexpected.length > 0) {
    throw new Error(
      `Python/TypeScript tool surface drift (missing=${missing.join(",") || "none"}; ` +
        `unexpected=${unexpected.join(",") || "none"})`,
    );
  }
  return definitions;
}

/** Build the only tools exposed to Pi. Every definition forces sequential mode. */
export function createKernelTools(
  kernel: KernelClient,
  description: KernelDescription = kernel.description,
): ToolDefinition[] {
  const definitions = verifyDescription(description);
  return KERNEL_TOOL_NAMES.map((name) => {
    const source = definitions.get(name);
    const parameters = TOOL_SCHEMAS[name];
    if (!source || !parameters) throw new Error(`missing tool metadata for ${name}`);
    if (canonicalJson(parameters) !== canonicalJson(source.input_schema)) {
      throw new Error(`Python/TypeScript parameter schema drift for ${name}`);
    }

    return defineTool({
      name,
      label: name,
      description: source.description,
      parameters,
      executionMode: "sequential",
      async execute(toolCallId, params, signal) {
        if (signal?.aborted) throw new Error("kernel tool call aborted before execution");
        const result: KernelToolResult = await kernel.callTool(
          toolCallId,
          name,
          params as Record<string, unknown>,
        );
        return {
          content: result.content,
          details: {
            kernel: {
              toolCallId: result.toolCallId,
              journalSeq: result.journalSeq,
              traceStep: result.traceStep,
              stateHash: result.stateHash,
              isError: result.isError,
              finished: result.finished,
            },
          } satisfies KernelToolDetails,
          // Pi stops without an extra provider turn when finish is the sole
          // call (or every sibling is also rejected after finish).
          terminate: result.finished,
        };
      },
    });
  });
}
