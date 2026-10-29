import type { ReactNode } from "react";

import { type Entry, formatBytes } from "../../api/files";
import { fileIcon } from "../icons";
import { Preview } from "../Preview";

const KIND = { dir: "Folder", file: "File", link: "Link", other: "Other" } as const;

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-text-dim">{label}</dt>
      <dd className="mt-0.5 break-all text-md text-text">{children}</dd>
    </div>
  );
}

/** The one selected entry: what it is, and a preview of a file. */
export function DetailsPane({ entry, path }: { entry: Entry; path: string }) {
  const Icon = fileIcon(entry.name, entry.type === "dir");
  return (
    <aside aria-label="Details" className="rounded-lg border border-border bg-surface p-4 shadow-sm">
      <div className="mb-4 flex items-center gap-3">
        <span aria-hidden="true" className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md bg-surface-2 text-text-dim">
          <Icon className="h-6 w-6" />
        </span>
        <h2 className="min-w-0 break-words font-mono text-md font-semibold text-text">{entry.name}</h2>
      </div>
      <dl className="space-y-3">
        <Fact label="Kind">{KIND[entry.type]}</Fact>
        {entry.type !== "dir" && <Fact label="Size">{formatBytes(entry.size)}</Fact>}
        <Fact label="Modified">{new Date(entry.mtime * 1000).toLocaleString()}</Fact>
        <Fact label="Location"><span className="font-mono text-sm">{path}</span></Fact>
      </dl>
      {entry.type === "file" && (
        <div className="mt-4 border-t border-border pt-4">
          <Preview path={path} />
        </div>
      )}
    </aside>
  );
}
