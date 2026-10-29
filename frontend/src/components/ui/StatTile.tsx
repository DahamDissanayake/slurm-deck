import type { ReactNode } from "react";

import { cx } from "./cx";
import { Meter, type MeterTone } from "./Meter";

/** One headline number: icon and label, the value, a line of context and
 * an optional bar or ring for how full it is. */
export function StatTile({ icon, label, value, sub, meter, className }: {
  icon?: ReactNode; label: string; value: ReactNode; sub?: ReactNode;
  meter?: { value: number; max?: number; kind?: "bar" | "ring"; tone?: MeterTone }; className?: string;
}) {
  const ring = meter?.kind === "ring";
  return (
    <div role="group" aria-label={label}
         className={cx("flex flex-col gap-3 rounded-lg border border-border bg-surface p-4 shadow-sm", className)}>
      <div className="flex items-center gap-2 text-sm text-text-dim">
        {icon && <span aria-hidden="true" className="inline-flex [&>svg]:h-4 [&>svg]:w-4">{icon}</span>}
        <span className="truncate">{label}</span>
      </div>
      <div className="flex items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xl font-semibold tabular-nums text-text">{value}</div>
          {sub && <div className="mt-0.5 truncate text-xs text-text-dim">{sub}</div>}
        </div>
        {ring && <Meter kind="ring" label={label} {...meter} />}
      </div>
      {meter && !ring && <Meter label={label} {...meter} />}
    </div>
  );
}
