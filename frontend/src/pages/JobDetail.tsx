import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { duration, isLive, type JobInfo, jobs } from "../api/jobs";
import { ExtendDialog } from "../components/ExtendDialog";
import { Chip } from "../components/JobCard";
import { ClockIcon, FileTextIcon, FolderIcon, GpuIcon, PlusIcon, RefreshIcon, TerminalIcon, XIcon } from "../components/icons";
import { LogViewer } from "../components/LogViewer";
import { OpenButton } from "../components/OpenButton";
import { Card } from "../components/ui/Card";
import { ErrorState } from "../components/ui/ErrorState";
import { IconButton } from "../components/ui/IconButton";
import { IconLink } from "../components/ui/IconLink";
import { Notice } from "../components/ui/Notice";
import { Skeleton } from "../components/ui/Skeleton";
import { StatusBadge } from "../components/ui/StatusBadge";
import { Tabs } from "../components/ui/Tabs";
import { useToast } from "../components/ui/Toast";

type Section = "overview" | "logs" | "script";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md bg-surface-2 px-3 py-2.5">
      <dt className="text-xs text-text-dim">{label}</dt>
      <dd className="mt-0.5 break-words text-md font-medium text-text">{children}</dd>
    </div>
  );
}

/** One job: its state and actions, then Overview, Logs and Script on tabs. */
export function JobDetail({ id }: { id: string }) {
  const [job, setJob] = useState<JobInfo | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [section, setSection] = useState<Section>("overview");
  const [extending, setExtending] = useState(false);
  const toast = useToast();

  const load = useCallback(() => {
    setError(null);
    jobs.get(id).then(setJob, setError);
  }, [id]);
  useEffect(load, [load]);

  if (error) {
    return (
      <Card><ErrorState title="Couldn't load this job" error={error instanceof ApiError ? error : null} onRetry={load} /></Card>
    );
  }
  if (!job) return <Card><Skeleton count={5} label="Loading the job" /></Card>;
  const live = isLive(job.state);

  async function cancel() {
    if (!window.confirm(`Cancel job ${id}?`)) return;
    try {
      await jobs.cancel(id);
      toast({ tone: "ok", message: `Job ${id} cancelled.` });
    } catch (err) {
      toast({ tone: "danger", message: err instanceof ApiError && err.message ? err.message : "Cancelling failed." });
    }
    load();
  }

  const tabs = [
    { value: "overview" as const, label: "Overview", icon: <GpuIcon /> },
    { value: "logs" as const, label: "Logs", icon: <TerminalIcon /> },
    ...(job.script ? [{ value: "script" as const, label: "Script", icon: <FileTextIcon /> }] : []),
  ];

  return (
    <Card>
      <header className="mb-5 flex flex-wrap items-center gap-3">
        <h2 className="font-mono text-lg font-semibold text-text">Job {id}</h2>
        <StatusBadge state={job.state} />
        <div className="ml-auto flex items-center gap-1">
          {live && job.session && <OpenButton jobId={id} />}
          {live && <IconButton label="Extend time" icon={<PlusIcon />} onClick={() => setExtending(true)} />}
          {live && <IconButton label="Cancel job" icon={<XIcon />} onClick={cancel} />}
          <IconLink href={`/new?rerun=${id}`} label="Rerun" icon={<RefreshIcon />} />
        </div>
      </header>
      {extending && live && (
        <ExtendDialog jobId={id} onClose={() => setExtending(false)}
                      onDone={() => { setExtending(false); toast({ tone: "ok", message: "Time added." }); load(); }} />
      )}
      <Tabs label="Job sections" tabs={tabs} value={section} onChange={setSection}>
        {section === "overview" && (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-1.5">
              <Chip icon={<ClockIcon />}>{duration(job.run_time_s)} of {duration(job.time_limit_s)}</Chip>
              <Chip icon={<FolderIcon />}>{job.kind}</Chip>
            </div>
            <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Fact label="Node"><span className="font-mono">{job.node || "—"}</span></Fact>
              <Fact label="Time used">{duration(job.run_time_s)}</Fact>
              <Fact label="Time limit">{duration(job.time_limit_s)}</Fact>
              <Fact label="Exit code"><span className="font-mono">{job.exit_code || "—"}</span></Fact>
              <div className="sm:col-span-2 lg:col-span-4">
                <Fact label="Folder"><span className="font-mono">{job.folder ?? job.work_dir}</span></Fact>
              </div>
            </dl>
            {job.explanation && <Notice role="note">{job.explanation}</Notice>}
          </div>
        )}
        {section === "logs" && <LogViewer jobId={id} running={live} />}
        {section === "script" && job.script && (
          <pre className="max-h-[36rem] overflow-auto rounded-md border border-border bg-bg p-4 font-mono text-xs">{job.script}</pre>
        )}
      </Tabs>
    </Card>
  );
}
