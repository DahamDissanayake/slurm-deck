import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { type Env, type EnvList, envs } from "../api/envs";
import { Link } from "../app/navigation";
import { Panel } from "../components/Panel";
import { field, primary, secondary } from "./NewJob/StepInputs";

function Table({ title, rows }: { title: string; rows: Env[] }) {
  return (
    <Panel title={title}>
      {rows.length === 0 ? <p className="text-sm text-text-dim">None yet.</p> : (
        <ul className="space-y-1 text-sm">
          {rows.map((e) => (
            <li key={e.path}>
              <span className="font-mono">{e.name}</span>{" "}
              <span className={e.ready ? "text-ok" : "text-warning"}>
                {e.ready ? "ready" : "not ready"}</span>
              {!!e.missing?.length && (
                <span className="text-danger"> · Missing: {e.missing.join(", ")}</span>)}
              <span className="block text-xs text-text-dim">{e.path}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

/** Prebuilt, my environments and container images; build a new environment. */
export function Environments() {
  const [list, setList] = useState<EnvList | null>(null);
  const [dialog, setDialog] = useState(false);
  const [name, setName] = useState("");
  const [packages, setPackages] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(() => { envs.list().then(setList, () => setError("Couldn't load.")); },
                           []);
  useEffect(load, [load]);

  async function start() {
    setError("");
    try {
      await envs.build(name, packages);
      setDialog(false);
      load();
    } catch (err) {
      setError(err instanceof ApiError && err.message ? err.message : "The build didn't start.");
    }
  }

  if (!list) return <Panel title="Environments"><p className="text-text-dim">{error || "Loading…"}</p></Panel>;
  return (
    <div className="space-y-6">
      <div className="flex">
        <button type="button" className={`${primary} ml-auto`} onClick={() => setDialog(true)}>
          Build environment…</button>
      </div>
      {dialog && (
        <Panel title="Build environment">
          {error && <p role="alert" className="mb-3 text-danger">{error}</p>}
          <label className="block text-sm text-text-dim">Name
            <input className={field} value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label className="block text-sm text-text-dim">Packages
            <input className={field} value={packages} placeholder="torch transformers"
                   onChange={(e) => setPackages(e.target.value)} /></label>
          <div className="flex gap-2">
            <button type="button" className={secondary} onClick={() => setDialog(false)}>Cancel</button>
            <button type="button" className={primary} disabled={!name} onClick={start}>Start build</button>
          </div>
        </Panel>
      )}
      {list.builds.length > 0 && (
        <Panel title="Builds">
          <ul className="space-y-1 text-sm">
            {list.builds.map((b) => (
              <li key={b.job_id}>
                <span className="font-mono">{b.name}</span> · {b.state}
                {b.missing.length > 0 && <span className="text-danger"> · Missing: {b.missing.join(", ")}</span>}
                {" · "}<Link href={`/jobs/${b.job_id}`} className="text-accent">Build log</Link>
              </li>
            ))}
          </ul>
        </Panel>
      )}
      <Table title="Prebuilt" rows={list.prebuilt} />
      <Table title="My environments" rows={list.mine} />
      <Table title="Container images" rows={list.images} />
    </div>
  );
}
