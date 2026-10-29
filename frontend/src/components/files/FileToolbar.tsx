import type { ReactNode } from "react";

import { FolderIcon, GridIcon, ListIcon, LockIcon, PlusIcon, SearchIcon, SortIcon, UploadIcon } from "../icons";
import { buttonClass, Button } from "../ui/Button";
import { cx } from "../ui/cx";
import { Menu } from "../ui/Menu";
import { SegmentedControl } from "../ui/SegmentedControl";
import type { Sort, SortKey } from "./FileGrid";

const SORTS: [SortKey, string][] = [["name", "Name"], ["size", "Size"], ["mtime", "Modified"]];
const pick = "focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent";

function UploadInput({ label, folder, onFiles, children, className }: {
  label: string; folder?: boolean; onFiles: (files: File[]) => void; children: ReactNode; className: string;
}) {
  return (
    <label className={cx(className, "cursor-pointer gap-2 [&>svg]:h-4 [&>svg]:w-4", pick)} title={label}>
      {children}
      <input type="file" multiple aria-label={label} className="sr-only"
             onChange={(e) => { onFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }}
             {...(folder ? { webkitdirectory: "" } : {})} />
    </label>
  );
}

/** Upload, new folder, filter, sort and the list/grid switch. Write actions
 * are left out of a read-only area, which says so instead. */
export function FileToolbar({ writable, view, onView, filter, onFilter, sort, onSort, onUpload, onNewFolder }: {
  writable: boolean; view: "list" | "grid"; onView: (v: "list" | "grid") => void;
  filter: string; onFilter: (q: string) => void; sort: Sort; onSort: (s: Sort) => void;
  onUpload: (files: File[]) => void; onNewFolder: () => void;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      {writable ? (
        <>
          <UploadInput label="Upload files" onFiles={onUpload} className={buttonClass({ size: "sm", pill: true })}>
            <UploadIcon />Upload
          </UploadInput>
          <UploadInput label="Upload folder" folder onFiles={onUpload}
                       className={buttonClass({ variant: "secondary", size: "sm", square: true })}>
            <FolderIcon />
          </UploadInput>
          <Button variant="secondary" size="sm" pill icon={<PlusIcon />} onClick={onNewFolder}>New folder</Button>
        </>
      ) : (
        <span className="inline-flex h-8 items-center gap-1.5 rounded-full bg-neutral-soft px-3 text-sm text-text-dim">
          <LockIcon className="h-3.5 w-3.5" />Read-only
        </span>
      )}
      <div className="ml-auto flex flex-wrap items-center gap-2">
        <label className="relative">
          <span aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-dim [&>svg]:h-4 [&>svg]:w-4">
            <SearchIcon />
          </span>
          <input type="search" aria-label="Filter files" placeholder="Filter" value={filter}
                 onChange={(e) => onFilter(e.target.value)}
                 className="h-8 w-40 rounded-full border border-border bg-surface pl-9 pr-3 text-md text-text placeholder:text-text-dim focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent" />
        </label>
        <Menu label="Sort files" icon={<SortIcon />} tooltipSide="bottom"
              items={SORTS.map(([key, label]) => ({
                label: key === sort.key ? `${label} ${sort.asc ? "↑" : "↓"}` : label,
                onSelect: () => onSort({ key, asc: key === sort.key ? !sort.asc : true }),
              }))} />
        <SegmentedControl label="View" value={view} onChange={onView}
                          options={[{ value: "list", label: "List", icon: <ListIcon /> },
                                    { value: "grid", label: "Grid", icon: <GridIcon /> }]} />
      </div>
    </div>
  );
}
