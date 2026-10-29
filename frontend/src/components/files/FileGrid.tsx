import type { MouseEvent } from "react";

import { type Entry, formatBytes } from "../../api/files";
import { fileIcon } from "../icons";
import { cx, focusRing } from "../ui/cx";

export type SortKey = "name" | "size" | "mtime";
export type Sort = { key: SortKey; asc: boolean };

/** Folders first, then by the chosen column. */
export function sortEntries(entries: Entry[], sort: Sort): Entry[] {
  return [...entries].sort((a, b) => {
    if ((a.type === "dir") !== (b.type === "dir")) return a.type === "dir" ? -1 : 1;
    const d = sort.key === "name" ? a.name.localeCompare(b.name) : a[sort.key] - b[sort.key];
    return sort.asc ? d : -d;
  });
}

type Props = {
  entries: Entry[]; view: "list" | "grid"; selected: Set<string>;
  onToggle: (entry: Entry) => void; onSelectOnly: (entry: Entry) => void; onOpenDir: (name: string) => void;
  onContext: (entry: Entry, x: number, y: number) => void;
};

const when = (mtime: number) => new Date(mtime * 1000).toLocaleString();

function Checkbox({ entry, checked, onToggle, className }: {
  entry: Entry; checked: boolean; onToggle: (entry: Entry) => void; className?: string;
}) {
  return (
    <input type="checkbox" aria-label={`Select ${entry.name}`} checked={checked} onChange={() => onToggle(entry)}
           className={cx("h-4 w-4 cursor-pointer accent-accent", focusRing, className)} />
  );
}

function Name({ entry, onSelectOnly, onOpenDir, className }: {
  entry: Entry; onSelectOnly: Props["onSelectOnly"]; onOpenDir: Props["onOpenDir"]; className?: string;
}) {
  return (
    <button type="button" onClick={() => (entry.type === "dir" ? onOpenDir(entry.name) : onSelectOnly(entry))}
            className={cx("min-w-0 truncate text-left", focusRing, className)}>
      {entry.name}
    </button>
  );
}

/** A folder's entries as a table or a grid of cards, with a file-type icon
 * each. A folder's name opens it; a file's name selects it; the checkbox adds
 * to the selection; right-click asks for the row's menu. */
export function FileGrid({ entries, view, selected, onToggle, onSelectOnly, onOpenDir, onContext }: Props) {
  const context = (entry: Entry) => (e: MouseEvent) => { e.preventDefault(); onContext(entry, e.clientX, e.clientY); };

  if (view === "grid") {
    return (
      <ul aria-label="Files" className="grid grid-cols-[repeat(auto-fill,minmax(9rem,1fr))] gap-3">
        {entries.map((e) => {
          const Icon = fileIcon(e.name, e.type === "dir");
          const on = selected.has(e.name);
          return (
            <li key={e.name} onContextMenu={context(e)}
                className={cx("relative flex flex-col items-center gap-2 rounded-lg border p-3 pt-5 text-center",
                  on ? "border-accent bg-accent-soft" : "border-border bg-surface hover:bg-surface-2")}>
              <Checkbox entry={e} checked={on} onToggle={onToggle} className="absolute left-2 top-2" />
              <span aria-hidden="true" className={e.type === "dir" ? "text-accent" : "text-text-dim"}>
                <Icon className="h-10 w-10" />
              </span>
              <Name entry={e} onSelectOnly={onSelectOnly} onOpenDir={onOpenDir}
                    className="w-full font-mono text-sm text-text hover:text-accent" />
              <span className="text-xs text-text-dim">{e.type === "dir" ? "Folder" : formatBytes(e.size)}</span>
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table aria-label="Files" className="w-full text-md">
        <thead className="text-left text-xs text-text-dim">
          <tr className="border-b border-border">
            <th className="w-10 py-2 pl-3 font-medium"><span className="sr-only">Select</span></th>
            <th className="py-2 font-medium">Name</th>
            <th className="w-24 py-2 font-medium">Size</th>
            <th className="hidden w-48 py-2 pr-3 font-medium sm:table-cell">Modified</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => {
            const Icon = fileIcon(e.name, e.type === "dir");
            const on = selected.has(e.name);
            return (
              <tr key={e.name} aria-selected={on} onContextMenu={context(e)}
                  className={cx("border-b border-border last:border-0", on ? "bg-accent-soft" : "hover:bg-surface-2")}>
                <td className="py-2 pl-3"><Checkbox entry={e} checked={on} onToggle={onToggle} /></td>
                <td className="max-w-0 py-2">
                  <span className="flex items-center gap-2.5">
                    <span aria-hidden="true" className={cx("inline-flex shrink-0", e.type === "dir" ? "text-accent" : "text-text-dim")}>
                      <Icon className="h-5 w-5" />
                    </span>
                    <Name entry={e} onSelectOnly={onSelectOnly} onOpenDir={onOpenDir}
                          className="font-mono text-text hover:text-accent" />
                  </span>
                </td>
                <td className="py-2 tabular-nums text-text-dim">{e.type === "dir" ? "" : formatBytes(e.size)}</td>
                <td className="hidden py-2 pr-3 text-text-dim sm:table-cell">{when(e.mtime)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
