import { useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { DAYS, type Totals, usage } from "../api/usage";
import { Card } from "../components/ui/Card";
import { BoltIcon, ChartIcon, ClockIcon, GpuIcon } from "../components/icons";
import { UsageTabs } from "../components/UsageTabs";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { Skeleton } from "../components/ui/Skeleton";
import { StatTile } from "../components/ui/StatTile";

export function StateBar({ counts }: { counts: Record<string, number> }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  if (total === 0) return <EmptyState icon={<ChartIcon />} title="No jobs in this period" className="py-6" />;
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-full bg-surface-2" role="img"
           aria-label="Jobs by state">
        {Object.entries(counts).map(([state, n]) => (
          <div key={state} title={`${state}: ${n}`} style={{ width: `${(n / total) * 100}%` }}
               className={state === "COMPLETED" ? "bg-ok" : state === "FAILED" ? "bg-danger"
                 : "bg-warning"} />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 text-sm text-text-dim">
        {Object.entries(counts).map(([state, n]) => <li key={state}>{state}: {n}</li>)}
      </ul>
    </div>
  );
}

/** My GPU-hours, CPU-hours and jobs over the last 7, 30 or 90 days. */
export function Usage() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<Totals | null>(null);
  const [error, setError] = useState("");

  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    setData(null);
    setError("");
    usage.personal(days).then(setData, (e) =>
      setError(e instanceof ApiError && e.message ? e.message : "Couldn't load your usage."));
  }, [days, attempt]);

  const jobs = data ? Object.values(data.jobs_by_state).reduce((a, b) => a + b, 0) : 0;
  return (
    <Card title="Usage">
      <UsageTabs />
      <label className="mb-4 block text-sm text-text-dim">Period
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}
                className="ml-2 h-8 rounded-md border border-border bg-surface px-2 text-text hover:border-border-strong">
          {DAYS.map((d) => <option key={d} value={d}>Last {d} days</option>)}
        </select>
      </label>
      {error && <ErrorState title="Couldn't load your usage" error={error} onRetry={() => setAttempt((n) => n + 1)} />}
      {!data && !error && <Skeleton variant="tile" count={3} label="Loading usage" />}
      {data && (
        <>
          <div className="mb-6 grid gap-3 sm:grid-cols-3">
            <StatTile icon={<GpuIcon />} label="GPU-hours" value={data.gpu_hours.toFixed(1)} />
            <StatTile icon={<ClockIcon />} label="CPU-hours" value={data.cpu_hours.toFixed(1)} />
            <StatTile icon={<BoltIcon />} label="Jobs" value={String(jobs)} />
          </div>
          <StateBar counts={data.jobs_by_state} />
        </>
      )}
    </Card>
  );
}
