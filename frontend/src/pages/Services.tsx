import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { jobs, type QueueJob } from "../api/jobs";
import { sessions } from "../api/sessions";
import { OpenButton } from "../components/OpenButton";
import { smallButton, StateChip } from "../components/JobCard";
import { Panel } from "../components/Panel";
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
    <Panel title="Services">
      <div className="mb-4"><StartTensorBoard onStarted={load} /></div>
      {error && <p role="alert" className="mb-3 text-danger">{error}</p>}
      {rows === null ? <p className="text-text-dim">Loading…</p>
        : rows.length === 0 ? <p className="text-text-dim">You have no sessions running.</p> : (
          <ul className="space-y-2">
            {rows.map((j) => (
              <li key={j.job_id} className="flex flex-wrap items-center gap-3">
                <StateChip state={j.state} />
                <span className="text-xs text-text-dim">{LABEL[j.kind as keyof typeof LABEL]}</span>
                <span className="font-mono text-sm">{j.name ?? j.job_id}</span>
                <span className="ml-auto flex gap-2">
                  <OpenButton jobId={j.job_id} />
                  <button type="button" className={smallButton} onClick={() => stop(j)}>Stop</button>
                </span>
              </li>
            ))}
          </ul>
        )}
    </Panel>
  );
}
