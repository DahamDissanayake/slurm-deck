import type { Cluster } from "../api/live";
import { PodBlocks } from "./PodBlocks";

const gb = (mb: number) => `${(mb / 1024).toFixed(0)} GB`;

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-widest text-text-dim">{label}</div>
      <div className="font-mono text-sm">{value}</div>
    </div>
  );
}

/** The cluster at a glance: pods in use, GPU, CPU, memory and free disk. */
export function ClusterStrip({ cluster }: { cluster: Cluster | null }) {
  if (!cluster) return <p className="text-sm text-text-dim">Connecting to the cluster…</p>;
  const n = cluster.node;
  return (
    <div className="flex flex-wrap items-end gap-x-8 gap-y-4">
      <div>
        <div className="mb-1 text-xs uppercase tracking-widest text-text-dim">
          Pods {cluster.pods_used}/{cluster.pods_total}
        </div>
        <PodBlocks used={cluster.pods_used} total={cluster.pods_total} />
      </div>
      {n && n.live_stats && (
        <>
          <Stat label="GPU" value={`${n.gpu_util}%`} />
          <Stat label="VRAM" value={`${gb(n.gpu_mem_used_mb)} / ${gb(n.gpu_mem_total_mb)}`} />
          <Stat label="CPU" value={`${n.cpu_util}%`} />
          <Stat label="RAM" value={`${gb(n.mem_used_mb)} / ${gb(n.mem_total_mb)}`} />
        </>
      )}
      {cluster.disk && (
        <Stat label="Disk free" value={`${(cluster.disk.free_bytes / 1e12).toFixed(2)} TB`} />
      )}
    </div>
  );
}
