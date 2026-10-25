import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { duration, isLive, type JobInfo, jobs, stateLabel } from "../api/jobs";
import { Link } from "../app/navigation";
import { ExtendDialog } from "../components/ExtendDialog";
import { smallButton, StateChip } from "../components/JobCard";
import { LogViewer } from "../components/LogViewer";
import { OpenButton } from "../components/OpenButton";
import { Panel } from "../components/Panel";

const STEPS = ["Queued", "Starting", "Running", "Ended"] as const;

function Timeline({ state }: { state: string }) {
  const at = STEPS.indexOf(stateLabel(state));
  return (
    <ol className="flex gap-2 text-xs" aria-label="Job progress">
      {STEPS.map((s, i) => (
        <li key={s} aria-current={i === at ? "step" : undefined}
            className={`rounded-sm border px-2 py-1 ${i === at ? "border-accent text-accent"
              : i < at ? "border-border text-text" : "border-border text-text-dim"}`}>
          {s}
        </li>
      ))}
    </ol>
  );
}

/** One job: where it is, what it asked for, its script, why it failed, and its log. */
export function JobDetail({ id }: { id: string }) {
  const [job, setJob] = useState<JobInfo | null>(null);
  const [error, setError] = useState("");
  const [extending, setExtending] = useState(false);

  const load = useCallback(() => {
    jobs.get(id).then(setJob, (err) =>
      setError(err instanceof ApiError && err.message ? err.message : "Couldn't load this job."));
  }, [id]);
  useEffect(load, [load]);

  if (error) return <Panel title={`Job ${id}`}><p role="alert" className="text-danger">{error}</p></Panel>;
  if (!job) return <Panel title={`Job ${id}`}><p className="text-text-dim">Loading…</p></Panel>;
  const live = isLive(job.state);

  async function cancel() {
    if (!window.confirm(`Cancel job ${id}?`)) return;
    await jobs.cancel(id).catch((err) => setError(err instanceof ApiError ? err.message : "Cancelling failed."));
    load();
  }

  return (
    <div className="space-y-6">
      <Panel title={`Job ${id}`}>
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <StateChip state={job.state} />
          <Timeline state={job.state} />
          <div className="ml-auto flex gap-2">
            {live && job.session && <OpenButton jobId={id} />}
            {live && (
              <>
                <button type="button" className={smallButton} onClick={() => setExtending(true)}>Extend…</button>
                <button type="button" className={smallButton} onClick={cancel}>Cancel</button>
              </>
            )}
            <Link href={`/new?rerun=${id}`} className={smallButton}>Rerun</Link>
          </div>
        </div>
        {extending && live && (
          <ExtendDialog jobId={id} onClose={() => setExtending(false)}
                        onDone={() => { setExtending(false); load(); }} />
        )}
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm md:grid-cols-4">
          <dt className="text-text-dim">Node</dt><dd className="font-mono">{job.node || "—"}</dd>
          <dt className="text-text-dim">Time used</dt><dd>{duration(job.run_time_s)}</dd>
          <dt className="text-text-dim">Time limit</dt><dd>{duration(job.time_limit_s)}</dd>
          <dt className="text-text-dim">Exit code</dt><dd className="font-mono">{job.exit_code || "—"}</dd>
          <dt className="text-text-dim">Folder</dt><dd className="col-span-3 font-mono">{job.folder ?? job.work_dir}</dd>
        </dl>
        {job.explanation && (
          <p role="note" className="mt-4 rounded-sm border border-warning p-3 text-sm">{job.explanation}</p>
        )}
      </Panel>
      {job.script && (
        <Panel title="Script">
          <pre className="overflow-auto rounded-sm border border-border bg-bg p-3 font-mono text-xs">{job.script}</pre>
        </Panel>
      )}
      <Panel title="Log">
        <LogViewer jobId={id} running={live} />
      </Panel>
    </div>
  );
}
