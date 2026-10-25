import { useEffect, useState } from "react";

import { ApiError } from "../../api/client";
import { formatBytes } from "../../api/files";
import { type ClusterUsage, DAYS, type DiskUsage, usage } from "../../api/usage";
import { Panel } from "../../components/Panel";

type SortKey = "user" | "gpu_hours" | "cpu_hours" | "jobs";

const jobsOf = (u: { jobs_by_state: Record<string, number> }) =>
  Object.values(u.jobs_by_state).reduce((a, b) => a + b, 0);

/** Everyone's usage over a period, and disk use per user. */
export function UsageAdmin() {
  const [days, setDays] = useState(30);
  const [report, setReport] = useState<ClusterUsage | null>(null);
  const [disk, setDisk] = useState<DiskUsage | null>(null);
  const [sort, setSort] = useState<{ key: SortKey; asc: boolean }>({ key: "gpu_hours", asc: false });
  const [error, setError] = useState("");

  useEffect(() => {
    setReport(null);
    usage.cluster(days).then(setReport, (e) =>
      setError(e instanceof ApiError && e.message ? e.message : "Couldn't load usage."));
  }, [days]);
  useEffect(() => {
    usage.disk().then(setDisk, () => setDisk({ total_bytes: 0, users: [] }));
  }, []);

  const rows = [...(report?.users ?? [])].sort((a, b) => {
    const [x, y] = sort.key === "user" ? [a.user, b.user]
      : sort.key === "jobs" ? [jobsOf(a), jobsOf(b)] : [a[sort.key], b[sort.key]];
    return (x < y ? -1 : x > y ? 1 : 0) * (sort.asc ? 1 : -1);
  });
  const head = (key: SortKey, label: string) => (
    <th className="py-1 font-normal">
      <button type="button"
              onClick={() => setSort({ key, asc: sort.key === key ? !sort.asc : key === "user" })}>
        {label}{sort.key === key ? (sort.asc ? " ▲" : " ▼") : ""}
      </button>
    </th>
  );
  return (
    <div className="space-y-6">
      <Panel title="Usage by user">
        <label className="mb-4 block text-sm text-text-dim">Period
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}
                  className="ml-2 rounded-sm border border-border bg-surface-2 px-2 py-1 text-text">
            {DAYS.map((d) => <option key={d} value={d}>Last {d} days</option>)}
          </select>
        </label>
        {error && <p role="alert" className="text-danger">{error}</p>}
        {report && (
          <table className="w-full text-left text-sm">
            <thead className="text-text-dim">
              <tr>{head("user", "User")}{head("gpu_hours", "GPU-hours")}
                {head("cpu_hours", "CPU-hours")}{head("jobs", "Jobs")}</tr>
            </thead>
            <tbody>
              {rows.map((u) => (
                <tr key={u.user} className="border-t border-border">
                  <td className="py-1 font-mono">{u.user}</td>
                  <td>{u.gpu_hours.toFixed(1)}</td><td>{u.cpu_hours.toFixed(1)}</td>
                  <td>{jobsOf(u)}</td>
                </tr>
              ))}
              <tr className="border-t border-border font-semibold">
                <td className="py-1">Everyone</td><td>{report.total.gpu_hours.toFixed(1)}</td>
                <td>{report.total.cpu_hours.toFixed(1)}</td><td>{jobsOf(report.total)}</td>
              </tr>
            </tbody>
          </table>
        )}
      </Panel>
      <Panel title="Disk use by user">
        {!disk ? <p className="text-text-dim">Measuring… this can take a minute.</p> : (
          <table className="w-full text-left text-sm">
            <thead className="text-text-dim">
              <tr><th className="py-1 font-normal">User</th><th className="font-normal">Files</th>
                <th className="font-normal">Job outputs</th><th className="font-normal">Total</th></tr>
            </thead>
            <tbody>
              {disk.users.map((u) => (
                <tr key={u.user} className="border-t border-border">
                  <td className="py-1 font-mono">{u.user}</td><td>{formatBytes(u.users_bytes)}</td>
                  <td>{formatBytes(u.jobs_bytes)}</td><td>{formatBytes(u.bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
