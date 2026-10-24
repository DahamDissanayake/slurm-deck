import { useState } from "react";

const KEY = "sd-theme";
type Theme = "light" | "dark";

// Storage can throw (private windows, blocked site data): the theme still
// switches, it just isn't remembered.
function stored(): Theme | null {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

function remember(theme: Theme) {
  try {
    window.localStorage.setItem(KEY, theme);
  } catch {
    /* not remembered */
  }
}

/** Apply the remembered choice, if any, before the first render. */
export function applyStoredTheme() {
  const theme = stored();
  if (theme) document.documentElement.dataset.theme = theme;
}

function current(): Theme {
  const set = document.documentElement.dataset.theme;
  if (set === "light" || set === "dark") return set;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(current);
  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      className="rounded-sm border border-border px-2 py-1 text-sm text-text-dim hover:text-text"
      onClick={() => {
        document.documentElement.dataset.theme = next;
        remember(next);
        setTheme(next);
      }}
    >
      {next === "light" ? "Light theme" : "Dark theme"}
    </button>
  );
}
