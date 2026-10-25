import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../../api/client";
import { cluster, type NodeJob, type Pods, type Qos, type QosField, type Services } from "../../api/cluster";
import { usePolled } from "../../api/poll";
import { Panel } from "../../components/Panel";
import { smallButton } from "./AdminLayout";

const say = (e: unknown, fallback: string) =>
  e instanceof ApiError && e.message ? e.message : fallback;
const input = "w-24 rounded-sm border border-border bg-surface-2 px-2 py-1 text-text";

/** One QOS: its limits as editable boxes; an empty box clears the limit. */
function QosRow({ q, onSaved, onError }: { q: Qos; onSaved: () => void; onError: (m: string) => void }) {
  const start = {
    max_wall: q.max_wall_s == null ? "" : String(q.max_wall_s / 3600),
    max_pods_per_user: q.max_pods_per_user == null ? "" : String(q.max_pods_per_user),
    max_gpus_per_user: q.max_gpus_per_user == null ? "" : String(q.max_gpus_per_user),
    priority: String(q.priority),
  };
  const [v, setV] = useState(start);

  async function save() {
    try {
      for (const f of Object.keys(start) as QosField[]) {
        if (v[f] === start[f]) continue;
        const n = v[f].trim() === "" ? null : Number(v[f]);
        await cluster.setQos(q.name, f, f === "max_wall" && n !== null ? Math.round(n * 3600) : n);
      }
      onSaved();
    } catch (e) {
      onError(say(e, "That didn't save."));
    }
  }

  return (
    <tr className="border-t border-border">
      <td className="py-1 font-mono">{q.name}</td>
      {(["max_wall", "max_pods_per_user", "max_gpus_per_user", "priority"] as QosField[]).map((f) => (
        <td key={f}>
          <input className={input} aria-label={`${q.name} ${f}`} value={v[f]}
                 placeholder="none" onChange={(e) => setV({ ...v, [f]: e.target.value })} />
        </td>
      ))}
      <td><button type="button" className={smallButton} onClick={save}>Save</button></td>
    </tr>
  );
}

function QosPanel() {
  const [rows, setRows] = useState<Qos[] | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => { cluster.qos().then(setRows, (e) => setError(say(e, "Couldn't load limits."))); }, []);
  useEffect(load, [load]);
  return (
    <Panel title="Limits (QOS)">
      {error && <p role="alert" className="mb-2 text-danger">{error}</p>}
      <table className="w-full text-left text-sm">
        <thead className="text-text-dim">
          <tr><th>Name</th><th>Max hours</th><th>Pods per user</th><th>GPUs per user</th>
            <th>Priority</th><th /></tr>
        </thead>
        <tbody>
          {(rows ?? []).map((q) => (
            <QosRow key={q.name} q={q} onError={setError} onSaved={() => { setError(""); load(); }} />
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function NodePanel() {
  const [jobs, setJobs] = useState<NodeJob[]>([]);
  const [reason, setReason] = useState("");
  const [cancel, setCancel] = useState(false);
  const [note, setNote] = useState("");
  const load = useCallback(() => { cluster.nodeJobs().then(setJobs, () => setJobs([])); }, []);
  useEffect(load, [load]);

  async function run(action: () => Promise<unknown>, done: string) {
    try {
      await action();
      setNote(done);
      load();
    } catch (e) {
      setNote(say(e, "That didn't work."));
    }
  }
  function drain() {
    if (cancel && !window.confirm(`Cancel the ${jobs.length} job(s) on the node and drain it?`)) return;
    run(() => cluster.drain(reason.trim(), cancel), "The node is draining.");
  }

  return (
    <Panel title="Node">
      <p className="mb-2 text-sm text-text-dim">{jobs.length} job(s) on the node.</p>
      <div className="flex flex-wrap items-end gap-2 text-sm">
        <label>Reason
          <input className={`${input} ml-2 w-64`} value={reason} maxLength={200}
                 onChange={(e) => setReason(e.target.value)} />
        </label>
        <label><input type="checkbox" checked={cancel} onChange={(e) => setCancel(e.target.checked)} />
          {" "}Cancel running jobs</label>
        <button type="button" className={smallButton} disabled={!reason.trim()} onClick={drain}>Drain</button>
        <button type="button" className={smallButton}
                onClick={() => run(cluster.resume, "The node is back in service.")}>Resume</button>
      </div>
      {note && <p role="status" className="mt-2 text-sm">{note}</p>}
    </Panel>
  );
}

function PodsPanel() {
  const [pods, setPods] = useState<Pods | null>(null);
  const [n, setN] = useState(1);
  const [note, setNote] = useState("");
  const load = useCallback(() => { cluster.pods().then(setPods, () => setPods(null)); }, []);
  useEffect(load, [load]);

  async function resize() {
    if (!window.confirm(`Resize to ${n} pod(s)? Slurm restarts on both nodes.`)) return;
    try {
      setNote((await cluster.resize(n)).output);
      load();
    } catch (e) {
      setNote(say(e, "The resize failed."));
    }
  }

  const fit = pods?.fits.find((f) => f.n === n);
  return (
    <Panel title="Pods">
      <div className="mb-3 flex flex-wrap gap-1" aria-label="Pod grid">
        {(pods?.pods ?? []).map((p) => (
          <span key={p.pod} title={p.job_id ? `Job ${p.job_id} (${p.user})` : "Free"}
                className={`h-6 w-6 rounded-sm border border-border ${p.job_id ? "bg-accent" : "bg-surface-2"}`} />
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label>New pod count
          <select className={`${input} ml-2 w-20`} value={n} onChange={(e) => setN(Number(e.target.value))}>
            {Array.from({ length: 8 }, (_, i) => i + 1).map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </label>
        <button type="button" className={smallButton} disabled={fit?.ok === false} onClick={resize}>Resize</button>
        {fit && !fit.ok && <span className="text-warning">{fit.message}</span>}
      </div>
      {note && <pre role="status" className="mt-2 whitespace-pre-wrap font-mono text-xs">{note}</pre>}
    </Panel>
  );
}

function ServicesPanel() {
  const { data, failed } = usePolled<Services>(cluster.services, 15000);
  const list = (title: string, units: Record<string, string>) => (
    <div>
      <h3 className="mb-1 text-sm text-text-dim">{title}</h3>
      <ul className="text-sm">
        {Object.entries(units).map(([u, s]) => (
          <li key={u}><span className={s === "active" ? "text-ok" : "text-danger"}>●</span> {u}: {s}</li>
        ))}
      </ul>
    </div>
  );
  return (
    <Panel title="Services">
      {failed && <p role="alert" className="text-danger">Couldn't read service status.</p>}
      {data && (
        <div className="grid gap-4 sm:grid-cols-2">
          {list("Login node", data.login)}
          {data.gpu_error ? <p role="alert" className="text-danger">GPU host: {data.gpu_error}</p>
            : list("GPU host", data.gpu)}
        </div>
      )}
    </Panel>
  );
}

/** Cluster control: limits, the node, the pods and the services behind them. */
export function Cluster() {
  return (
    <div className="space-y-6">
      <QosPanel /><NodePanel /><PodsPanel /><ServicesPanel />
    </div>
  );
}
