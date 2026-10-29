import { type ReactNode, useCallback, useState } from "react";

import type { Cluster } from "../api/live";
import { usePolled } from "../api/poll";
import { type ClusterStatus, type Node, usage } from "../api/usage";
import { initials } from "../app/UserMenu";
import { BoltIcon, ChartIcon, GpuIcon, MemoryIcon, ServerIcon, ThermometerIcon } from "./icons";
import { TimeLeft } from "./JobCard";
import { PodBlocks } from "./PodBlocks";
import { Card } from "./ui/Card";
import { EmptyState } from "./ui/EmptyState";
import { ErrorState } from "./ui/ErrorState";
import { Meter } from "./ui/Meter";
import { Skeleton } from "./ui/Skeleton";
import { StatTile } from "./ui/StatTile";
import { StatusBadge } from "./ui/StatusBadge";

const gb = (mb: number) => `${(mb / 1024).toFixed(1)} GB`;
const pct = (n: number) => `${Math.round(n)}%`;
const DASH = "—";

/** The headline numbers, from the live cluster feed. */
export function ClusterTiles({ cluster }: { cluster: Cluster | null }) {
  if (!cluster) return <Skeleton variant="tile" count={6} label="Loading the cluster" />;
  const n = cluster.node?.live_stats ? cluster.node : null;
  const waiting = cluster.queue.filter((j) => j.state === "PENDING").length;
  const none = n ? undefined : "Not reporting";
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(11rem,1fr))] gap-4">
      <StatTile icon={<GpuIcon />} label="GPU utilisation" value={n ? pct(n.gpu_util) : DASH} sub={none ?? "GPU busy"} />
      <StatTile icon={<MemoryIcon />} label="GPU memory" value={n ? gb(n.gpu_mem_used_mb) : DASH}
                sub={n ? `of ${gb(n.gpu_mem_total_mb)}` : none} />
      <StatTile icon={<ChartIcon />} label="CPU load" value={n ? pct(n.cpu_util) : DASH} sub={none ?? "all cores"} />
      <StatTile icon={<MemoryIcon />} label="RAM" value={n ? gb(n.mem_used_mb) : DASH}
                sub={n ? `of ${gb(n.mem_total_mb)}` : none} />
      <StatTile icon={<ServerIcon />} label="Pods free" value={cluster.pods_total - cluster.pods_used}
                sub={`of ${cluster.pods_total} in total`} />
      <StatTile icon={<ChartIcon />} label="In the queue" value={waiting}
                sub={waiting === 1 ? "job waiting for a pod" : "jobs waiting for a pod"} />
    </div>
  );
}

/** The cluster status, refreshed every few seconds; Retry reloads it. */
function useStatus() {
  const [attempt, setAttempt] = useState(0);
  // `attempt` is a dependency only so that Retry makes usePolled load again.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const load = useCallback(() => usage.status(), [attempt]);
  const { data, failed } = usePolled(load, 5000);
  return { data, failed, retry: () => setAttempt((a) => a + 1) };
}

function Row({ label, value, meter }: { label: string; value: string; meter: { value: number; max: number } }) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between text-md">
        <span className="text-text-dim">{label}</span>
        <span className="font-medium tabular-nums text-text">{value}</span>
      </div>
      <Meter label={label} {...meter} />
    </div>
  );
}

function Fact({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2.5 rounded-md bg-surface-2 px-3 py-2.5">
      <span aria-hidden="true" className="inline-flex text-text-dim [&>svg]:h-4 [&>svg]:w-4">{icon}</span>
      <div>
        <div className="text-xs text-text-dim">{label}</div>
        <div className="text-md font-medium tabular-nums text-text">{value}</div>
      </div>
    </div>
  );
}

