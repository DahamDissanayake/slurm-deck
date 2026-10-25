import { useEffect, useState } from "react";

import { apiFetch } from "./client";
import type { QueueJob } from "./jobs";
import { type LaunchSpec, newjob } from "./newjob";

/** The job kinds that are interactive sessions. */
export const SESSION_KINDS = ["notebook", "tensorboard", "terminal"] as const;
export type SessionKind = (typeof SESSION_KINDS)[number];

export type SessionInfo = { kind: SessionKind; ready: boolean; open_url: string | null;
                            error?: string };

const POLL_MS = 3000;

export const isSession = (kind?: string): kind is SessionKind =>
  SESSION_KINDS.includes(kind as SessionKind);

export const sessions = {
  /** My live jobs that are sessions. */
  list: () => apiFetch<{ jobs: QueueJob[] }>("/api/jobs").then(
    (r) => r.jobs.filter((j) => isSession(j.kind))),
  info: (id: string) => apiFetch<{ session: SessionInfo | null }>(`/api/jobs/${id}`)
    .then((r) => r.session),
  /** A TensorBoard job over a log folder. */
  startTensorBoard: async (logDir: string) => {
    const { spec } = await newjob.defaults("tensorboard");
    const sent: LaunchSpec = { ...spec, intent: "tensorboard", data_path: logDir };
    return newjob.submit(sent);
  },
};

/** The session's readiness, checked every few seconds until it is ready. */
export function useSession(jobId: string): SessionInfo | null {
  const [info, setInfo] = useState<SessionInfo | null>(null);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    const check = () => sessions.info(jobId).then((s) => {
      if (stopped) return;
      setInfo(s);
      if (!s?.ready) timer = setTimeout(check, POLL_MS);
    }, () => { if (!stopped) timer = setTimeout(check, POLL_MS); });
    check();
    return () => { stopped = true; clearTimeout(timer); };
  }, [jobId]);
  return info;
}
