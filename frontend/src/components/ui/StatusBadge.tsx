import type { ReactNode } from "react";

import { CheckIcon, ClockIcon, DotIcon, PauseIcon, StopIcon, XIcon } from "../icons";
import { cx } from "./cx";

type Tone = "running" | "pending" | "ok" | "danger" | "warning" | "neutral";

const TONES: Record<Tone, string> = {
  running: "bg-accent-soft text-accent",
  pending: "bg-warning-soft text-warning",
  ok: "bg-ok-soft text-ok",
  danger: "bg-danger-soft text-danger",
  warning: "bg-warning-soft text-warning",
  neutral: "bg-neutral-soft text-text-dim",
};
const ICONS: Record<Tone, ReactNode> = {
  running: <DotIcon />,
  pending: <ClockIcon />,
  ok: <CheckIcon />,
  danger: <XIcon />,
  warning: <PauseIcon />,
  neutral: <StopIcon />,
};

// [label, tone] by state, upper-cased. Slurm job states first, then systemd
// service states, then the lower-case states other APIs use.
const STATES: Record<string, [string, Tone]> = {
  PENDING: ["Queued", "pending"], REQUEUED: ["Requeued", "pending"], CONFIGURING: ["Starting", "running"],
  RUNNING: ["Running", "running"], COMPLETING: ["Finishing", "running"], RESIZING: ["Resizing", "running"],
  SUSPENDED: ["Suspended", "warning"], PREEMPTED: ["Preempted", "warning"], COMPLETED: ["Completed", "ok"],
  FAILED: ["Failed", "danger"], TIMEOUT: ["Timed out", "danger"], OUT_OF_MEMORY: ["Out of memory", "danger"],
  NODE_FAIL: ["Node failed", "danger"], BOOT_FAIL: ["Boot failed", "danger"], DEADLINE: ["Deadline missed", "danger"],
  CANCELLED: ["Cancelled", "neutral"],
  ACTIVE: ["Active", "ok"], INACTIVE: ["Stopped", "neutral"], ACTIVATING: ["Starting", "pending"],
  DEACTIVATING: ["Stopping", "pending"], RELOADING: ["Reloading", "pending"],
  IDLE: ["Idle", "ok"], MIXED: ["Partly busy", "running"], ALLOCATED: ["Busy", "running"],
  DRAINING: ["Draining", "warning"], DRAINED: ["Drained", "warning"], DOWN: ["Down", "danger"],
  FAIL: ["Failed", "danger"], STALE: ["Stale", "warning"],
  BUILDING: ["Building", "pending"], OK: ["Ready", "ok"], DONE: ["Done", "ok"], ENDED: ["Ended", "neutral"],
};

export const JOB_STATES = ["PENDING", "REQUEUED", "CONFIGURING", "RUNNING", "COMPLETING", "RESIZING", "SUSPENDED",
  "PREEMPTED", "COMPLETED", "FAILED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL", "BOOT_FAIL", "DEADLINE", "CANCELLED"];
export const SERVICE_STATES = ["active", "inactive", "failed", "activating", "deactivating", "reloading"];

/** One badge for every job and service state: icon + plain word, coloured by
 * meaning, never colour alone. Running pulses softly when motion is allowed. */
export function StatusBadge({ state, className }: { state: string; className?: string }) {
  const key = state.trim().split(/\s+/)[0]?.toUpperCase() ?? "";
  const [label, tone] = STATES[key]
    ?? [key ? key.charAt(0) + key.slice(1).toLowerCase().replace(/_/g, " ") : "Unknown", "neutral"];
  return (
    <span title={state} className={cx("inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5",
      "text-xs font-medium", TONES[tone], className)}>
      <span aria-hidden="true" data-pulse={tone === "running" || undefined}
            className={cx("inline-flex [&>svg]:h-3.5 [&>svg]:w-3.5", tone === "running" && "motion-safe:animate-pulse-soft")}>
        {ICONS[tone]}
      </span>
      {label}
    </span>
  );
}
