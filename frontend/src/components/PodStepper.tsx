import { PlusIcon } from "./icons";
import { IconButton } from "./ui/IconButton";

const MinusIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
    <path d="M5 12h14" />
  </svg>
);

/** Choose how many GPU pods to ask for, with how many are free right now. */
export function PodStepper({ value, max, free, total, onChange }: {
  value: number; max: number; free: number | null; total: number | null;
  onChange: (pods: number) => void;
}) {
  return (
    <div className="flex items-center gap-3">
      <IconButton label="Fewer pods" variant="secondary" size="sm" icon={<MinusIcon />}
                  disabled={value <= 1} onClick={() => onChange(value - 1)} />
      <output aria-label="Pods" className="w-8 text-center font-mono text-lg">{value}</output>
      <IconButton label="More pods" variant="secondary" size="sm" icon={<PlusIcon />}
                  disabled={value >= max} onClick={() => onChange(value + 1)} />
      {free != null && total != null && (
        <span className="text-sm text-text-dim">{free} of {total} free</span>
      )}
    </div>
  );
}
