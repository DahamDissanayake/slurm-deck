import { ApiError, apiFetch } from "./client";

/** A job as squeue (or sacct, for history) reports it. `name` is missing for
 * other people's jobs in the shared queue. */
export type QueueJob = {
  job_id: string;
  name?: string;
  state: string;
  user: string;
  pods: number;
  time_used: string;
  time_limit: string;
  time_left_s: number | null;
  kind?: string;
};

export type JobInfo = {
  owner: string;
  state: string;
  time_limit_s: number | null;
  run_time_s: number | null;
  node: string;
  exit_code: string;
  work_dir: string;
  kind: string;
  folder: string | null;
  script: string | null;
  explanation: string | null;
};

const LIVE = new Set(["PENDING", "CONFIGURING", "RUNNING", "SUSPENDED", "COMPLETING",
                      "REQUEUED", "RESIZING"]);

export const isLive = (state: string) => LIVE.has(state);

/** The four words the UI uses for Slurm's many states. */
export function stateLabel(state: string): "Queued" | "Starting" | "Running" | "Ended" {
  if (state === "PENDING" || state === "REQUEUED") return "Queued";
  if (state === "CONFIGURING") return "Starting";
  return isLive(state) ? "Running" : "Ended";
}

export function duration(seconds: number | null): string {
  if (seconds == null) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h ? `${h} h ${m} min` : `${m} min`;
}

const post = (path: string, json?: unknown) => apiFetch(path, { method: "POST", json });

export const jobs = {
  history: (days: number, state = "") =>
    apiFetch<{ jobs: QueueJob[] }>(`/api/jobs/history?days=${days}${state ? `&state=${state}` : ""}`)
      .then((r) => r.jobs),
  get: (id: string) => apiFetch<JobInfo>(`/api/jobs/${id}`),
  cancel: (id: string) => post(`/api/jobs/${id}/cancel`),
  extend: (id: string, hours: number) =>
    apiFetch<{ new_limit_s: number }>(`/api/jobs/${id}/extend`,
                                     { method: "POST", json: { hours } }),
};

export const logUrl = (id: string, stream: string, offset = 0) =>
  `/api/jobs/${id}/log?stream=${stream}&offset=${offset}`;

/** Part of a job's log as plain text, and the log's full size. */
export async function readLog(id: string, stream: string, offset: number):
    Promise<{ text: string; size: number }> {
  const res = await fetch(logUrl(id, stream, offset), { credentials: "same-origin" });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new ApiError(res.status, data.error ?? "error", data.message ?? "");
  }
  return { text: await res.text(), size: Number(res.headers.get("X-SD-Size") || 0) };
}
