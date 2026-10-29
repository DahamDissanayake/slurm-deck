import type { Root } from "../api/files";
import { ChevronRightIcon } from "./icons";
import { focusRing } from "./ui/cx";

/** The path from its area root down, each part clickable. */
export function Breadcrumbs({ root, path, onOpen }: {
  root: Root; path: string; onOpen: (path: string) => void;
}) {
  const rest = path.slice(root.path.length).split("/").filter(Boolean);
  const crumbs = [{ label: root.label, path: root.path },
    ...rest.map((name, i) => ({ label: name, path: [root.path, ...rest.slice(0, i + 1)].join("/") }))];
  return (
    <nav aria-label="Folder" className="mb-3 flex flex-wrap items-center gap-0.5 text-md">
      {crumbs.map((c, i) => (
        <span key={c.path} className="flex items-center gap-0.5">
          {i > 0 && <ChevronRightIcon className="h-3.5 w-3.5 text-text-dim" />}
          <button type="button" aria-current={i === crumbs.length - 1 ? "page" : undefined} onClick={() => onOpen(c.path)}
                  className={`rounded-sm px-1.5 py-0.5 hover:bg-surface-2 ${focusRing} ${i === crumbs.length - 1
                    ? "font-medium text-text" : "text-text-dim hover:text-text"}`}>
            {c.label}
          </button>
        </span>
      ))}
    </nav>
  );
}
