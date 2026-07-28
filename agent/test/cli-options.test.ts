import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { runtimeOptionsFrom } from "../src/cli.js";

/**
 * The command line is a chain: simagent -> node cli.ts -> runtime -> kernel argv.
 * Every other test in this suite starts at `createSimAgentRuntime`, so a flag
 * parsed by the CLI and then never assigned passes all of them: the run just
 * looks like a fresh default. That happened to `--adopt` once. These tests
 * watch the hop no other test can see.
 */
describe("cli run flags", () => {
  it("carries every run flag into the runtime options", () => {
    const built = runtimeOptionsFrom(
      new Map(
        Object.entries({
          "problem-id": "circumcenter-in-triangle",
          "out-dir": "runs/here",
          thinking: "high",
          images: "true",
          seed: "7",
          adopt: "runs/earlier",
        }),
      ),
    );
    expect(built.problemId).toBe("circumcenter-in-triangle");
    expect(built.outDir).toBe(resolve("runs/here"));
    expect(built.thinkingLevel).toBe("high");
    expect(built.images).toBe(true);
    expect(built.seed).toBe(7);
    expect(built.adopt).toBe(resolve("runs/earlier"));
  });

  it("starts a fresh world when no earlier run is named", () => {
    const built = runtimeOptionsFrom(
      new Map([
        ["problem-id", "circumcenter-in-triangle"],
        ["out-dir", "runs/here"],
      ]),
    );
    expect(built.adopt).toBeUndefined();
    expect(built.images).toBe(false);
    expect(built.seed).toBe(0);
  });

  it("still refuses an ambiguous or missing problem source", () => {
    expect(() => runtimeOptionsFrom(new Map([["out-dir", "runs/here"]]))).toThrow(
      /exactly one of --problem-id or --spec/,
    );
    expect(() =>
      runtimeOptionsFrom(
        new Map([
          ["problem-id", "a"],
          ["spec", "b.json"],
          ["out-dir", "runs/here"],
        ]),
      ),
    ).toThrow(/exactly one of --problem-id or --spec/);
  });

  it("still refuses a provider without its model", () => {
    expect(() =>
      runtimeOptionsFrom(
        new Map([
          ["problem-id", "a"],
          ["out-dir", "runs/here"],
          ["provider", "somewhere"],
        ]),
      ),
    ).toThrow(/must be given together/);
  });
});
