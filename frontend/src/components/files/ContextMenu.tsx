import { type KeyboardEvent, useEffect, useRef } from "react";

import { cx, focusRing } from "../ui/cx";
import type { FileAction } from "./actions";

const ITEM = "[role=menuitem]";

/** The right-click menu for a file row, at the pointer. Arrow keys, Home and
 * End move, Escape or a click elsewhere closes it. */
export function ContextMenu({ x, y, label, items, onSelect, onClose }: {
  x: number; y: number; label: string; items: FileAction[]; onSelect: (id: FileAction["id"]) => void; onClose: () => void;
}) {
  const list = useRef<HTMLDivElement>(null);

  useEffect(() => {
    list.current?.querySelector<HTMLElement>(ITEM)?.focus();
    const away = (e: MouseEvent) => { if (!list.current?.contains(e.target as Node)) onClose(); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [onClose]);

  const onKeyDown = (e: KeyboardEvent) => {
    const enabled = Array.from(list.current?.querySelectorAll<HTMLElement>(ITEM) ?? []);
    const i = enabled.indexOf(document.activeElement as HTMLElement);
    const n = enabled.length;
    const to = { ArrowDown: (i + 1) % n, ArrowUp: (i - 1 + n) % n, Home: 0, End: n - 1 }[e.key];
    if (to !== undefined) { e.preventDefault(); enabled[to]?.focus(); }
    else if (e.key === "Escape" || e.key === "Tab") { e.preventDefault(); onClose(); }
  };

  return (
    <div ref={list} role="menu" aria-label={label} onKeyDown={onKeyDown} style={{ left: x, top: y }}
         className="fixed z-50 min-w-44 rounded-md border border-border bg-surface p-1 shadow-lg">
      {items.map((item) => (
        <button key={item.id} type="button" role="menuitem" tabIndex={-1}
                onClick={() => { onClose(); onSelect(item.id); }}
                className={cx("flex w-full items-center gap-2 rounded-sm px-2.5 py-1.5 text-left text-md [&>svg]:h-4 [&>svg]:w-4",
                  focusRing, item.danger ? "text-danger hover:bg-danger-soft focus:bg-danger-soft"
                    : "text-text hover:bg-surface-2 focus:bg-surface-2")}>
          {item.icon}
          {item.label}
        </button>
      ))}
    </div>
  );
}
