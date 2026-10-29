import { useEffect, useState } from "react";

import { type Entry, files, filesHref, type Root } from "../../api/files";
import { Link } from "../../app/navigation";
import { ChevronRightIcon, FolderIcon, LockIcon } from "../icons";
import { cx, focusRing } from "../ui/cx";

const row = "flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-md";

/** My files and the shared areas; the one holding the current folder is marked. */
export function Places({ roots, root }: { roots: Root[]; root: Root | undefined }) {
  return (
    <nav aria-label="Places">
      <ul className="space-y-0.5">
        {roots.map((r) => (
          <li key={r.path}>
            <Link href={filesHref(r.path)} aria-current={r === root ? "page" : undefined}
                  className={cx(row, "w-full", focusRing, r === root ? "bg-accent-soft font-medium text-accent"
                    : "text-text-dim hover:bg-surface-2 hover:text-text")}>
              <FolderIcon className="h-4 w-4 shrink-0" />
              <span className="truncate">{r.label}</span>
              {!r.writable && <LockIcon className="ml-auto h-3.5 w-3.5 shrink-0" />}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** A folder and, once opened, its subfolders; they load the first time it opens. */
function Node({ path, label, dir, depth }: { path: string; label: string; dir: string; depth: number }) {
  const onPath = dir === path || dir.startsWith(`${path}/`);
  const [open, setOpen] = useState(depth === 0 || onPath);
  const [children, setChildren] = useState<Entry[] | null>(null);

  useEffect(() => {
    if (!open || children) return;
    let stale = false;
    files.list(path).then((r) => { if (!stale) setChildren(r.entries.filter((e) => e.type === "dir")); },
      () => { if (!stale) setChildren([]); });
    return () => { stale = true; };
  }, [open, children, path]);

  const sub = [...(children ?? [])].sort((a, b) => a.name.localeCompare(b.name));
  return (
    <li>
      <div className="flex items-center" style={{ paddingLeft: depth * 12 }}>
        <button type="button" aria-label={`${open ? "Collapse" : "Expand"} ${label}`} aria-expanded={open}
                onClick={() => setOpen((o) => !o)}
                className={cx("flex h-6 w-6 shrink-0 items-center justify-center rounded-sm text-text-dim hover:text-text", focusRing)}>
          <ChevronRightIcon className={cx("h-3.5 w-3.5 motion-safe:transition-transform motion-safe:duration-fast", open && "rotate-90")} />
        </button>
        <Link href={filesHref(path)} aria-current={path === dir ? "page" : undefined}
              className={cx(row, "py-1 text-sm", focusRing, path === dir ? "bg-accent-soft font-medium text-accent"
                : "text-text-dim hover:bg-surface-2 hover:text-text")}>
          <FolderIcon className="h-4 w-4 shrink-0" />
          <span className="truncate">{label}</span>
        </Link>
      </div>
      {open && sub.length > 0 && (
        <ul>
          {sub.map((e) => <Node key={e.name} path={`${path}/${e.name}`} label={e.name} dir={dir} depth={depth + 1} />)}
        </ul>
      )}
    </li>
  );
}

/** The folders under the current place, opened down to the current folder. */
export function FolderTree({ root, dir }: { root: Root; dir: string }) {
  return (
    <nav aria-label="Folders">
      <ul><Node path={root.path} label={root.label} dir={dir} depth={0} /></ul>
    </nav>
  );
}
