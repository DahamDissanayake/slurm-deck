import { type ReactNode, useId } from "react";

/** The primary container: a surface with the TUI's double-ruled top edge. */
export function Panel({ title, children, className = "" }: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  const id = useId();
  return (
    <section
      aria-labelledby={title ? id : undefined}
      className={`rounded-sm border border-border border-t-4 border-double border-t-accent bg-surface p-6 ${className}`}
    >
      {title && (
        <h2 id={id} className="mb-4 font-mono text-sm uppercase tracking-widest text-text-dim">
          {title}
        </h2>
      )}
      {children}
    </section>
  );
}
