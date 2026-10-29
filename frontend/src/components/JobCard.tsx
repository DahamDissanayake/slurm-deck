import { type ReactNode, useState } from "react";

import { ApiError } from "../api/client";
import { clockSeconds, compact, isLive, jobs, type QueueJob, stateLabel } from "../api/jobs";
import { isSession } from "../api/sessions";
import { ClockIcon, FileTextIcon, GpuIcon, PlusIcon, RefreshIcon, XIcon } from "./icons";
import { small as smallButton } from "./controls";
import { ExtendDialog } from "./ExtendDialog";
import { OpenButton } from "./OpenButton";
import { IconButton } from "./ui/IconButton";
import { IconLink } from "./ui/IconLink";
import { Meter } from "./ui/Meter";
import { StatusBadge } from "./ui/StatusBadge";
import { useToast } from "./ui/Toast";

const CHIP = {
  Queued: "border-text-dim text-text-dim",
  Starting: "border-warning text-warning",
  Running: "border-ok text-ok",
  Ended: "border-border text-text-dim",
};

export { smallButton };

/** The four-word state chip the admin and services pages still use; new UI
 * uses StatusBadge. */
export function StateChip({ state }: { state: string }) {
  const label = stateLabel(state);
  return (
    <span title={state} className={`rounded-sm border px-2 py-0.5 text-xs ${CHIP[label]}`}>
      {label}
    </span>
  );
}

/** A small icon + text fact about a job, such as its pods or time used. */
export function Chip({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-2.5 py-1 text-xs text-text-dim">
      <span aria-hidden="true" className="inline-flex [&>svg]:h-3.5 [&>svg]:w-3.5">{icon}</span>
      {children}
    </span>
  );
}

/** How much of its time limit a live job has left, as a ring. */
export function TimeLeft({ job }: { job: QueueJob }) {
  const limit = clockSeconds(job.time_limit);
  if (!isLive(job.state) || job.time_left_s == null || !limit) return null;
  return (
    <Meter kind="ring" label={`Time left for job ${job.job_id}`} value={job.time_left_s} max={limit}
           tone="auto" size={44}>
      {compact(job.time_left_s)}
    </Meter>
  );
}

/** One of my jobs: state, time, pods and what I can do with it. Extend and
 * Cancel only exist while the job is live. */
export function JobCard({ job }: { job: QueueJob }) {
  const [extending, setExtending] = useState(false);
  const toast = useToast();
  const live = isLive(job.state);

  async function cancel() {
    if (!window.confirm(`Cancel job ${job.job_id}?`)) return;
    try {
      await jobs.cancel(job.job_id);
      toast({ tone: "ok", message: `Job ${job.job_id} cancelled.` });
    } catch (err) {
      toast({ tone: "danger", message: err instanceof ApiError && err.message ? err.message : "Cancelling failed." });
    }
  }

  return (
    <article className="rounded-lg border border-border bg-surface p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <TimeLeft job={job} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate font-mono text-md font-semibold text-text">{job.name ?? job.job_id}</h3>
            <StatusBadge state={job.state} />
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Chip icon={<GpuIcon />}>{job.pods} pod{job.pods === 1 ? "" : "s"}</Chip>
            <Chip icon={<ClockIcon />}>{job.time_used} of {job.time_limit}</Chip>
            <Chip icon={<span className="text-xs font-semibold">#</span>}>{job.job_id}</Chip>
          </div>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-1 border-t border-border pt-3">
        {live && isSession(job.kind) && <OpenButton jobId={job.job_id} />}
        <IconLink href={`/jobs/${job.job_id}`} label="Logs" icon={<FileTextIcon />} size="sm" />
        {live && <IconButton label="Extend time" icon={<PlusIcon />} size="sm" onClick={() => setExtending(true)} />}
        {live && <IconButton label="Cancel" icon={<XIcon />} size="sm" onClick={cancel} />}
        <IconLink href={`/new?rerun=${job.job_id}`} label="Rerun" icon={<RefreshIcon />} size="sm" />
      </div>
      {extending && live && (
        <ExtendDialog jobId={job.job_id} onClose={() => setExtending(false)}
                      onDone={() => { setExtending(false); toast({ tone: "ok", message: "Time added." }); }} />
      )}
    </article>
  );
}
