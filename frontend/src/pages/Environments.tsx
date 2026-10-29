import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { type Env, type EnvList, envs } from "../api/envs";
import { Link } from "../app/navigation";
import { Card } from "../components/ui/Card";
import { EnvIcon, PlusIcon } from "../components/icons";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { Skeleton } from "../components/ui/Skeleton";
import { StatusBadge } from "../components/ui/StatusBadge";
import { field } from "./NewJob/StepInputs";

function Table({ title, rows }: { title: string; rows: Env[] }) {
  return (
    <Card title={title}>
      {rows.length === 0 ? <EmptyState icon={<EnvIcon />} title="None yet" className="py-6" /> : (
        <ul className="space-y-3 text-sm">
          {rows.map((e) => (
            <li key={e.path}>
              <span className="font-mono">{e.name}</span>{" "}
              <StatusBadge state={e.ready ? "ok" : "building"} />
              {!!e.missing?.length && (
                <span className="text-danger"> · Missing: {e.missing.join(", ")}</span>)}
              <span className="block text-xs text-text-dim">{e.path}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
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

  if (!list) {
    return (
      <Card title="Environments">
        {error ? <ErrorState title="Couldn't load environments" error={error} onRetry={() => { setError(""); load(); }} />
          : <Skeleton variant="row" label="Loading environments" />}
      </Card>
    );
  }
  return (
    <div className="space-y-6">
      <div className="flex">
        <Button icon={<PlusIcon />} className="ml-auto" onClick={() => setDialog(true)}>
          Build environment…</Button>
      </div>
      {dialog && (
        <Card title="Build environment">
          {error && <p role="alert" className="mb-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}
          <label className="block text-sm text-text-dim">Name
            <input className={field} value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label className="block text-sm text-text-dim">Packages
            <input className={field} value={packages} placeholder="torch transformers"
                   onChange={(e) => setPackages(e.target.value)} /></label>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setDialog(false)}>Cancel</Button>
            <Button disabled={!name} onClick={start}>Start build</Button>
          </div>
        </Card>
      )}
      {list.builds.length > 0 && (
        <Card title="Builds">
          <ul className="space-y-1 text-sm">
            {list.builds.map((b) => (
              <li key={b.job_id}>
                <span className="font-mono">{b.name}</span> <StatusBadge state={b.state} />
                {b.missing.length > 0 && <span className="text-danger"> · Missing: {b.missing.join(", ")}</span>}
                {" · "}<Link href={`/jobs/${b.job_id}`} className="text-accent">Build log</Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Table title="Prebuilt" rows={list.prebuilt} />
      <Table title="My environments" rows={list.mine} />
      <Table title="Container images" rows={list.images} />
    </div>
  );
}
