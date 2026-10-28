import { type ReactNode, useEffect, useRef, useState } from "react";

import {
  BellIcon, ChartIcon, DashboardIcon, EnvIcon, FolderIcon, JobsIcon, ModelIcon, PlusIcon, ServerIcon,
  ShieldIcon, SidebarIcon, XIcon,
} from "../components/icons";
import { cx, focusRing } from "../components/ui/cx";
import { IconButton } from "../components/ui/IconButton";
import { Tooltip } from "../components/ui/Tooltip";
import { Wordmark } from "../components/Wordmark";
import { Link } from "./navigation";

export type NavItem = { href: string; label: string; icon: ReactNode };

const NAV: NavItem[] = [
  { href: "/", label: "Dashboard", icon: <DashboardIcon /> },
  { href: "/new", label: "New job", icon: <PlusIcon /> },
  { href: "/jobs", label: "Jobs", icon: <JobsIcon /> },
  { href: "/files", label: "Files", icon: <FolderIcon /> },
  { href: "/envs", label: "Environments", icon: <EnvIcon /> },
  { href: "/models", label: "Models", icon: <ModelIcon /> },
  { href: "/services", label: "Services", icon: <ServerIcon /> },
  { href: "/usage", label: "Usage", icon: <ChartIcon /> },
  { href: "/notify", label: "Notify", icon: <BellIcon /> },
];
const ADMIN: NavItem = { href: "/admin", label: "Admin", icon: <ShieldIcon /> };

/** The nav items this role sees, in rail order. */
export const navFor = (role: string) => (role === "admin" ? [...NAV, ADMIN] : NAV);

/** The item `pathname` sits under, if any. */
export const sectionOf = (pathname: string) =>
  [...NAV, ADMIN].find(({ href }) => (href === "/" ? pathname === "/"
    : pathname === href || pathname.startsWith(`${href}/`)));

const KEY = "sd-rail";

// Storage can throw (private windows, blocked site data): the rail still
// expands, it just isn't remembered.
function storedExpanded() {
  try {
    return window.localStorage.getItem(KEY) === "expanded";
  } catch {
    return false;
  }
}

/** Whether the rail shows labels, remembered across reloads. */
export function useRailExpanded(): [boolean, () => void] {
  const [expanded, setExpanded] = useState(storedExpanded);
  const toggle = () => setExpanded((was) => {
    try {
      window.localStorage.setItem(KEY, was ? "collapsed" : "expanded");
    } catch {
      /* not remembered */
    }
    return !was;
  });
  return [expanded, toggle];
}

function NavLinks({ items, pathname, labels, onNavigate }: {
  items: NavItem[]; pathname: string; labels: boolean; onNavigate?: () => void;
}) {
  const current = sectionOf(pathname)?.href;
  return (
    <ul className="flex flex-col gap-1">
      {items.map(({ href, label, icon }) => {
        const active = href === current;
        const link = (
          <Link href={href} onClick={onNavigate} aria-current={active ? "page" : undefined}
                className={cx("relative flex h-10 items-center gap-3 rounded-md text-md font-medium",
                  "transition-colors duration-fast ease-out", focusRing,
                  labels ? "w-full px-3" : "w-10 justify-center",
                  // The one accent in the shell: a short bar against the rail edge.
                  "before:absolute before:-left-3 before:top-2 before:bottom-2 before:w-[3px] before:rounded-full",
                  active ? "bg-accent-soft text-accent before:bg-accent"
                    : "text-text-dim hover:bg-surface-2 hover:text-text before:bg-transparent")}>
            <span aria-hidden="true" className="contents [&>svg]:h-5 [&>svg]:w-5 [&>svg]:shrink-0">{icon}</span>
            <span className={labels ? "truncate" : "sr-only"}>{label}</span>
          </Link>
        );
        return (
          <li key={href} className="flex">
            {labels ? link : <Tooltip content={label} describe={false} side="right">{link}</Tooltip>}
          </li>
        );
      })}
    </ul>
  );
}

function Brand({ full }: { full: boolean }) {
  return (
    <Link href="/" className={cx("flex h-10 items-center rounded-md px-2 text-md", focusRing)}>
      {full ? <Wordmark /> : <span aria-label="Slurm Deck" className="font-mono font-bold text-accent">{">_"}</span>}
    </Link>
  );
}

/** The slim icon rail on wide screens; expands to show labels. */
export function Sidebar({ items, pathname, expanded, onToggle }: {
  items: NavItem[]; pathname: string; expanded: boolean; onToggle: () => void;
}) {
  return (
    <aside className={cx("sticky top-0 hidden h-screen shrink-0 flex-col border-r border-border bg-surface px-3 py-3 md:flex",
      "motion-safe:transition-[width] motion-safe:duration-base motion-safe:ease-out", expanded ? "w-56" : "w-16")}>
      <div className={cx("mb-4 flex", !expanded && "justify-center")}><Brand full={expanded} /></div>
      {/* No overflow clipping here: the collapsed rail's tooltips sit outside it. */}
      <nav aria-label="Main" className="flex-1">
        <NavLinks items={items} pathname={pathname} labels={expanded} />
      </nav>
      <div className={cx("mt-3 flex border-t border-border pt-3", expanded ? "justify-end" : "justify-center")}>
        <IconButton label={expanded ? "Collapse sidebar" : "Expand sidebar"} icon={<SidebarIcon />}
                    aria-expanded={expanded} onClick={onToggle} />
      </div>
    </aside>
  );
}

/** The nav as a drawer on small screens. Escape, the backdrop, the close
 * button or following a link closes it. */
export function Drawer({ items, pathname, onClose }: {
  items: NavItem[]; pathname: string; onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    panel.current?.querySelector<HTMLElement>("a[aria-current]")?.focus();
  }, []);
  return (
    <div className="fixed inset-0 z-50 md:hidden">
      <div aria-hidden="true" className="absolute inset-0 bg-bg opacity-70" onClick={onClose} />
      <div ref={panel} role="dialog" aria-modal="true" aria-label="Menu"
           onKeyDown={(e) => e.key === "Escape" && onClose()}
           className="absolute inset-y-0 left-0 flex w-64 flex-col border-r border-border bg-surface p-3 shadow-lg">
        <div className="mb-4 flex items-center justify-between">
          <Brand full />
          <IconButton label="Close menu" icon={<XIcon />} tooltipSide="bottom" onClick={onClose} />
        </div>
        <nav aria-label="Main menu" className="overflow-y-auto pl-3">
          <NavLinks items={items} pathname={pathname} labels onNavigate={onClose} />
        </nav>
      </div>
    </div>
  );
}
