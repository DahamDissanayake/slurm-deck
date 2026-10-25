import { useCallback } from "react";

import { duration } from "../api/jobs";
import { usePolled } from "../api/poll";
import { usage } from "../api/usage";
import { Panel } from "../components/Panel";
import { UsageTabs } from "../components/UsageTabs";

const POLL_MS = 5000;

function Check({ label, ok }: { label: string; ok: boolean }) {
  return (
    <li className="flex items-center gap-2" data-ok={ok}>
      <span aria-hidden className={ok ? "text-ok" : "text-danger"}>{ok ? "●" : "○"}</span>
      <span>{label}</span>
      <span className="text-sm text-text-dim">{ok ? "Yes" : "No"}</span>
    </li>
  );
}

function Item({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-sm border border-border bg-surface-2 p-3">
      <dt className="text-sm text-text-dim">{label}</dt>
      <dd className="text-lg">{value}</dd>
    </div>
  );
}

/** The cluster at a glance, with three plain health checks. */
export function ClusterStatus() {
  const load = useCallback(async () => {
    const [status, queue] = await Promise.all([usage.status(), usage.queue()]);
    return { status, queue: queue.jobs };
  }, []);
  const { data, failed } = usePolled(load, POLL_MS);
  const node = data?.status.node ?? null;
  const running = data?.queue.filter((j) => j.state === "RUNNING").length ?? 0;
  const pending = data?.queue.filter((j) => j.state === "PENDING").length ?? 0;
  return (
    <Panel title="Cluster status">
      <UsageTabs />
      {!data && !failed && <p className="text-text-dim">Loading…</p>}
      <ul className="mb-4 space-y-1">
        <Check label="Scheduler reachable" ok={!failed && data !== null} />
        <Check label="GPU node up" ok={node !== null && !/^(DOWN|DRAIN|FAIL)/.test(node.state)} />
        <Check label="Stats fresh" ok={node?.live_stats === true} />
      </ul>
      {data && (
        <dl className="grid gap-3 sm:grid-cols-2">
          <Item label="Node state" value={node?.state ?? "Unknown"} />
          <Item label="Pods in use" value={`${data.status.pods_used} of ${data.status.pods_total}`} />
          <Item label="Jobs running" value={String(running)} />
          <Item label="Jobs waiting" value={String(pending)} />
          <Item label="Longest job" value={duration(data.status.partition_max_s)} />
        </dl>
      )}
    </Panel>
  );
}
