import { useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { DAYS, type Totals, usage } from "../api/usage";
import { Panel } from "../components/Panel";
import { UsageTabs } from "../components/UsageTabs";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-sm border border-border bg-surface-2 p-4">
      <div className="text-2xl font-semibold">{value}</div>
      <div className="text-sm text-text-dim">{label}</div>
    </div>
  );
}

/** A bar split by job state, with the counts beside it. */
export function StateBar({ counts }: { counts: Record<string, number> }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  if (total === 0) return <p className="text-sm text-text-dim">No jobs in this period.</p>;
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-sm border border-border" role="img"
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

  useEffect(() => {
    setData(null);
    setError("");
    usage.personal(days).then(setData, (e) =>
      setError(e instanceof ApiError && e.message ? e.message : "Couldn't load your usage."));
  }, [days]);

  const jobs = data ? Object.values(data.jobs_by_state).reduce((a, b) => a + b, 0) : 0;
  return (
    <Panel title="Usage">
      <UsageTabs />
      <label className="mb-4 block text-sm text-text-dim">Period
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}
                className="ml-2 rounded-sm border border-border bg-surface-2 px-2 py-1 text-text">
          {DAYS.map((d) => <option key={d} value={d}>Last {d} days</option>)}
        </select>
      </label>
      {error && <p role="alert" className="text-danger">{error}</p>}
      {!data && !error && <p className="text-text-dim">Loading…</p>}
      {data && (
        <>
          <div className="mb-6 grid gap-3 sm:grid-cols-3">
            <Stat label="GPU-hours" value={data.gpu_hours.toFixed(1)} />
            <Stat label="CPU-hours" value={data.cpu_hours.toFixed(1)} />
            <Stat label="Jobs" value={String(jobs)} />
          </div>
          <StateBar counts={data.jobs_by_state} />
        </>
      )}
    </Panel>
  );
}