function Hardware({ node }: { node: Node }) {
  return (
    <div className="space-y-4">
      <Row label="GPU" value={pct(node.gpu_util)} meter={{ value: node.gpu_util, max: 100 }} />
      <Row label="GPU memory" value={`${gb(node.gpu_mem_used_mb)} of ${gb(node.gpu_mem_total_mb)}`}
           meter={{ value: node.gpu_mem_used_mb, max: node.gpu_mem_total_mb }} />
      <Row label="CPU" value={pct(node.cpu_util)} meter={{ value: node.cpu_util, max: 100 }} />
      <Row label="RAM" value={`${gb(node.mem_used_mb)} of ${gb(node.mem_total_mb)}`}
           meter={{ value: node.mem_used_mb, max: node.mem_total_mb }} />
      <div className="grid grid-cols-2 gap-3 pt-1">
        <Fact icon={<ThermometerIcon />} label="GPU temperature" value={`${node.gpu_temp} °C`} />
        <Fact icon={<BoltIcon />} label="GPU power" value={`${node.gpu_power_w.toFixed(0)} W`} />
      </div>
    </div>
  );
}

function body(status: ReturnType<typeof useStatus>, ok: (data: ClusterStatus) => ReactNode, loading: string) {
  const { data, failed, retry } = status;
  if (data) return ok(data);
  if (failed) return <ErrorState title="Couldn't reach the cluster" onRetry={retry} className="py-8" />;
  return <Skeleton count={5} label={loading} />;
}

/** GPU, CPU and RAM as meters, with temperature and power. */
export function HardwareCard({ status }: { status: ReturnType<typeof useStatus> }) {
  return (
    <Card title="Hardware" icon={<GpuIcon />}>
      {body(status, (d) => d.node
        ? <Hardware node={d.node} />
        : <EmptyState icon={<GpuIcon />} title="The GPU node isn't reporting" className="py-8" />,
      "Loading hardware stats")}
    </Card>
  );
}

function Check({ label, state, detail }: { label: string; state: string; detail?: string }) {
  return (
    <li className="flex items-center justify-between gap-3 py-2">
      <span className="text-md text-text">{label}</span>
      <span className="flex items-center gap-2">
        {detail && <span className="text-xs text-text-dim">{detail}</span>}
        <StatusBadge state={state} />
      </span>
    </li>
  );
}

/** Health checks, pods, and who is running with how long they have left. */
export function ClusterCard({ status, cluster }: { status: ReturnType<typeof useStatus>; cluster: Cluster | null }) {
  const running = (cluster?.queue ?? []).filter((j) => j.state === "RUNNING");
  return (
    <Card title="Cluster" icon={<ServerIcon />}>
      {body(status, (d) => {
        const node = d.node;
        return (
          <>
            <ul className="divide-y divide-border">
              <Check label="Scheduler" state="OK" />
              <Check label="GPU node" detail={node?.state.toLowerCase()}
                     state={node ? node.state.split(/[*~#!%$@^-]/)[0].toUpperCase() : "DOWN"} />
              <Check label="Live stats" state={node?.live_stats ? "OK" : "STALE"} />
            </ul>
            <div className="mt-4 border-t border-border pt-4">
              <div className="mb-2 text-sm text-text-dim">Pods {d.pods_used} of {d.pods_total} in use</div>
              <PodBlocks used={d.pods_used} total={d.pods_total} />
            </div>
          </>
        );
      }, "Loading cluster status")}
      <div className="mt-4 border-t border-border pt-4">
        <h3 className="mb-2 text-sm text-text-dim">Who's running</h3>
        {running.length === 0 ? <p className="text-md text-text-dim">Nobody right now.</p> : (
          <ul className="space-y-2">
            {running.map((j) => (
              <li key={j.job_id} className="flex items-center gap-3">
                <span aria-hidden="true"
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent">
                  {initials(j.user)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-md text-text">{j.user}</span>
                  <span className="block text-xs text-text-dim">{j.pods} pod{j.pods === 1 ? "" : "s"}</span>
                </span>
                <TimeLeft job={j} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

export { useStatus };
