import type { Config } from "tailwindcss";

// Every colour, radius, shadow, type size and duration is a token from
// src/styles/tokens.css, never a literal.
const token = (name: string) => `var(--${name})`;
const size = (name: string, lineHeight: string) => [token(`text-${name}`), { lineHeight }] as [string, { lineHeight: string }];

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
      "border-strong": token("border-strong"),
      text: token("text"),
      "text-dim": token("text-dim"),
      accent: token("accent"),
      "accent-strong": token("accent-strong"),
      "accent-soft": token("accent-soft"),
      "accent-fg": token("accent-fg"),
      danger: token("danger"),
      "danger-soft": token("danger-soft"),
      warning: token("warning"),
      "warning-soft": token("warning-soft"),
      ok: token("ok"),
      "ok-soft": token("ok-soft"),
      info: token("info"),
      "info-soft": token("info-soft"),
      "neutral-soft": token("neutral-soft"),
    },
    fontFamily: {
      mono: token("font-mono"),
      sans: token("font-ui"),
    },
    extend: {
      fontSize: {
        xs: size("xs", "16px"),
        sm: size("sm", "18px"),
        md: size("md", "20px"),
        base: size("base", "24px"),
        lg: size("lg", "28px"),
        xl: size("xl", "32px"),
        "2xl": size("2xl", "36px"),
      },
      borderRadius: {
        sm: token("radius-sm"),
        md: token("radius-md"),
        lg: token("radius-lg"),
        full: token("radius-full"),
      },
      boxShadow: {
        sm: token("shadow-sm"),
        md: token("shadow-md"),
        lg: token("shadow-lg"),
      },
      transitionDuration: {
        fast: token("duration-fast"),
        base: token("duration-base"),
        slow: token("duration-slow"),
      },
      transitionTimingFunction: { out: token("ease-out") },
      keyframes: {
        "pulse-soft": { "0%, 100%": { opacity: "1" }, "50%": { opacity: "0.35" } },
        shimmer: { "0%, 100%": { opacity: "0.55" }, "50%": { opacity: "1" } },
        "toast-in": { from: { opacity: "0", transform: "translateY(8px)" }, to: { opacity: "1" } },
      },
      animation: {
        "pulse-soft": "pulse-soft 1.8s ease-in-out infinite",
        shimmer: "shimmer 1.4s ease-in-out infinite",
        "toast-in": `toast-in ${token("duration-base")} ${token("ease-out")}`,
      },
    },
  },
  plugins: [],
} satisfies Config;
