/**
 * One structured, non-agentic model request, routed by pi.
 *
 * Formalizing a conjecture and drafting a proof attempt are not agent runs:
 * they are single questions with a fixed answer shape. They still belong to
 * pi, because SimAgent harnesses whatever model pi routes and a front door
 * pinned to one vendor would contradict that everywhere else in the repo.
 *
 * The answer shape is enforced the only way that works across providers: one
 * tool whose parameters ARE the schema, and the tool call's arguments are the
 * result. Nothing here validates the mathematics; Python's `validate_claim`
 * remains the gate.
 */
import type { AssistantMessage, Context, Model } from "@earendil-works/pi-ai";
import { Type } from "typebox";
import type { ModelRuntime } from "@earendil-works/pi-coding-agent";

export interface StructuredRequest {
  system: string;
  prompt: string;
  toolName: string;
  toolDescription: string;
  schema: Record<string, unknown>;
  provider?: string;
  model?: string;
}

export interface StructuredResult {
  provider: string;
  model: string;
  output: Record<string, unknown>;
}

/**
 * Vision is deliberately NOT required here: a formalizer reads words and
 * writes JSON, so demanding an image model would reject a perfectly capable
 * one for a capability this request never uses.
 */
async function selectModel(
  runtime: ModelRuntime,
  provider?: string,
  id?: string,
): Promise<Model<any>> {
  if (provider !== undefined && id !== undefined) {
    const requested = runtime.getModel(provider, id);
    if (!requested) throw new Error(`pi does not know the model ${provider}/${id}`);
    if ((await runtime.checkAuth(provider)) === undefined) {
      throw new Error(`no standard Pi authentication is configured for ${provider}`);
    }
    return requested;
  }
  const available = await runtime.getAvailable();
  const first = available[0];
  if (!first) throw new Error("no authenticated Pi model is available");
  return first;
}

export async function structured(
  runtime: ModelRuntime,
  request: StructuredRequest,
): Promise<StructuredResult> {
  const model = await selectModel(runtime, request.provider, request.model);
  const context: Context = {
    systemPrompt: request.system,
    messages: [{ role: "user", content: request.prompt, timestamp: Date.now() }],
    tools: [
      {
        name: request.toolName,
        description: request.toolDescription,
        parameters: Type.Unsafe(request.schema),
      },
    ],
  };
  const reply: AssistantMessage = await runtime.complete(model, context);
  const call = reply.content.find(
    (block) => block.type === "toolCall" && block.name === request.toolName,
  );
  if (!call || call.type !== "toolCall") {
    // Say WHY, including whatever the model said instead: a bare failure is
    // one the caller's repair loop cannot act on.
    const said = reply.content
      .filter((block): block is Extract<typeof block, { type: "text" }> => block.type === "text")
      .map((block) => block.text)
      .join("\n")
      .trim();
    throw new Error(
      `${model.provider}/${model.id} returned no ${request.toolName} call ` +
        `(stopReason=${reply.stopReason})${said ? `: ${said.slice(0, 400)}` : ""}`,
    );
  }
  return { provider: model.provider, model: model.id, output: call.arguments };
}
