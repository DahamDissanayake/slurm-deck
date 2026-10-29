import { type DragEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../api/client";
import { type Entry, files, filesHref, join, type Root } from "../api/files";
import { match, navigate, useLocation } from "../app/navigation";
import { Breadcrumbs } from "../components/Breadcrumbs";
import { actionsFor, type FileAction, type FileHandlers } from "../components/files/actions";
import { ContextMenu } from "../components/files/ContextMenu";
import { DetailsPane } from "../components/files/DetailsPane";
import { FileGrid, type Sort, sortEntries } from "../components/files/FileGrid";
import { FileToolbar } from "../components/files/FileToolbar";
import { FolderTree, Places } from "../components/files/Places";
import { SelectionBar } from "../components/files/SelectionBar";
import { FilePicker } from "../components/FilePicker";
import { FolderIcon, UploadIcon } from "../components/icons";
import { TextEditor } from "../components/TextEditor";
import { type Incoming, UploadPanel } from "../components/UploadPanel";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorState } from "../components/ui/ErrorState";
import { Notice } from "../components/ui/Notice";
import { Skeleton } from "../components/ui/Skeleton";

const open = (path: string) => navigate(filesHref(path));
const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");
const message = (e: unknown, fallback: string) => (e instanceof ApiError && e.message ? e.message : fallback);

/** The file workspace: places and folders on the left, the folder in the
 * middle (list or grid, drag files in to upload), and details on the right.
 * Shared areas are read-only, so their write actions aren't offered. */
