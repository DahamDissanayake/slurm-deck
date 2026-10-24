import { useState } from "react";

import { type Entry, formatBytes } from "../api/files";

type SortKey = "name" | "size" | "mtime";

/** A folder's entries, sortable by name, size or modified time. Clicking a
 * folder's name opens it; a file's name, or any row's radio, selects it. */
export function FileTable({ entries, selected, onOpenDir, onSelect }: {
  entries: Entry[]; selected: string | null;
  onOpenDir: (name: string) => void; onSelect: (entry: Entry) => void;
}) {
  const [sort, setSort] = useState<{ key: SortKey; asc: boolean }>({ key: "name", asc: true });
  const rows = [...entries].sort((a, b) => {
    if ((a.type === "dir") !== (b.type === "dir")) return a.type === "dir" ? -1 : 1;
    const d = sort.key === "name" ? a.name.localeCompare(b.name) : a[sort.key] - b[sort.key];
    return sort.asc ? d : -d;
  });
  const header = (key: SortKey, label: string) => (
    <th className="px-2 py-1 text-left font-normal">
      <button type="button" onClick={() => setSort({ key, asc: sort.key === key ? !sort.asc : true })}>
        {label}{sort.key === key ? (sort.asc ? " ▲" : " ▼") : ""}
      </button>
    </th>
  );
  return (
    <table className="w-full text-sm">
      <thead className="text-text-dim">
        <tr><th />{header("name", "Name")}{header("size", "Size")}{header("mtime", "Modified")}</tr>
      </thead>
      <tbody>
        {rows.length === 0 && (
          <tr><td colSpan={4} className="px-2 py-3 text-text-dim">This folder is empty.</td></tr>
        )}
        {rows.map((e) => (
          <tr key={e.name} aria-selected={selected === e.name}
              className={selected === e.name ? "bg-surface-2" : ""}>
            <td className="w-6 px-2">
              <input type="radio" name="sd-file" aria-label={`Select ${e.name}`}
                     checked={selected === e.name} onChange={() => onSelect(e)} />
            </td>
            <td className="px-2 py-1 font-mono">
              <button type="button" className="text-left hover:text-accent"
                      onClick={() => (e.type === "dir" ? onOpenDir(e.name) : onSelect(e))}>
                {e.name}
              </button>
              {e.type === "dir" && <span className="text-text-dim">/</span>}
            </td>
            <td className="px-2 py-1">{e.type === "dir" ? "" : formatBytes(e.size)}</td>
            <td className="px-2 py-1">{new Date(e.mtime * 1000).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
