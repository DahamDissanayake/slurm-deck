import { apiFetch } from "./client";

export type Entry = { name: string; type: "file" | "dir" | "link" | "other"; size: number;
                      mtime: number };
export type Root = { label: string; path: string; writable: boolean };
export type PreviewData = { kind: "table"; rows: string[][] }
  | { kind: "text"; text: string; truncated: boolean };
export type ActiveUpload = { id: string; filename: string; dest_dir: string; size: number;
                             offset: number; expires_at: string };

const q = (path: string) => `?path=${encodeURIComponent(path)}`;
const post = (url: string, json: unknown) => apiFetch(url, { method: "POST", json });

export const join = (dir: string, name: string) => `${dir.replace(/\/+$/, "")}/${name}`;
export const parent = (path: string) => path.replace(/\/[^/]+\/?$/, "") || "/";
export const IMAGE = /\.(png|jpe?g|gif|webp|svg)$/i;
export const ARCHIVE = /\.(zip|tar|tar\.gz|tgz|tar\.bz2|tar\.xz)$/i;

export const files = {
  roots: () => apiFetch<{ roots: Root[] }>("/api/files/roots"),
  list: (path: string) => apiFetch<{ entries: Entry[] }>(`/api/files${q(path)}`),
  preview: (path: string) => apiFetch<PreviewData>(`/api/files/preview${q(path)}`),
  previewUrl: (path: string) => `/api/files/preview${q(path)}`,
  downloadUrl: (path: string) => `/api/files/download${q(path)}`,
  getText: (path: string) => apiFetch<{ text: string }>(`/api/files/text${q(path)}`),
  putText: (path: string, text: string) =>
    apiFetch(`/api/files/text${q(path)}`, { method: "PUT", body: text,
                                            headers: { "Content-Type": "text/plain" } }),
  mkdir: (path: string) => post("/api/files/mkdir", { path }),
  rename: (src: string, dst: string) => post("/api/files/rename", { src, dst }),
  remove: (path: string, recursive: boolean) => post("/api/files/delete", { path, recursive }),
  extract: (archive: string, dest_dir: string) =>
    post("/api/files/extract", { archive, dest_dir }),
  activeUploads: () => apiFetch<{ uploads: ActiveUpload[] }>("/api/uploads?active=1"),
};

export function formatBytes(n: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${i ? n.toFixed(1) : n} ${units[i]}`;
}
