import { useCallback, useState } from "react";

import { ApiError } from "../../api/client";
import { cluster } from "../../api/cluster";
import { isLive, jobs, type QueueJob } from "../../api/jobs";
import { usePolled } from "../../api/poll";
import { Link } from "../../app/navigation";
import { StateChip } from "../../components/JobCard";
import { Panel } from "../../components/Panel";
import { smallButton } from "./AdminLayout";

type Tab = "queue" | "history";

/** Everyone's jobs: the live queue and the history. An admin can cancel any job. */
export function JobsAdmin() {
  const [tab, setTab] = useState<Tab>("queue");
  const [error, setError] = useState("");
  const load = useCallback(() => (tab === "queue" ? cluster.queue() : cluster.history(30)), [tab]);
  const { data, failed } = usePolled<QueueJob[]>(load, 5000);

  async function cancel(j: QueueJob) {
    if (!window.confirm(`Cancel job ${j.job_id} (${j.user})?`)) return;
    try {
      await jobs.cancel(j.job_id);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError && e.message ? e.message : "Cancelling failed.");
    }
  }

  return (
    <Panel title="Jobs">
      <div role="tablist" className="mb-4 flex gap-4 border-b border-border text-sm">
        {(["queue", "history"] as const).map((t) => (
          <button key={t} role="tab" type="button" aria-selected={tab === t} onClick={() => setTab(t)}
                  className={`-mb-px border-b-2 px-1 pb-2 ${tab === t
                    ? "border-accent text-accent" : "border-transparent text-text-dim"}`}>
            {t === "queue" ? "Queue" : "History (30 days)"}
          </button>
        ))}
      </div>
      {(error || failed) && <p role="alert" className="mb-2 text-danger">{error || "Couldn't load jobs."}</p>}
      <table className="w-full text-left text-sm">
        <thead className="text-text-dim">
          <tr><th>Job</th><th>User</th><th>State</th><th>Pods</th><th>Time</th><th /></tr>
        </thead>
        <tbody>
          {(data ?? []).map((j) => (
            <tr key={j.job_id} className="border-t border-border">
              <td className="py-2 font-mono">
                <Link href={`/jobs/${j.job_id}`} className="text-accent">{j.name ?? `#${j.job_id}`}</Link>
              </td>
              <td>{j.user}</td><td><StateChip state={j.state} /></td><td>{j.pods}</td>
              <td>{j.time_used} / {j.time_limit}</td>
              <td>{isLive(j.state) && (
                <button type="button" className={smallButton} onClick={() => cancel(j)}>Cancel</button>)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}
