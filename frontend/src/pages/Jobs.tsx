import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { isLive, jobs as api, type QueueJob, stateLabel } from "../api/jobs";
import { useLive } from "../api/live";
import { Link } from "../app/navigation";
import { ExtendDialog } from "../components/ExtendDialog";
import { ClockIcon, FileTextIcon, GpuIcon, JobsIcon, PlusIcon, RefreshIcon, XIcon } from "../components/icons";
import { Chip } from "../components/JobCard";
import { buttonClass } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { cx } from "../components/ui/cx";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { IconLink } from "../components/ui/IconLink";
import { Menu } from "../components/ui/Menu";
import { SegmentedControl } from "../components/ui/SegmentedControl";
import { Skeleton } from "../components/ui/Skeleton";
import { StatusBadge } from "../components/ui/StatusBadge";
import { useToast } from "../components/ui/Toast";

type Filter = "all" | "running" | "pending" | "finished";
type Scope = "everyone" | "mine";

const FILTERS = [{ value: "all", label: "All" }, { value: "running", label: "Running" },
                 { value: "pending", label: "Pending" }, { value: "finished", label: "Finished" }] as const;
const SCOPES = [{ value: "everyone", label: "Everyone" }, { value: "mine", label: "Mine" }] as const;
const OUTCOMES = ["", "COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY"];
const select = "h-8 rounded-md border border-border bg-surface px-2 text-md text-text";

const matches = (filter: Filter, state: string) => {
  const label = stateLabel(state);
  return filter === "all" || (filter === "running" ? label === "Running"
    : label === "Queued" || label === "Starting");
};

/** One job: its name and owner, state, resources, and (for my jobs) what I can do. */
function JobRow({ job, mine }: { job: QueueJob; mine: boolean }) {
  const [extending, setExtending] = useState(false);
  const toast = useToast();
  const live = isLive(job.state);

  async function cancel() {
    if (!window.confirm(`Cancel job ${job.job_id}?`)) return;
    try {
      await api.cancel(job.job_id);
      toast({ tone: "ok", message: `Job ${job.job_id} cancelled.` });
    } catch (err) {
      toast({ tone: "danger", message: err instanceof ApiError && err.message ? err.message : "Cancelling failed." });
    }
  }

  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1 basis-48">
          <div className="truncate font-mono text-md font-medium text-text">
            {job.name ? <Link href={`/jobs/${job.job_id}`} className="hover:text-accent hover:underline">{job.name}</Link>
              : `#${job.job_id}`}
          </div>
          <div className="text-xs text-text-dim">{job.user}</div>
        </div>
        <StatusBadge state={job.state} />
        <div className="flex flex-wrap gap-1.5">
          <Chip icon={<GpuIcon />}>{job.pods} pod{job.pods === 1 ? "" : "s"}</Chip>
          <Chip icon={<ClockIcon />}>{job.time_used} of {job.time_limit}</Chip>
        </div>
        {mine && (
          <div className="flex items-center gap-0.5">
            <IconLink href={`/jobs/${job.job_id}`} label="Logs" icon={<FileTextIcon />} size="sm" />
            <IconLink href={`/new?rerun=${job.job_id}`} label="Rerun" icon={<RefreshIcon />} size="sm" />
            {live && (
              <Menu label={`More actions for job ${job.job_id}`}
                    items={[{ label: "Extend time", icon: <PlusIcon />, onSelect: () => setExtending(true) },
                            { label: "Cancel job", icon: <XIcon />, danger: true, onSelect: cancel }]} />
            )}
          </div>
        )}
      </div>
      {extending && live && (
        <ExtendDialog jobId={job.job_id} onClose={() => setExtending(false)}
                      onDone={() => { setExtending(false); toast({ tone: "ok", message: "Time added." }); }} />
      )}
    </li>
  );
}

function List({ rows, mineIds, empty }: { rows: QueueJob[]; mineIds: Set<string>; empty: string }) {
  if (rows.length === 0) {
    return <EmptyState icon={<JobsIcon />} title="No jobs here"
                       action={<Link href="/new" className={buttonClass({ pill: true })}>Start a job</Link>}>{empty}</EmptyState>;
  }
  return (
    <ul className="divide-y divide-border rounded-md border border-border">
      {rows.map((j) => <JobRow key={j.job_id} job={j} mine={mineIds.has(j.job_id)} />)}
    </ul>
  );
}

/** My finished jobs over a period, loaded from the accounting history. */
function Finished() {
  const [days, setDays] = useState(30);
  const [outcome, setOutcome] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [rows, setRows] = useState<QueueJob[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let stale = false;
    setRows(null);
    setError(null);
    api.history(days, outcome).then((r) => { if (!stale) setRows(r); }, (e) => { if (!stale) setError(e); });
    return () => { stale = true; };
  }, [days, outcome, attempt]);

  const retry = useCallback(() => setAttempt((a) => a + 1), []);
  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-4 text-md text-text-dim">
        <label className="flex items-center gap-2">Period
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} className={select}>
            {[7, 30, 90].map((d) => <option key={d} value={d}>Last {d} days</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2">Outcome
          <select value={outcome} onChange={(e) => setOutcome(e.target.value)} className={select}>
            {OUTCOMES.map((s) => <option key={s} value={s}>{s ? s.charAt(0) + s.slice(1).toLowerCase().replace(/_/g, " ") : "Any"}</option>)}
          </select>
        </label>
      </div>
      {error ? <ErrorState title="Couldn't load your finished jobs" error={error} onRetry={retry} />
        : rows === null ? <Skeleton variant="row" count={4} label="Loading jobs" />
          : <List rows={rows} mineIds={new Set(rows.map((r) => r.job_id))}
                  empty="Nothing finished in this period." />}
    </>
  );
}

/** Jobs: the whole queue (other people's job names hidden), my live jobs, and my finished ones. */
export function Jobs() {
  const [filter, setFilter] = useState<Filter>("all");
  const [scope, setScope] = useState<Scope>("everyone");
  const { cluster, jobs } = useLive();
  const mineIds = new Set((jobs ?? []).map((j) => j.job_id));
  const source = scope === "mine" ? jobs : cluster?.queue ?? null;
  const rows = (source ?? []).filter((j) => matches(filter, j.state));

  return (
    <Card>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <SegmentedControl label="Filter jobs" options={[...FILTERS]} value={filter} onChange={setFilter} />
        {filter !== "finished" && (
          <SegmentedControl label="Whose jobs" options={[...SCOPES]} value={scope} onChange={setScope} />
        )}
        <Link href="/new" className={cx(buttonClass({ size: "sm", pill: true }), "ml-auto")}>
          New job
        </Link>
      </div>
      {filter === "finished" ? <Finished />
        : source === null ? <Skeleton variant="row" count={4} label="Loading jobs" />
          : <List rows={rows} mineIds={mineIds}
                  empty={filter === "all" ? "Nothing is running or waiting right now." : "No jobs in this state right now."} />}
    </Card>
  );
}
