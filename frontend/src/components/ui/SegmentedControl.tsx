import { type KeyboardEvent, type ReactNode, useRef } from "react";

import { cx, focusRing } from "./cx";

export type Segment<T extends string> = { value: T; label: string; icon?: ReactNode };

const STEP: Record<string, number> = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };

/** One choice out of a few, as a pill of segments (a radio group: Tab
 * enters at the chosen one, arrow keys move and choose). */
export function SegmentedControl<T extends string>({ label, options, value, onChange, className }: {
  label: string; options: Segment<T>[]; value: T; onChange: (value: T) => void; className?: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const current = Math.max(0, options.findIndex((o) => o.value === value));

  const onKeyDown = (e: KeyboardEvent, i: number) => {
    const step = STEP[e.key];
    if (!step) return;
    e.preventDefault();
    const j = (i + step + options.length) % options.length;
    onChange(options[j].value);
    refs.current[j]?.focus();
  };

  return (
    <div role="radiogroup" aria-label={label}
         className={cx("inline-flex items-center gap-0.5 rounded-full bg-surface-2 p-1", className)}>
      {options.map((o, i) => {
        const checked = o.value === value;
        return (
          <button key={o.value} ref={(el) => { refs.current[i] = el; }} type="button" role="radio"
                  aria-checked={checked} tabIndex={i === current ? 0 : -1}
                  onClick={() => onChange(o.value)} onKeyDown={(e) => onKeyDown(e, i)}
                  className={cx("inline-flex h-7 items-center gap-1.5 rounded-full px-3 text-sm font-medium",
                    "transition-colors duration-fast ease-out [&>svg]:h-4 [&>svg]:w-4", focusRing,
                    checked ? "bg-surface text-text shadow-sm" : "text-text-dim hover:text-text")}>
            {o.icon}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
