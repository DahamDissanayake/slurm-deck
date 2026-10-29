import { describe, expect, it } from "vitest";

import css from "./tokens.css?raw";

// Tokens v2 (modern UI redesign spec): [token, dark, light]
const SPEC: [string, string, string][] = [
  ["--bg", "#0E131A", "#F4F6F9"],
  ["--surface", "#151B23", "#FFFFFF"],
  ["--surface-2", "#1C242E", "#EDF0F5"],
  ["--border", "#29333F", "#DAE0E8"],
  ["--text", "#E6EBF1", "#17202B"],
  ["--text-dim", "#8C99AB", "#5A6779"],
  ["--accent", "#8B9CFF", "#4152D9"],
];
const STATUS = ["--danger", "--warning", "--ok", "--info"];
const THEMED = ["--accent-soft", "--accent-fg", "--ok-soft", "--warning-soft", "--danger-soft",
  "--info-soft", "--neutral-soft", "--border-strong", "--shadow-sm", "--shadow-md", "--shadow-lg"];
// Theme-independent scales: [token, value]
const SCALES: [string, string][] = [
  ["--radius-sm", "6px"], ["--radius-md", "10px"], ["--radius-lg", "14px"], ["--radius-full", "9999px"],
  ["--text-xs", "12px"], ["--text-sm", "13px"], ["--text-md", "14px"], ["--text-base", "16px"],
  ["--text-lg", "20px"], ["--text-xl", "24px"], ["--text-2xl", "30px"], ["--space", "4px"],
];

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

  it("defines every themed token in all four blocks", () => {
    for (const b of [...dark, ...light]) for (const t of THEMED) expect(value(b, t), t).toBeTruthy();
  });

  it.each(SCALES)("%s is %s", (token, v) => expect(value(block(":root"), token)).toBe(v));

  it("zeroes motion and stops animations under prefers-reduced-motion", () => {
    const start = css.indexOf("@media (prefers-reduced-motion: reduce)");
    expect(start).toBeGreaterThanOrEqual(0);
    const rm = css.slice(start);
    for (const t of ["--duration-fast", "--duration-base", "--duration-slow"]) expect(value(rm, t)).toBe("0ms");
    expect(rm).toMatch(/animation: none !important/);
  });

  it("puts light under prefers-color-scheme and loads nothing external", () => {
    expect(css).toMatch(/@media \(prefers-color-scheme: light\)/);
    expect(css).not.toMatch(/@import|url\(|https?:/);
  });
});
