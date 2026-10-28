import type { ReactNode } from "react";

import { cx } from "./cx";

export type MeterTone = "auto" | "accent" | "ok" | "warning" | "danger";
const FILL = { accent: "bg-accent", ok: "bg-ok", warning: "bg-warning", danger: "bg-danger" };
const STROKE = { accent: "stroke-accent", ok: "stroke-ok", warning: "stroke-warning", danger: "stroke-danger" };

/** "auto" turns warning from 75% full and danger from 90%. */
const pick = (tone: MeterTone, pct: number) =>
  tone !== "auto" ? tone : pct >= 90 ? "danger" : pct >= 75 ? "warning" : "accent";

/** A value out of `max` as a thin bar or a ring; `children` sit in the ring's centre. */
export function Meter({ label, value, max = 100, kind = "bar", tone = "auto", size = 40, children, className }: {
  label: string; value: number; max?: number; kind?: "bar" | "ring"; tone?: MeterTone;
  size?: number; children?: ReactNode; className?: string;
}) {
  const pct = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  const t = pick(tone, pct);
  const aria = { role: "meter", "aria-label": label, "aria-valuenow": value, "aria-valuemin": 0, "aria-valuemax": max };
  if (kind === "bar") {
    return (
      <div {...aria} className={cx("h-1.5 w-full overflow-hidden rounded-full bg-surface-2", className)}>
        <div data-fill style={{ width: `${pct}%` }}
             className={cx("h-full rounded-full transition-[width] duration-slow ease-out", FILL[t])} />
      </div>
    );
  }
  const r = 15.5;
  const c = 2 * Math.PI * r;
  return (
    <div {...aria} className={cx("relative inline-grid shrink-0 place-items-center", className)}
         style={{ width: size, height: size }}>
      <svg viewBox="0 0 36 36" className="absolute inset-0 -rotate-90" aria-hidden="true">
        <circle cx="18" cy="18" r={r} fill="none" strokeWidth="3" className="stroke-surface-2" />
        <circle data-fill cx="18" cy="18" r={r} fill="none" strokeWidth="3" strokeLinecap="round"
                strokeDasharray={c} strokeDashoffset={c * (1 - pct / 100)}
                className={cx("transition-[stroke-dashoffset] duration-slow ease-out", STROKE[t])} />
      </svg>
      {children && <span className="relative text-xs font-semibold tabular-nums text-text">{children}</span>}
    </div>
  );
}
