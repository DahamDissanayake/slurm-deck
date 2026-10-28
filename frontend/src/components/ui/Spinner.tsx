import { cx } from "./cx";

/** A turning ring. Announced as "Loading" unless `label` is null (decorative,
 * e.g. inside a busy button that says so itself). */
export function Spinner({ label = "Loading", className = "h-4 w-4" }: { label?: string | null; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" data-spinner
         role={label ? "status" : undefined} aria-label={label ?? undefined} aria-hidden={label ? undefined : true}
         className={cx("shrink-0 motion-safe:animate-spin", className)}>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" opacity="0.25" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}
