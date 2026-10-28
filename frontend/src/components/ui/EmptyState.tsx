import type { ReactNode } from "react";

import { cx } from "./cx";

export const stateIcon = "inline-flex h-12 w-12 items-center justify-center rounded-full [&>svg]:h-6 [&>svg]:w-6";

/** Nothing here yet: an icon, one line saying so, and what to do about it. */
export function EmptyState({ icon, title, children, action, className }: {
  icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode; className?: string;
}) {
  return (
    <div className={cx("flex flex-col items-center gap-3 px-6 py-12 text-center", className)}>
      {icon && <span aria-hidden="true" className={cx(stateIcon, "bg-accent-soft text-accent")}>{icon}</span>}
      <h3 className="text-base font-semibold text-text">{title}</h3>
      {children && <p className="max-w-sm text-md text-text-dim">{children}</p>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}
