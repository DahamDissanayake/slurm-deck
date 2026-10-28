import { type KeyboardEvent, type ReactNode, useEffect, useId, useRef, useState } from "react";

import { MoreIcon } from "../icons";
import { cx, focusRing } from "./cx";
import { IconButton } from "./IconButton";

export type MenuItem = { label: string; icon?: ReactNode; onSelect: () => void; danger?: boolean; disabled?: boolean };

const ITEM = "[role=menuitem]:not([disabled])";

/** A dropdown of actions behind an icon button named `label`. Arrow keys,
 * Home and End move between items, Escape closes and returns focus, a click
 * outside closes. */
export function Menu({ label, items, icon = <MoreIcon />, align = "end" }: {
  label: string; items: MenuItem[]; icon?: ReactNode; align?: "start" | "end";
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    list.current?.querySelector<HTMLElement>(ITEM)?.focus();
    const away = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  const close = () => { setOpen(false); trigger.current?.focus(); };

  const onKeyDown = (e: KeyboardEvent) => {
    const enabled = Array.from(list.current?.querySelectorAll<HTMLElement>(ITEM) ?? []);
    const i = enabled.indexOf(document.activeElement as HTMLElement);
    const n = enabled.length;
    const to = { ArrowDown: (i + 1) % n, ArrowUp: (i - 1 + n) % n, Home: 0, End: n - 1 }[e.key];
    if (to !== undefined) { e.preventDefault(); enabled[to]?.focus(); }
    else if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "Tab") setOpen(false);
  };

  return (
    <div ref={wrap} className="relative inline-flex">
      <IconButton ref={trigger} label={label} icon={icon} aria-haspopup="menu" aria-expanded={open}
                  aria-controls={open ? id : undefined} onClick={() => setOpen((o) => !o)} />
      {open && (
        <div ref={list} id={id} role="menu" aria-label={label} onKeyDown={onKeyDown}
             className={cx("absolute top-full z-40 mt-1 min-w-44 rounded-md border border-border bg-surface p-1 shadow-lg",
               align === "end" ? "right-0" : "left-0")}>
          {items.map((item) => (
            <button key={item.label} type="button" role="menuitem" tabIndex={-1} disabled={item.disabled}
                    onClick={() => { close(); item.onSelect(); }}
                    className={cx("flex w-full items-center gap-2 rounded-sm px-2.5 py-1.5 text-left text-md",
                      "disabled:cursor-not-allowed disabled:opacity-50 [&>svg]:h-4 [&>svg]:w-4", focusRing,
                      item.danger ? "text-danger hover:bg-danger-soft focus:bg-danger-soft"
                        : "text-text hover:bg-surface-2 focus:bg-surface-2")}>
              {item.icon}
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
