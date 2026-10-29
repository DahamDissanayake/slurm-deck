import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { jobs, type QueueJob } from "../api/jobs";
import { sessions } from "../api/sessions";
import { OpenButton } from "../components/OpenButton";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { StatusBadge } from "../components/ui/StatusBadge";
import { ServerIcon } from "../components/icons";
import { Card } from "../components/ui/Card";
import { StartTensorBoard } from "../components/StartTensorBoard";

const POLL_MS = 5000;
const LABEL = { notebook: "Notebook", tensorboard: "TensorBoard", terminal: "Terminal" };

/** My notebooks, TensorBoards and terminals: open or stop each, or start a TensorBoard. */
export function Services() {
  const [rows, setRows] = useState<QueueJob[] | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    sessions.list().then(setRows, () => setRows((r) => r ?? []));
  }, []);
  useEffect(() => {
    load();
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  async function stop(job: QueueJob) {
    if (!window.confirm(`Stop ${job.name ?? job.job_id}?`)) return;
    setError("");
    try {
      await jobs.cancel(job.job_id);
      load();
    } catch (err) {
      setError(err instanceof ApiError && err.message ? err.message : "Stopping failed.");
    }
  }

  return (
    <Card title="Services">
      <div className="mb-4"><StartTensorBoard onStarted={load} /></div>
      {error && <p role="alert" className="mb-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}
      {rows === null ? <Skeleton variant="row" label="Loading services" />
        : rows.length === 0 ? <EmptyState icon={<ServerIcon />} title="You have no sessions running">Start a notebook, terminal or TensorBoard to see it here.</EmptyState> : (
          <ul className="space-y-3">
            {rows.map((j) => (
              <li key={j.job_id} className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-surface-2 px-3 py-2">
                <StatusBadge state={j.state} />
                <span className="text-xs text-text-dim">{LABEL[j.kind as keyof typeof LABEL]}</span>
                <span className="font-mono text-sm">{j.name ?? j.job_id}</span>
                <span className="ml-auto flex gap-2">
                  <OpenButton jobId={j.job_id} />
                  <Button size="sm" variant="secondary" onClick={() => stop(j)}>Stop</Button>
                </span>
              </li>
            ))}
          </ul>
        )}
    </Card>
  );
}
