import { usePolled } from "../api/poll";
import { usage } from "../api/usage";
import { Panel } from "../components/Panel";
import { UsageTabs } from "../components/UsageTabs";
import { Item } from "./ClusterStatus";

const POLL_MS = 5000;
const gb = (mb: number) => `${(mb / 1024).toFixed(1)} GB`;

/** The GPU node's live numbers: GPU, memory, temperature, power, CPU and RAM. */
export function Hardware() {
  const { data, failed } = usePolled(usage.status, POLL_MS);
  const n = data?.node;
  const rows: [string, string][] = n ? [
    ["GPU utilisation", `${n.gpu_util}%`],
    ["GPU memory", `${gb(n.gpu_mem_used_mb)} of ${gb(n.gpu_mem_total_mb)}`],
    ["GPU temperature", `${n.gpu_temp} °C`],
    ["GPU power", `${n.gpu_power_w.toFixed(0)} W`],
    ["CPU utilisation", `${n.cpu_util}%`],
    ["RAM", `${gb(n.mem_used_mb)} of ${gb(n.mem_total_mb)}`],
  ] : [];
  return (
    <Panel title="Hardware stats">
      <UsageTabs />
      {failed && <p role="alert" className="mb-3 text-danger">Couldn't reach the cluster.</p>}
      {!data && !failed && <p className="text-text-dim">Loading…</p>}
      {data && !n && <p className="text-text-dim">The GPU node isn't reporting.</p>}
      {n && (
        <dl className="grid gap-3 sm:grid-cols-2">
          {rows.map(([label, value]) => <Item key={label} label={label} value={value} />)}
        </dl>
      )}
    </Panel>
  );
}
