import { useState } from "react";

import { ApiError } from "../api/client";
import { isLive, jobs, type QueueJob, stateLabel } from "../api/jobs";
import { Link } from "../app/navigation";
import { ExtendDialog } from "./ExtendDialog";

const CHIP = {
  Queued: "border-text-dim text-text-dim",
  Starting: "border-warning text-warning",
  Running: "border-ok text-ok",
  Ended: "border-border text-text-dim",
};

export const smallButton =
  "rounded-sm border border-border px-3 py-1 text-sm text-text hover:border-accent disabled:opacity-50";

export function StateChip({ state }: { state: string }) {
  const label = stateLabel(state);
  return (
    <span title={state} className={`rounded-sm border px-2 py-0.5 text-xs ${CHIP[label]}`}>
      {label}
    </span>
  );
}

/** One of my jobs: state, time, pods and what I can do with it. Extend and
 * Cancel only exist while the job is live. */
export function JobCard({ job }: { job: QueueJob }) {
  const [extending, setExtending] = useState(false);
  const [note, setNote] = useState("");
  const live = isLive(job.state);

  async function cancel() {
    if (!window.confirm(`Cancel job ${job.job_id}?`)) return;
    try {
      await jobs.cancel(job.job_id);
      setNote("Cancelled.");
    } catch (err) {
      setNote(err instanceof ApiError && err.message ? err.message : "Cancelling failed.");
    }
  }

  return (
    <article className="rounded-sm border border-border bg-surface-2 p-4">
      <header className="mb-2 flex items-center gap-3">
        <StateChip state={job.state} />
        <span className="font-mono text-sm">{job.name ?? job.job_id}</span>
        <span className="ml-auto text-xs text-text-dim">#{job.job_id}</span>
      </header>
      <p className="mb-3 text-sm text-text-dim">
        {job.time_used} of {job.time_limit} · {job.pods} pod{job.pods === 1 ? "" : "s"}
      </p>
      <div className="flex flex-wrap gap-2">
        <Link href={`/jobs/${job.job_id}`} className={smallButton}>Logs</Link>
        {live && (
          <>
            <button type="button" className={smallButton} onClick={() => setExtending(true)}>
              Extend…
            </button>
            <button type="button" className={smallButton} onClick={cancel}>Cancel</button>
          </>
        )}
        <Link href={`/new?rerun=${job.job_id}`} className={smallButton}>Rerun</Link>
      </div>
      {note && <p role="status" className="mt-2 text-sm">{note}</p>}
      {extending && live && (
        <ExtendDialog jobId={job.job_id} onClose={() => setExtending(false)}
                      onDone={() => { setExtending(false); setNote("Time added."); }} />
      )}
    </article>
  );
}
