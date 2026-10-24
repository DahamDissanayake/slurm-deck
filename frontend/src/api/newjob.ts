import { apiFetch } from "./client";

/** The launch spec the New job flow edits (sdcore.launchspec.LaunchSpec). */
export type LaunchSpec = {
  intent: string;
  script: string;
  env_kind: string;
  conda_env: string;
  venv_path: string;
  container_image: string;
  gpu_shards: number;
  cpus: number;
  mem_gb: number;
  time_limit: string;
  data_path: string;
  model_path: string;
  args: string;
  array: string;
  dependency: string;
  mail: boolean;
  requirements: string;
  packages: string;
  port: number;
};

export type Qos = { max_wall_s: number | null; max_pods_per_user: number | null };
export type Defaults = { spec: LaunchSpec; qos: Qos; terminal_enabled: boolean };
export type Template = { id: number; name: string; spec: LaunchSpec };
export type ClusterStatus = {
  pods_total: number;
  pods_used: number;
  node: null | { gpu_mem_total_mb: number; gpu_mem_used_mb: number; live_stats: boolean;
                 shard_total: number };
};

const post = <T>(path: string, json: unknown) => apiFetch<T>(path, { method: "POST", json });

export const newjob = {
  defaults: (intent: string) => apiFetch<Defaults>(`/api/jobs/defaults?intent=${intent}`),
  preview: (spec: LaunchSpec) =>
    post<{ script: string; problems: string[]; warnings: string[] }>("/api/jobs/preview", spec),
  submit: (spec: LaunchSpec) => post<{ job_id: string }>("/api/jobs", spec),
  rerun: (id: string) => apiFetch<{ spec: LaunchSpec }>(`/api/jobs/${id}/rerun`),
  templates: () =>
    apiFetch<{ presets: Template[]; templates: Template[] }>("/api/templates")
      .then((r) => [...r.presets, ...r.templates]),
  saveTemplate: (name: string, spec: LaunchSpec) => post<Template>("/api/templates", { name, spec }),
  status: () => apiFetch<ClusterStatus>("/api/cluster/status"),
  notify: () => apiFetch<{ wanted_pods: number | null }>("/api/notify"),
  setNotify: (wanted_pods: number) =>
    apiFetch("/api/notify", { method: "PUT", json: { wanted_pods } }),
  stopNotify: () => apiFetch("/api/notify", { method: "DELETE" }),
};

function seconds(hms: string): number | null {
  const m = /^(?:(\d+)-)?(\d+):(\d{2}):(\d{2})$/.exec(hms.trim());
  if (!m) return null;
  return Number(m[1] ?? 0) * 86400 + Number(m[2]) * 3600 + Number(m[3]) * 60 + Number(m[4]);
}

/** The QoS checks the server makes, worded the same, so they show while typing. */
export function qosProblems(spec: LaunchSpec, qos: Qos): string[] {
  const out: string[] = [];
  if (qos.max_pods_per_user != null && spec.gpu_shards > qos.max_pods_per_user) {
    out.push(`Requested ${spec.gpu_shards} GPU pods but your QOS allows ` +
             `${qos.max_pods_per_user} per user.`);
  }
  const s = seconds(spec.time_limit);
  if (s == null) out.push("Write the time limit as HH:MM:SS.");
  else if (qos.max_wall_s != null && s > qos.max_wall_s) {
    out.push(`Requested ${spec.time_limit} exceeds the QOS wall-time limit of ` +
             `${Math.floor(qos.max_wall_s / 3600)}h.`);
  }
  return out;
}
