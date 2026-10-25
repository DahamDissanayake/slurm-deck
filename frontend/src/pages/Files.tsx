import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { ARCHIVE, type Entry, files, join, parent, type Root } from "../api/files";
import { match, navigate, useLocation } from "../app/navigation";
import { Breadcrumbs } from "../components/Breadcrumbs";
import { FilePicker } from "../components/FilePicker";
import { FileTable } from "../components/FileTable";
import { Panel } from "../components/Panel";
import { Preview } from "../components/Preview";
import { TextEditor } from "../components/TextEditor";
import { UploadPanel } from "../components/UploadPanel";
import { danger } from "../components/controls";
import { secondary } from "./NewJob/StepInputs";

const EDIT_MAX = 1024 * 1024;
const open = (path: string) => navigate(`/files${path.split("/").map(encodeURIComponent).join("/")}`);

/** The file manager: the user's areas, one folder at a time. Shared areas
 * are read-only, so their write actions aren't offered. */
export function Files() {
  const { pathname } = useLocation();
  const rest = match("/files/*", pathname)?.["*"];
  const [roots, setRoots] = useState<Root[]>([]);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [selected, setSelected] = useState<Entry | null>(null);
  const [editing, setEditing] = useState(false);
  const [moving, setMoving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { files.roots().then((r) => setRoots(r.roots), () => setRoots([])); }, []);
  const dir = rest ? `/${rest}` : roots[0]?.path ?? "";
  const root = roots.find((r) => dir === r.path || dir.startsWith(`${r.path}/`));

  const reload = useCallback(() => {
    if (!dir) return;
    setSelected(null);
    setEditing(false);
    files.list(dir).then((r) => { setEntries(r.entries); setError(""); },
      (e) => setError(e instanceof ApiError && e.message ? e.message : "This folder can't be opened."));
  }, [dir]);
  useEffect(reload, [reload]);

  async function act(action: () => Promise<unknown>) {
    setError("");
    try {
      await action();
      reload();
    } catch (e) {
      setError(e instanceof ApiError && e.message ? e.message : "That didn't work.");
    }
  }

  const path = selected ? join(dir, selected.name) : "";
  const writable = root?.writable ?? false;
  function newFolder() {
    const name = window.prompt("New folder name");
    if (name) act(() => files.mkdir(join(dir, name)));
  }
  function rename() {
    const name = selected && window.prompt("New name", selected.name);
    if (name && name !== selected?.name) act(() => files.rename(path, join(dir, name)));
  }
  function remove() {
    if (!selected || !window.confirm(`Delete ${selected.name}? This can't be undone.`)) return;
    act(() => files.remove(path, selected.type === "dir"));
  }

  return (
    <div className="flex flex-col gap-4 md:flex-row">
      <nav aria-label="Areas" className="flex shrink-0 flex-col gap-1 md:w-48">
        {roots.map((r) => (
          <button key={r.path} type="button" onClick={() => open(r.path)}
                  className={`text-left text-sm ${r === root ? "text-accent" : "text-text-dim"}`}>
            {r.label}{!r.writable && " (read-only)"}
          </button>
        ))}
      </nav>
      <Panel title="Files" className="min-w-0 flex-1">
        {root && <Breadcrumbs root={root} path={dir} onOpen={open} />}
        <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
          {!writable && root && (
            <span className="rounded-sm border border-border px-2 py-1 text-text-dim">Read-only</span>
          )}
          {writable && <button type="button" className={secondary} onClick={newFolder}>New folder</button>}
          {selected && (
            <button type="button" className={secondary}
                    onClick={() => window.location.assign(files.downloadUrl(path))}>Download</button>
          )}
          {selected && writable && (
            <>
              {selected.type === "file" && selected.size <= EDIT_MAX && (
                <button type="button" className={secondary} onClick={() => setEditing(true)}>Edit</button>
              )}
              <button type="button" className={secondary} onClick={rename}>Rename</button>
              <button type="button" className={secondary} onClick={() => setMoving(true)}>Move</button>
              {ARCHIVE.test(selected.name) && (
                <button type="button" className={secondary}
                        onClick={() => act(() => files.extract(path, dir))}>Extract</button>
              )}
              <button type="button" className={`${danger}`} onClick={remove}>Delete</button>
            </>
          )}
        </div>
        {error && <p role="alert" className="mb-3 text-danger">{error}</p>}
        {writable && <div className="mb-3"><UploadPanel destDir={dir} onDone={reload} /></div>}
        {dir !== root?.path && root && (
          <button type="button" className="mb-1 font-mono text-sm text-text-dim"
                  onClick={() => open(parent(dir))}>..</button>
        )}
        <FileTable entries={entries} selected={selected?.name ?? null}
                   onOpenDir={(name) => open(join(dir, name))}
                   onSelect={(e) => { setSelected(e); setEditing(false); }} />
        {selected?.type === "file" && (
          <div className="mt-4 border-t border-border pt-4">
            {editing ? <TextEditor path={path} onClose={() => setEditing(false)} /> : <Preview path={path} />}
          </div>
        )}
      </Panel>
      {moving && selected && (
        <FilePicker mode="dir" onClose={() => setMoving(false)}
                    onPick={(to) => act(() => files.rename(path, join(to, selected.name)))} />
      )}
    </div>
  );
}
