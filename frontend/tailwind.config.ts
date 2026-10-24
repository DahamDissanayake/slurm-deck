import type { Config } from "tailwindcss";

// Every colour is a token from src/styles/tokens.css, never a literal.
const token = (name: string) => `var(--${name})`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    colors: {
      transparent: "transparent",
      current: "currentColor",
      bg: token("bg"),
      surface: token("surface"),
      "surface-2": token("surface-2"),
      border: token("border"),
      text: token("text"),
      "text-dim": token("text-dim"),
      accent: token("accent"),
      danger: token("danger"),
      warning: token("warning"),
      ok: token("ok"),
    },
    fontFamily: {
      mono: token("font-mono"),
      sans: token("font-ui"),
    },
  },
  plugins: [],
} satisfies Config;
