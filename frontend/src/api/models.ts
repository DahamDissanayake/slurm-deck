import { apiFetch } from "./client";

export type ModelEntry = { name: string; type: string; bytes: number | null };
export type Library = { shared: ModelEntry[]; mine: ModelEntry[] };
export type Download = { job_id: string; repo_id: string; state: "running" | "done" | "failed";
                         bytes: number | null; message: string };

export const models = {
  library: () => apiFetch<Library>("/api/models"),
  downloads: () => apiFetch<{ downloads: Download[] }>("/api/models/downloads")
    .then((r) => r.downloads),
  /** The token, when there is one, is sent for this download only. */
  download: (repo_id: string, revision: string, token: string) =>
    apiFetch<{ job_id: string }>("/api/models/download", {
      method: "POST", json: { repo_id, revision: revision || null, token: token || null } }),
};
