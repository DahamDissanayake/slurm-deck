import { apiFetch } from "./client";

export const DAYS = [7, 30, 90];

export type Totals = { gpu_hours: number; cpu_hours: number; jobs_by_state: Record<string, number> };
export type ClusterUsage = { total: Totals; users: (Totals & { user: string })[] };
export type DiskUsage = { total_bytes: number;
                          users: { user: string; bytes: number; users_bytes: number;
                                   jobs_bytes: number }[] };

/** The node as /api/cluster/status reports it (sdcore.slurmparse.NodeStats). */
export type Node = {
  state: string; cpu_util: number; cpu_total: number; mem_used_mb: number; mem_total_mb: number;
  gpu_util: number; gpu_mem_used_mb: number; gpu_mem_total_mb: number; gpu_temp: number;
  gpu_power_w: number; shard_total: number; shard_alloc: number; live_stats: boolean;
};
export type ClusterStatus = { node: Node | null; pods_total: number; pods_used: number;
                              partition_max_s: number | null };

export const usage = {
  personal: (days: number) => apiFetch<Totals>(`/api/usage?days=${days}`),
  cluster: (days: number) => apiFetch<ClusterUsage>(`/api/admin/usage?days=${days}`),
  disk: () => apiFetch<DiskUsage>("/api/admin/disk-usage"),
  status: () => apiFetch<ClusterStatus>("/api/cluster/status"),
  queue: () => apiFetch<{ jobs: { state: string }[] }>("/api/cluster/queue"),
};
