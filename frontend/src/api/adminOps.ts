import { apiFetch } from "./client";

export type SettingValues = {
  default_time_limit: string; extension_cap_hours: number; submit_rate_per_hour: number;
  mail_enabled: boolean; maintenance_banner: string | null; terminal_jobs_enabled: boolean;
  disk_alert_percent: number; cluster_location: string | null;
};
export type SettingsReply = { settings: SettingValues; partition_max_s: number | null };

export type AuditRow = { id: number; ts: string; actor: string | null; acting_admin: string | null;
                         action: string; target: string | null; result: string; source: string };
export type AgentEvent = { ts: string; actor: string | null; verb: string; target: string; result: string };
export type MailRow = { id: number; to: string; subject: string; status: string; created_at: string;
                        error: string | null };
type Paged<K extends string, T> = { page: number; has_more: boolean } & { [P in K]: T[] };

const qs = (params: Record<string, string | number>) => new URLSearchParams(
  Object.entries(params).filter(([, v]) => v !== "").map(([k, v]) => [k, String(v)])).toString();

export const adminOps = {
  settings: () => apiFetch<SettingsReply>("/api/admin/settings"),
  saveSettings: (changes: Partial<SettingValues>) =>
    apiFetch<SettingsReply>("/api/admin/settings", { method: "PUT", json: changes }),
  audit: (p: { actor: string; action: string; from: string; to: string; page: number }) =>
    apiFetch<Paged<"events", AuditRow>>(`/api/admin/audit?${qs({ ...p, page_size: 25 })}`),
  agentLog: () => apiFetch<{ events: AgentEvent[] }>("/api/admin/agent-audit?limit=100"),
  mail: (status: string, page: number) =>
    apiFetch<Paged<"mail", MailRow>>(`/api/admin/mail-log?${qs({ status, page, page_size: 25 })}`),
};
