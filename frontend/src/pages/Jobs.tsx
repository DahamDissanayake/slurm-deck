import { useEffect, useState } from "react";

import { jobs as api, type QueueJob } from "../api/jobs";
import { useLive } from "../api/live";
import { Link } from "../app/navigation";
import { JobCard, smallButton, StateChip } from "../components/JobCard";
import { Panel } from "../components/Panel";

type Tab = "queue" | "mine" | "history";
const STATES = ["", "COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY"];

function Table({ rows, rerun }: { rows: QueueJob[]; rerun?: boolean }) {
  if (rows.length === 0) return <p className="text-sm text-text-dim">Nothing here.</p>;
  return (
    <table className="w-full text-left text-sm">
      <thead className="text-text-dim">
        <tr><th>Job</th><th>User</th><th>State</th><th>Pods</th><th>Time</th><th /></tr>
      </thead>
      <tbody>
        {rows.map((j) => (
          <tr key={j.job_id} className="border-t border-border">
            <td className="py-2 font-mono">
              {j.name ? <Link href={`/jobs/${j.job_id}`} className="text-accent">{j.name}</Link>
                : `#${j.job_id}`}
            </td>
            <td>{j.user}</td>
            <td><StateChip state={j.state} /></td>
            <td>{j.pods}</td>
            <td>{j.time_used} / {j.time_limit}</td>
            <td>{rerun && <Link href={`/new?rerun=${j.job_id}`} className={smallButton}>Rerun</Link>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function History() {
  const [days, setDays] = useState(30);
  const [state, setState] = useState("");
  const [rows, setRows] = useState<QueueJob[] | null>(null);
  useEffect(() => {
    setRows(null);
    api.history(days, state).then(setRows, () => setRows([]));
  }, [days, state]);
  const select = "ml-2 rounded-sm border border-border bg-surface-2 px-2 py-1 text-text";
  return (
    <>
      <div className="mb-4 flex gap-4 text-sm">
        <label>Last
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} className={select}>
            {[7, 30, 90].map((d) => <option key={d} value={d}>{d} days</option>)}
          </select>
        </label>
        <label>State
          <select value={state} onChange={(e) => setState(e.target.value)} className={select}>
            {STATES.map((s) => <option key={s} value={s}>{s || "Any"}</option>)}
          </select>
        </label>
      </div>
      {rows === null ? <p className="text-sm text-text-dim">Loading…</p> : <Table rows={rows} rerun />}
    </>
  );
}

/** Jobs: the whole queue (other people's job names hidden), mine, and my history. */
export function Jobs() {
  const [tab, setTab] = useState<Tab>("queue");
  const { cluster, jobs } = useLive();
  return (
    <Panel title="Jobs">
      <div role="tablist" className="mb-4 flex gap-4 border-b border-border text-sm">
        {(["queue", "mine", "history"] as const).map((t) => (
          <button key={t} role="tab" type="button" aria-selected={tab === t} onClick={() => setTab(t)}
                  className={`-mb-px border-b-2 px-1 pb-2 ${tab === t
                    ? "border-accent text-accent" : "border-transparent text-text-dim"}`}>
            {t === "queue" ? "Queue" : t === "mine" ? "Mine" : "History"}
          </button>
        ))}
      </div>
      {tab === "queue" && <Table rows={cluster?.queue ?? []} />}
      {tab === "mine" && (
        <div className="grid gap-3 md:grid-cols-2">
          {(jobs ?? []).map((j) => <JobCard key={j.job_id} job={j} />)}
        </div>
      )}
      {tab === "history" && <History />}
    </Panel>
  );
}
