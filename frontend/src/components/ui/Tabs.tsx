import { type KeyboardEvent, type ReactNode, useId, useRef } from "react";

import { cx, focusRing } from "./cx";

export type Tab<T extends string> = { value: T; label: string; icon?: ReactNode };

/** Tabs over one panel (a tablist: Tab enters at the chosen tab, arrow keys,
 * Home and End move and choose). `children` is the chosen tab's panel. */
export function Tabs<T extends string>({ label, tabs, value, onChange, children, className }: {
  label: string; tabs: Tab<T>[]; value: T; onChange: (value: T) => void; children: ReactNode; className?: string;
}) {
  const base = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const current = Math.max(0, tabs.findIndex((t) => t.value === value));
  const tabId = (v: string) => `${base}-tab-${v}`;
  const panelId = `${base}-panel`;

  const onKeyDown = (e: KeyboardEvent, i: number) => {
    const n = tabs.length;
    const to = { ArrowRight: (i + 1) % n, ArrowLeft: (i - 1 + n) % n, Home: 0, End: n - 1 }[e.key];
    if (to === undefined) return;
    e.preventDefault();
    onChange(tabs[to].value);
    refs.current[to]?.focus();
  };

  return (
    <div className={className}>
      <div role="tablist" aria-label={label} className="mb-4 flex gap-1 overflow-x-auto border-b border-border">
        {tabs.map((t, i) => {
          const selected = i === current;
          return (
            <button key={t.value} ref={(el) => { refs.current[i] = el; }} id={tabId(t.value)} type="button"
                    role="tab" aria-selected={selected} aria-controls={selected ? panelId : undefined}
                    tabIndex={selected ? 0 : -1} onClick={() => onChange(t.value)} onKeyDown={(e) => onKeyDown(e, i)}
                    className={cx("-mb-px inline-flex h-10 items-center gap-2 whitespace-nowrap border-b-2 px-3 text-md font-medium",
                      "transition-colors duration-fast ease-out [&>svg]:h-4 [&>svg]:w-4", focusRing,
                      selected ? "border-accent text-text" : "border-transparent text-text-dim hover:text-text")}>
              {t.icon}
              {t.label}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" id={panelId} aria-labelledby={tabId(tabs[current]?.value ?? "")}>{children}</div>
    </div>
  );
}
