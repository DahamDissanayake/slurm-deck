import { apiFetch } from "./client";
import type { QueueJob } from "./jobs";

export type Qos = { name: string; max_wall_s: number | null; max_pods_per_user: number | null;
                    max_gpus_per_user: number | null; priority: number };
export type QosField = "max_wall" | "max_pods_per_user" | "max_gpus_per_user" | "priority";
export type Pods = { pods_total: number; pods: { pod: number; job_id: string | null;
                                                  user: string | null }[];
                     fits: { n: number; ok: boolean; message: string }[] };
export type Services = { login: Record<string, string>; gpu: Record<string, string>;
                         gpu_error: string };
export type NodeJob = { job_id: string; user: string; name: string; state: string };

export const AREAS = ["datasets", "models", "envs", "data", "images", "scripts"];

const post = <T = unknown>(path: string, json: unknown = {}) =>
  apiFetch<T>(`/api/admin${path}`, { method: "POST", json });

export const cluster = {
  qos: () => apiFetch<{ qos: Qos[] }>("/api/admin/qos").then((r) => r.qos),
  setQos: (name: string, field: QosField, value: number | null) =>
    post("/qos", { name, field, value }),
  nodeJobs: () => post<{ jobs: NodeJob[] }>("/node/jobs").then((r) => r.jobs),
  drain: (reason: string, cancel_running: boolean) => post("/node/drain", { reason, cancel_running }),
  resume: () => post("/node/resume"),
  pods: () => apiFetch<Pods>("/api/admin/pods"),
  resize: (n: number) => post<{ output: string }>("/pods/resize", { n }),
  services: () => apiFetch<Services>("/api/admin/service-status"),
  publish: (src: string, area: string, name: string, replace: boolean) =>
    post("/shared/publish", { src, area, name, replace }),
  unpublish: (area: string, name: string) => post("/shared/unpublish", { area, name }),
  history: (days: number) =>
    apiFetch<{ jobs: QueueJob[] }>(`/api/jobs/history?days=${days}&all_users=true`)
      .then((r) => r.jobs),
  queue: () => apiFetch<{ jobs: QueueJob[] }>("/api/cluster/queue")
    .then((r) => r.jobs),
};
