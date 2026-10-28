import type { Root } from "../api/files";

/** The path from its area root down, each part clickable. */
export function Breadcrumbs({ root, path, onOpen }: {
  root: Root; path: string; onOpen: (path: string) => void;
}) {
  const rest = path.slice(root.path.length).split("/").filter(Boolean);
  const crumbs = [{ label: root.label, path: root.path },
    ...rest.map((name, i) => ({ label: name, path: [root.path, ...rest.slice(0, i + 1)].join("/") }))];
  return (
    <nav aria-label="Folder" className="mb-3 flex flex-wrap gap-1 font-mono text-sm">
      {crumbs.map((c, i) => (
        <span key={c.path}>
          {i > 0 && <span className="text-text-dim"> / </span>}
          <button type="button" className="hover:text-accent" onClick={() => onOpen(c.path)}>
            {c.label}
          </button>
        </span>
      ))}
    </nav>
  );
}