export function Files() {
  const { pathname } = useLocation();
  const rest = match("/files/*", pathname)?.["*"];
  const [roots, setRoots] = useState<Root[] | null>(null);
  const [rootsError, setRootsError] = useState<unknown>(null);
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [error, setError] = useState("");
  const [selection, setSelection] = useState<Set<string>>(new Set());
  const [view, setView] = useState<"list" | "grid">("list");
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<Sort>({ key: "name", asc: true });
  const [editing, setEditing] = useState<string | null>(null);
  const [moving, setMoving] = useState(false);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const [incoming, setIncoming] = useState<Incoming | null>(null);
  const [dragging, setDragging] = useState(false);
  const depth = useRef(0);

  const loadRoots = useCallback(() => {
    setRootsError(null);
    files.roots().then((r) => setRoots(r.roots), setRootsError);
  }, []);
  useEffect(loadRoots, [loadRoots]);

  const dir = rest ? `/${rest}` : roots?.[0]?.path ?? "";
  const root = roots?.find((r) => dir === r.path || dir.startsWith(`${r.path}/`));
  const writable = root?.writable ?? false;

  const reload = useCallback(() => {
    if (!dir) return;
    setSelection(new Set());
    setEditing(null);
    setLoadError(null);
    setEntries(null);
    files.list(dir).then((r) => setEntries(r.entries), setLoadError);
  }, [dir]);
  useEffect(reload, [reload]);

  const shown = useMemo(() => sortEntries((entries ?? []).filter(
    (e) => e.name.toLowerCase().includes(filter.trim().toLowerCase())), sort), [entries, filter, sort]);
  const selected = (entries ?? []).filter((e) => selection.has(e.name));
  const one = selected.length === 1 ? selected[0] : null;
  const pathOf = (e: Entry) => join(dir, e.name);

  async function act(action: () => Promise<unknown>) {
    setError("");
    try {
      await action();
      reload();
    } catch (e) {
      setError(message(e, "That didn't work."));
      reload();
    }
  }

  const toggle = (e: Entry) => setSelection((s) => {
    const next = new Set(s);
    if (!next.delete(e.name)) next.add(e.name);
    return next;
  });
  const selectOnly = (e: Entry) => { setSelection(new Set([e.name])); setEditing(null); };

  function download() {
    selected.forEach((e, i) => setTimeout(() => {
      const a = document.createElement("a");
      a.href = files.downloadUrl(pathOf(e));
      a.download = e.name;
      a.click();
    }, i * 250));
  }
  function newFolder() {
    const name = window.prompt("New folder name");
    if (name) act(() => files.mkdir(join(dir, name)));
  }
  function rename() {
    const name = one && window.prompt("New name", one.name);
    if (one && name && name !== one.name) act(() => files.rename(pathOf(one), join(dir, name)));
  }
  function remove() {
    const what = one ? one.name : `${selected.length} items`;
    if (!selected.length || !window.confirm(`Delete ${what}? This can't be undone.`)) return;
    act(async () => { for (const e of selected) await files.remove(pathOf(e), e.type === "dir"); });
  }

  const handlers: FileHandlers = {
    open: () => one && open(pathOf(one)),
    download,
    edit: () => one && setEditing(pathOf(one)),
    rename,
    move: () => setMoving(true),
    extract: () => act(async () => { for (const e of selected) await files.extract(pathOf(e), dir); }),
    delete: remove,
  };
  const actions = actionsFor(selected, writable);

  function onContext(entry: Entry, x: number, y: number) {
    if (!selection.has(entry.name)) setSelection(new Set([entry.name]));
    setMenu({ x, y });
  }
  const run = (id: FileAction["id"]) => handlers[id]();

  function onDrop(e: DragEvent) {
    if (!writable || !hasFiles(e)) return;
    e.preventDefault();
    depth.current = 0;
    setDragging(false);
    const dropped = Array.from(e.dataTransfer.files);
    if (dropped.length) setIncoming({ files: dropped, id: Date.now() });
  }
  const drag = writable ? {
    onDragEnter: (e: DragEvent) => { if (hasFiles(e)) { e.preventDefault(); depth.current++; setDragging(true); } },
    onDragOver: (e: DragEvent) => { if (hasFiles(e)) e.preventDefault(); },
    onDragLeave: (e: DragEvent) => { if (hasFiles(e) && --depth.current <= 0) { depth.current = 0; setDragging(false); } },
    onDrop,
  } : {};

  if (rootsError) {
    return <Card><ErrorState title="Couldn't load your files" error={rootsError} onRetry={loadRoots} /></Card>;
  }
  if (!roots) return <Card><Skeleton variant="row" count={5} label="Loading files" /></Card>;

  let listing;
  if (loadError) {
    listing = <ErrorState title="This folder can't be opened" error={loadError} onRetry={reload} />;
  } else if (entries === null) {
    listing = <Skeleton variant="row" count={6} label="Loading files" />;
  } else if (entries.length === 0) {
    listing = <EmptyState icon={<FolderIcon />} title="This folder is empty">
      {writable ? "Drag files here, or use Upload, to add some." : "Nothing has been shared here yet."}
    </EmptyState>;
  } else if (shown.length === 0) {
    listing = <EmptyState title="No files match">Nothing here has "{filter}" in its name.</EmptyState>;
  } else {
    listing = <FileGrid entries={shown} view={view} selected={selection} onToggle={toggle}
                        onSelectOnly={selectOnly} onOpenDir={(name) => open(join(dir, name))} onContext={onContext} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
        <div className="shrink-0 space-y-4 lg:w-56">
          <Places roots={roots} root={root} />
          {root && <FolderTree root={root} dir={dir} />}
        </div>
        <section aria-label="Files" {...drag}
                 className="relative min-w-0 flex-1 rounded-lg border border-border bg-surface p-4 shadow-sm">
          {editing ? (
            <TextEditor path={editing} onClose={() => { setEditing(null); reload(); }} />
          ) : (
            <>
              <FileToolbar writable={writable} view={view} onView={setView} filter={filter} onFilter={setFilter}
                           sort={sort} onSort={setSort} onNewFolder={newFolder}
                           onUpload={(f) => f.length && setIncoming({ files: f, id: Date.now() })} />
              {root && <Breadcrumbs root={root} path={dir} onOpen={open} />}
              {error && <Notice tone="danger" alert className="mb-3">{error}</Notice>}
              {selected.length > 0 && (
                <SelectionBar count={selected.length} actions={actions} handlers={handlers}
                              onClear={() => setSelection(new Set())} />
              )}
              {listing}
            </>
          )}
          {dragging && (
            <div className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-accent bg-surface opacity-95">
              <UploadIcon className="h-8 w-8 text-accent" />
              <p className="text-md font-semibold text-text">Drop to upload</p>
              <p className="text-sm text-text-dim">into {root && dir === root.path ? root.label : dir.split("/").pop()}</p>
            </div>
          )}
        </section>
        {one && !editing && (
          <div className="shrink-0 lg:w-80"><DetailsPane entry={one} path={pathOf(one)} /></div>
        )}
      </div>
      {writable && (
        <div className="sticky bottom-4 z-30 ml-auto w-full max-w-md">
          <UploadPanel destDir={dir} onDone={reload} incoming={incoming} />
        </div>
      )}
      {menu && actions.length > 0 && (
        <ContextMenu x={menu.x} y={menu.y} label={one ? `Actions for ${one.name}` : "Actions"} items={actions}
                     onSelect={run} onClose={() => setMenu(null)} />
      )}
      {moving && selected.length > 0 && (
        <FilePicker mode="dir" onClose={() => setMoving(false)}
                    onPick={(to) => act(async () => { for (const e of selected) await files.rename(pathOf(e), join(to, e.name)); })} />
      )}
    </div>
  );
}
