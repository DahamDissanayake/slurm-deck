import { useSyncExternalStore } from "react";

import type { QueueJob } from "./jobs";

/** What /ws/live sends (see sdweb.live). */
export type Cluster = {
  node: null | {
    gpu_util: number; gpu_mem_used_mb: number; gpu_mem_total_mb: number; cpu_util: number;
    mem_used_mb: number; mem_total_mb: number; live_stats: boolean;
  };
  pods_total: number;
  pods_used: number;
  queue: QueueJob[];
  disk: { free_bytes: number; total_bytes: number } | null;
  maintenance: string | null;
};

export type Live = {
  connected: boolean;
  cluster: Cluster | null;
  jobs: QueueJob[] | null;
  banners: { job_id: string; minutes_left: number | null }[];
};

const NO_SESSION = 4401;

/** Reconnect delay after `attempt` failed tries: 1 s doubling, at most 30 s. */
export function backoff(attempt: number): number {
  return Math.min(1000 * 2 ** attempt, 30_000);
}

// One socket for the whole tab, open while any component is listening.
let state: Live = { connected: false, cluster: null, jobs: null, banners: [] };
const listeners = new Set<() => void>();
let socket: WebSocket | null = null;
let retry: ReturnType<typeof setTimeout> | null = null;
let attempt = 0;

function set(next: Partial<Live>) {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
}

function connect() {
  retry = null;
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${scheme}://${window.location.host}/ws/live`);
  socket = ws;
  let banners: Live["banners"] = [];
  ws.onopen = () => { attempt = 0; set({ connected: true }); };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === "cluster") set({ cluster: msg });
    if (msg.type === "jobs") { banners = []; set({ jobs: msg.jobs, banners }); }
    if (msg.type === "banner") { banners = [...banners, msg]; set({ banners }); }
  };
  ws.onclose = (e) => {
    socket = null;
    set({ connected: false });
    if (e.code === NO_SESSION || listeners.size === 0) return;
    retry = setTimeout(connect, backoff(attempt++));
  };
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (!socket && !retry) connect();
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      if (retry) clearTimeout(retry);
      retry = null;
      socket?.close();
    }
  };
}

/** The live cluster picture and my jobs, kept up to date over /ws/live. */
export function useLive(): Live {
  return useSyncExternalStore(subscribe, () => state);
}
