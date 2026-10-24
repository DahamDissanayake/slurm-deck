/** One block per GPU pod: filled for pods in use. */
export function PodBlocks({ used, total }: { used: number; total: number }) {
  return (
    <div role="img" aria-label={`${used} of ${total} pods in use`} className="flex gap-1">
      {Array.from({ length: total }, (_, i) => (
        <span key={i}
              className={`h-4 w-4 rounded-sm border ${i < used
                ? "border-accent bg-accent" : "border-border bg-surface-2"}`} />
      ))}
    </div>
  );
}
