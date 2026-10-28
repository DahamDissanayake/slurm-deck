import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { formatBytes } from "../api/files";
import { type Library, type ModelEntry, models } from "../api/models";
import { usePolled } from "../api/poll";
import { Link } from "../app/navigation";
import { Panel } from "../components/Panel";
import { field, primary } from "./NewJob/StepInputs";

function Table({ title, rows }: { title: string; rows: ModelEntry[] }) {
  return (
    <div className="mb-4">
      <h3 className="mb-1 text-sm text-text-dim">{title}</h3>
      {rows.length === 0 ? <p className="text-sm text-text-dim">Nothing here yet.</p> : (
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
  const loadLibrary = useCallback(() => { models.library().then(setLibrary, () => setLibrary(null)); }, []);
  const { data: downloads } = usePolled(models.downloads, 5000);
  useEffect(loadLibrary, [loadLibrary]);

  async function start() {
    setNote("");
    try {
      const r = await models.download(repo.trim(), revision.trim(), token.trim());
      setNote(`Started job ${r.job_id}.`);
      setRepo("");
      setRevision("");
      setToken("");   // gone as soon as it is sent: it is never kept
    } catch (e) {
      setNote(e instanceof ApiError && e.message ? e.message : "The download didn't start.");
    }
  }

  return (
    <div className="space-y-6">
      <Panel title="Models">
        <Table title="Shared models" rows={library?.shared ?? []} />
        <Table title="My models" rows={library?.mine ?? []} />
      </Panel>
      <Panel title="Download from HuggingFace">
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
          <button type="button" className={primary} disabled={!repo.trim()} onClick={start}>
            Download
          </button>
          {note && <p role="status" className="mt-2">{note}</p>}
        </div>
      </Panel>
      <Panel title="Recent downloads">
        {(downloads ?? []).length === 0 ? <p className="text-sm text-text-dim">No downloads yet.</p> : (
          <ul className="space-y-1 text-sm">
            {(downloads ?? []).map((d) => (
              <li key={d.job_id} className="flex flex-wrap gap-3">
                <span className="font-mono">{d.repo_id}</span>
                <span>{d.state === "done" ? `Done${d.bytes != null ? `, ${formatBytes(d.bytes)}` : ""}`
                  : d.state === "running" ? "Downloading…" : "Failed"}</span>
                {d.message && <span className="text-danger">{d.message}</span>}
                <Link href={`/jobs/${d.job_id}`} className="text-accent">Log</Link>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
