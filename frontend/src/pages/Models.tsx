import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { formatBytes } from "../api/files";
import { type Library, type ModelEntry, models } from "../api/models";
import { usePolled } from "../api/poll";
import { Link } from "../app/navigation";
import { Card } from "../components/ui/Card";
import { ModelIcon } from "../components/icons";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { StatusBadge } from "../components/ui/StatusBadge";
import { field } from "./NewJob/StepInputs";

function Table({ title, rows }: { title: string; rows: ModelEntry[] }) {
  return (
    <div className="mb-4">
      <h3 className="mb-1 text-sm font-medium text-text-dim">{title}</h3>
      {rows.length === 0 ? <EmptyState icon={<ModelIcon />} title="Nothing here yet" className="py-6" /> : (
        <table className="w-full text-left text-sm">
          <tbody>
            {rows.map((m) => (
              <tr key={m.name} className="border-t border-border">
                <td className="py-1 font-mono">{m.name}</td>
                <td>{m.bytes == null ? "" : formatBytes(m.bytes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** The model library and HuggingFace downloads (as jobs on the cluster). */
export function Models() {
  const [library, setLibrary] = useState<Library | null>(null);
  const [repo, setRepo] = useState("");
  const [revision, setRevision] = useState("");
  const [token, setToken] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const loadLibrary = useCallback(() => { models.library().then(setLibrary, () => setLibrary(null)); }, []);
  const { data: downloads } = usePolled(models.downloads, 5000);
  useEffect(loadLibrary, [loadLibrary]);

  async function start() {
    setNote("");
    setBusy(true);
    try {
      const r = await models.download(repo.trim(), revision.trim(), token.trim());
      setNote(`Started job ${r.job_id}.`);
      setRepo("");
      setRevision("");
      setToken("");   // gone as soon as it is sent: it is never kept
    } catch (e) {
      setNote(e instanceof ApiError && e.message ? e.message : "The download didn't start.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card title="Models">
        {library === null ? <Skeleton variant="row" count={2} label="Loading models" /> : (
          <>
            <Table title="Shared models" rows={library.shared} />
            <Table title="My models" rows={library.mine} />
          </>
        )}
      </Card>
      <Card title="Download from HuggingFace">
        <div className="max-w-xl text-sm">
          <label className="block text-text-dim">Repository
            <input className={field} placeholder="meta-llama/Llama-3.1-8B" value={repo}
                   onChange={(e) => setRepo(e.target.value)} />
          </label>
          <label className="block text-text-dim">Revision (optional)
            <input className={field} placeholder="main" value={revision}
                   onChange={(e) => setRevision(e.target.value)} />
          </label>
          <label className="block text-text-dim">HuggingFace token (only for gated or private models)
            <input className={field} type="password" autoComplete="off" value={token}
                   onChange={(e) => setToken(e.target.value)} />
          </label>
          <p className="mb-3 text-text-dim">
            The token is used for this download only. It isn't saved, so you'll enter it again next time.
          </p>
          <Button loading={busy} disabled={!repo.trim()} onClick={start}>Download</Button>
          {note && <p role="status" className="mt-3 rounded-md bg-surface-2 px-3 py-2">{note}</p>}
        </div>
      </Card>
      <Card title="Recent downloads">
        {(downloads ?? []).length === 0 ? <EmptyState icon={<ModelIcon />} title="No downloads yet" className="py-6" /> : (
          <ul className="space-y-1 text-sm">
            {(downloads ?? []).map((d) => (
              <li key={d.job_id} className="flex flex-wrap gap-3">
                <span className="font-mono">{d.repo_id}</span>
                <StatusBadge state={d.state === "done" ? "ok" : d.state === "running" ? "running" : "failed"} />
                {d.state === "done" && d.bytes != null && <span>{formatBytes(d.bytes)}</span>}
                {d.message && <span className="text-danger">{d.message}</span>}
                <Link href={`/jobs/${d.job_id}`} className="text-accent">Log</Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
