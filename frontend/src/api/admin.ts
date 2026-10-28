import type { Account } from "./auth";
import { apiFetch } from "./client";

export type AccountRow = Account & {
  uid: number | null;
  created_at: string | null;
  last_login_at: string | null;
};

export type Folder = { exists: boolean; owner_uid: number | null; bytes: number | null;
                       mtime: string | null; uid_in_use: boolean };

export type Preview = {
  suggested_username: string;
  email_valid: boolean;
  username_valid: boolean;
  existing_folder: Folder | null;
  shell_account: { uid: number; home?: string } | null;
};

export type NewAccount = { email: string; full_name: string; username: string;
                           role: "user" | "admin"; reconnect_folder: boolean;
                           attach_shell: boolean };

export type ApplicationRow = { id: number; email: string; full_name: string; role_title: string;
                               organisation: string | null; contact_number: string;
                               reason: string | null; status: string; created_at: string };

export type AllowEntry = { id: number; kind: "domain" | "address"; value: string };

const post = (path: string, json?: unknown) => apiFetch(path, { method: "POST", json });

export const admin = {
  accounts: (q = "") =>
    apiFetch<{ accounts: AccountRow[] }>(`/api/admin/accounts${q ? `?q=${encodeURIComponent(q)}` : ""}`)
      .then((r) => r.accounts),
  preview: (email: string, username?: string) =>
    apiFetch<Preview>("/api/admin/accounts/preview",
                      { method: "POST", json: { email, username: username || undefined } }),
  create: (a: NewAccount) => apiFetch<AccountRow>("/api/admin/accounts", { method: "POST", json: a }),
  disable: (id: number) => post(`/api/admin/accounts/${id}/disable`),
  enable: (id: number) => post(`/api/admin/accounts/${id}/enable`),
  resetPassword: (id: number) => post(`/api/admin/accounts/${id}/reset-password`),
  remove: (id: number, purge: boolean, confirm: string) =>
    apiFetch(`/api/admin/accounts/${id}?purge=${purge}`, { method: "DELETE", json: { confirm } }),
  viewAs: (id: number) => post(`/api/admin/view-as/${id}`),
  applications: () =>
    apiFetch<{ applications: ApplicationRow[] }>("/api/admin/applications?status=pending")
      .then((r) => r.applications),
  approve: (id: number, username: string, role: string, reconnect_folder: boolean) =>
    post(`/api/admin/applications/${id}/approve`, { username, role, reconnect_folder }),
  reject: (id: number, note: string) => post(`/api/admin/applications/${id}/reject`, { note }),
  allowlist: () =>
    apiFetch<{ entries: AllowEntry[] }>("/api/admin/allowlist").then((r) => r.entries),
  allow: (value: string) => post("/api/admin/allowlist", { value }),
  disallow: (id: number) => apiFetch(`/api/admin/allowlist/${id}`, { method: "DELETE" }),
};

export function gb(bytes: number | null): string {
  return bytes == null ? "?" : `${(bytes / 1e9).toFixed(1)} GB`;
}

export function day(iso: string | null): string {
  return iso ? iso.slice(0, 10) : "never";
}
