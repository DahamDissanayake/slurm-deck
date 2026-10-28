import { cx } from "./cx";

const BONES = {
  line: "h-3 rounded-full odd:w-full even:w-4/5",
  tile: "h-24 rounded-lg",
  row: "h-10 rounded-md",
};

/** Placeholder shapes while something loads, announced once as `label`. */
export function Skeleton({ variant = "line", count = 3, label = "Loading", className }: {
  variant?: keyof typeof BONES; count?: number; label?: string; className?: string;
}) {
  return (
    <div role="status" aria-label={label}
         className={cx(variant === "tile" ? "grid grid-cols-[repeat(auto-fill,minmax(12rem,1fr))] gap-4"
           : "flex flex-col gap-2.5", className)}>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} data-bone aria-hidden="true"
             className={cx("bg-surface-2 motion-safe:animate-shimmer", BONES[variant])} />
      ))}
    </div>
  );
}
