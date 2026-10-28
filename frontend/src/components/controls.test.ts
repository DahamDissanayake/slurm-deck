import { describe, expect, it } from "vitest";
import * as c from "./controls";

const tokens = (s: string) => s.split(/\s+/);

describe("controls", () => {
  it("gives inputs, selects and normal buttons the same height", () => {
    for (const k of [c.input, c.select, c.primary, c.secondary, c.danger]) {
      expect(tokens(k)).toContain("h-10");
    }
    for (const k of [c.small, c.smallDanger]) expect(tokens(k)).toContain("h-8");
    expect(tokens(c.textarea)).toContain("min-h-20");
  });

  it("carries no margin, so rows can align them", () => {
    for (const k of Object.values(c.PRESETS)) {
      expect(tokens(k).filter((t) => /^-?m[trblxy]?-/.test(t))).toEqual([]);
    }
  });

  it("gives every button a border and a disabled look", () => {
    for (const k of [c.primary, c.secondary, c.danger, c.small, c.smallDanger]) {
      expect(tokens(k)).toContain("border");
      expect(tokens(k)).toContain("disabled:opacity-50");
    }
  });

  it("is never combined with a class that overrides it", () => {
    const files = import.meta.glob("../**/*.tsx", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
    const bad: string[] = [];
    const groups: Record<string, RegExp> = { height: /(^|\s)h-\d+(\s|$)/, margin: /(^|\s)m[trblxy]?-\d+(\s|$)/, width: /(^|\s)w-\d+(\s|$)/ };
    for (const [path, src] of Object.entries(files)) {
      if (path.endsWith(".test.tsx")) continue;
      for (const m of src.matchAll(/className=\{`([^`]*)`\}/g)) {
        const text = m[1];
        const uses = Object.keys(c.PRESETS).some((n) => text.includes("${" + n + "}"));
        if (!uses) continue;
        const extra = text.replace(/\$\{[^}]*\}/g, " ");
        if (groups.height.test(extra)) bad.push(`${path}: ${text}`);
      }
    }
    expect(bad).toEqual([]);
  });
});
