import { apiFetch } from "./client";

export type Env = { name: string; path: string; kind: string; ready: boolean;
                    missing?: string[] };
export type Build = { job_id: string; kind: string; name: string; path: string;
                      state: "building" | "ok" | "failed" | "ended"; missing: string[] };
export type EnvList = { prebuilt: Env[]; mine: Env[]; images: Env[]; builds: Build[] };

export const envs = {
  list: () => apiFetch<EnvList>("/api/envs"),
  build: (name: string, packages: string, kind = "conda") =>
    apiFetch<{ job_id: string }>("/api/envs/build",
                                 { method: "POST", json: { kind, name, packages } }),
};
