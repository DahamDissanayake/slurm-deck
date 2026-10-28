import { describe, expect, it } from "vitest";

import css from "./tokens.css?raw";

// Spec §6: [token, dark, light]
const SPEC: [string, string, string][] = [
  ["--bg", "#0A0E13", "#F3F6F8"],
  ["--surface", "#12181F", "#FFFFFF"],
  ["--surface-2", "#1A222C", "#EEF2F5"],
  ["--border", "#26313D", "#D7DEE5"],
  ["--text", "#E7ECF1", "#16202B"],
  ["--text-dim", "#7E8CA0", "#5B6B7C"],
  ["--accent", "#3FD9E8", "#0E93A3"],
];
const STATUS = ["--danger", "--warning", "--ok"];

function block(selector: string): string {
  const start = css.indexOf(selector + " {");
  expect(start, `missing ${selector}`).toBeGreaterThanOrEqual(0);
  return css.slice(start, css.indexOf("}", start));
}

const value = (body: string, token: string) =>
  body.match(new RegExp(`${token}:\\s*([^;]+);`))?.[1].trim();

describe("tokens.css", () => {
  const dark = [block(":root"), block(':root[data-theme="dark"]')];
  const light = [block(':root:not([data-theme="dark"])'), block(':root[data-theme="light"]')];

  it.each(SPEC)("%s matches the spec in both themes", (token, d, l) => {
    for (const b of dark) expect(value(b, token)?.toUpperCase()).toBe(d);
    for (const b of light) expect(value(b, token)?.toUpperCase()).toBe(l);
  });

  it("defines status colours apart from the accent", () => {
    for (const b of [...dark, ...light]) {
      for (const t of STATUS) {
        expect(value(b, t)).toMatch(/^#[0-9A-Fa-f]{6}$/);
        expect(value(b, t)).not.toBe(value(b, "--accent"));
      }
    }
  });

  it("puts light under prefers-color-scheme and loads nothing external", () => {
    expect(css).toMatch(/@media \(prefers-color-scheme: light\)/);
    expect(css).not.toMatch(/@import|url\(|https?:/);
  });
});
