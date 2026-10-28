import { type ReactNode, useId, useState } from "react";

import { cx } from "./cx";

/** Shows `content` above its child on hover and keyboard focus; Escape hides
 * it. `describe` links it as the child's description; leave it off when the
 * child is already named by the same text (IconButton). */
export function Tooltip({ content, children, describe = true, side = "top" }: {
  content: ReactNode; children: ReactNode; describe?: boolean; side?: "top" | "bottom";
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-flex" aria-describedby={describe && open ? id : undefined}
          onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}
          onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
          onKeyDown={(e) => e.key === "Escape" && setOpen(false)}>
      {children}
      {open && (
        <span role="tooltip" id={id}
              className={cx("pointer-events-none absolute left-1/2 z-50 -translate-x-1/2 whitespace-nowrap rounded-sm",
                "bg-text px-2 py-1 text-xs font-medium text-bg shadow-md",
                side === "top" ? "bottom-full mb-1.5" : "top-full mt-1.5")}>
          {content}
        </span>
      )}
    </span>
  );
}
