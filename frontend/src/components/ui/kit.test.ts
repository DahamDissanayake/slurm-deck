import { describe, expect, it } from "vitest";

const sources = Object.entries(
  import.meta.glob(["./*.{ts,tsx}", "!./*.test.*"], { query: "?raw", import: "default", eager: true }),
) as [string, string][];

describe("the UI kit sources", () => {
  it("are all read", () => expect(sources.length).toBeGreaterThanOrEqual(15));

  it.each(sources)("%s uses tokens, never literal colours", (_, src) => {
    expect(src).not.toMatch(/#[0-9a-fA-F]{3,8}\b|\b(rgba?|hsla?)\(/);
  });

  it.each(sources)("%s animates only when motion is allowed", (_, src) => {
    for (const m of src.matchAll(/([\w:-]*)animate-[\w-]+/g)) expect(m[1]).toBe("motion-safe:");
  });
});
