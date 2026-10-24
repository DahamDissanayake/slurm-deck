import { useEffect, useState } from "react";

import { type Entry, files, join, type Root } from "../api/files";
import { primary, secondary } from "../pages/NewJob/StepInputs";
import { Breadcrumbs } from "./Breadcrumbs";
import { FileTable } from "./FileTable";

/** A modal that browses the user's areas and returns an absolute path: a
 * file (optionally only with one of the accept extensions) or a folder. */
export function FilePicker({ mode, accept, onPick, onClose }: {
  mode: "file" | "dir"; accept?: string[]; onPick: (path: string) => void; onClose: () => void;
}) {
  const [roots, setRoots] = useState<Root[]>([]);
  const [dir, setDir] = useState("");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [selected, setSelected] = useState<Entry | null>(null);

  useEffect(() => {
    files.roots().then((r) => { setRoots(r.roots); setDir(r.roots[0]?.path ?? ""); }, () => {});
  }, []);
  useEffect(() => {
    if (!dir) return;
    setSelected(null);
    files.list(dir).then((r) => setEntries(r.entries.filter((e) => e.type === "dir" || (
      mode === "file" && (!accept || accept.some((x) => e.name.endsWith(x)))))), () => setEntries([]));
  }, [dir, mode, accept]);

  const root = roots.find((r) => dir === r.path || dir.startsWith(`${r.path}/`));
  const choice = selected ? join(dir, selected.name) : mode === "dir" ? dir : "";
  return (
    <div role="dialog" aria-modal="true" aria-label={mode === "dir" ? "Choose a folder" : "Choose a file"}
         className="fixed inset-0 z-20 flex items-center justify-center bg-bg/80 p-4">
      <div className="max-h-full w-full max-w-2xl overflow-auto rounded-sm border border-border bg-surface p-4">
        <select aria-label="Area" className="mb-3 bg-surface-2 p-1" value={root?.path ?? ""}
                onChange={(e) => setDir(e.target.value)}>
          {roots.map((r) => <option key={r.path} value={r.path}>{r.label}</option>)}
        </select>
        {root && <Breadcrumbs root={root} path={dir} onOpen={setDir} />}
        <FileTable entries={entries} selected={selected?.name ?? null}
                   onOpenDir={(name) => setDir(join(dir, name))}
                   onSelect={(e) => setSelected(mode === "file" && e.type === "dir" ? null : e)} />
        <div className="mt-3 flex items-center gap-2">
          <span className="flex-1 truncate font-mono text-xs text-text-dim">{choice}</span>
          <button type="button" className={secondary} onClick={onClose}>Cancel</button>
          <button type="button" className={primary} disabled={!choice}
                  onClick={() => { onPick(choice); onClose(); }}>Choose</button>
        </div>
      </div>
    </div>
  );
}
