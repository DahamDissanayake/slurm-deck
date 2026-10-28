const step = "h-8 w-8 rounded-sm border border-border text-lg disabled:opacity-40";

/** Choose how many GPU pods to ask for, with how many are free right now. */
export function PodStepper({ value, max, free, total, onChange }: {
  value: number; max: number; free: number | null; total: number | null;
  onChange: (pods: number) => void;
}) {
  return (
    <div className="flex items-center gap-3">
      <button type="button" aria-label="Fewer pods" className={step} disabled={value <= 1}
              onClick={() => onChange(value - 1)}>−</button>
      <output aria-label="Pods" className="w-8 text-center font-mono text-lg">{value}</output>
      <button type="button" aria-label="More pods" className={step} disabled={value >= max}
              onClick={() => onChange(value + 1)}>+</button>
      {free != null && total != null && (
        <span className="text-sm text-text-dim">{free} of {total} free</span>
      )}
    </div>
  );
}
