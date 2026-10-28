import { type ReactNode, useId } from "react";

import { cx } from "./cx";

/** A raised surface. With a title it is a region named by it, with an
 * optional leading icon and an actions slot on the right of the header. */
export function Card({ title, icon, actions, children, className }: {
  title?: string; icon?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  const id = useId();
  return (
    <section aria-labelledby={title ? id : undefined}
             className={cx("rounded-lg border border-border bg-surface p-5 shadow-sm", className)}>
      {(title || actions) && (
        <header className="mb-4 flex items-center gap-2.5">
          {icon && <span aria-hidden="true" className="inline-flex text-text-dim [&>svg]:h-[18px] [&>svg]:w-[18px]">{icon}</span>}
          {title && <h2 id={id} className="min-w-0 flex-1 truncate text-md font-semibold text-text">{title}</h2>}
          {actions && <div className="ml-auto flex items-center gap-1">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}
