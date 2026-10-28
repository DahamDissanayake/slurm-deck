import { Fragment } from "react";

import type { Live } from "../api/live";
import { ChevronRightIcon, DotIcon, MenuIcon } from "../components/icons";
import { cx, focusRing } from "../components/ui/cx";
import { IconButton } from "../components/ui/IconButton";
import { Link } from "./navigation";
import { sectionOf } from "./Sidebar";
import { ThemeToggle } from "./ThemeToggle";
import { UserMenu } from "./UserMenu";
import { ViewAsPill } from "./ViewAsBanner";

// Pages outside the nav that still need a title.
const TITLES: Record<string, string> = { "/account/password": "Change password" };

type Crumb = { label: string; href: string };

const decode = (s: string) => {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
};

/** The page title and, below the top level, the trail back up to it. File
 * paths keep their own spelling; other segments read as words. */
export function crumbsFor(pathname: string): { title: string; crumbs: Crumb[] } {
  const section = sectionOf(pathname);
  if (!section) return { title: TITLES[pathname] ?? "Not found", crumbs: [] };
  const rest = pathname.slice(section.href.length).split("/").filter(Boolean);
  if (!rest.length) return { title: section.label, crumbs: [] };
  const word = (s: string) => (section.href === "/files" ? s : s.charAt(0).toUpperCase() + s.slice(1).replace(/-/g, " "));
  const crumbs = [{ label: section.label, href: section.href }];
  rest.forEach((segment, i) => {
    crumbs.push({ label: word(decode(segment)), href: `${section.href}/${rest.slice(0, i + 1).join("/")}` });
  });
  return { title: section.label, crumbs };
}

/** Pods free, maintenance or offline, in a compact chip. Never colour alone. */
function ClusterChip({ live }: { live: Live }) {
  const { connected, cluster } = live;
  const [text, tone, title] = !connected ? ["Offline", "bg-neutral-soft text-text-dim", "Not connected to the cluster"]
    : !cluster ? ["Connecting…", "bg-neutral-soft text-text-dim", "Connecting to the cluster"]
      : cluster.maintenance ? ["Maintenance", "bg-warning-soft text-warning", cluster.maintenance]
        : [`${cluster.pods_total - cluster.pods_used} of ${cluster.pods_total} pods free`,
          cluster.pods_used < cluster.pods_total ? "bg-ok-soft text-ok" : "bg-warning-soft text-warning",
          "Cluster pods free now"];
  return (
    <Link href="/" data-testid="cluster-chip" title={title}
          className={cx("hidden h-8 items-center gap-1.5 whitespace-nowrap rounded-full px-3 text-sm font-medium sm:inline-flex",
            focusRing, tone)}>
      <DotIcon className="h-3.5 w-3.5" />
      {text}
    </Link>
  );
}

/** The light bar above every signed-in page: title and breadcrumbs on the
 * left; View-as, cluster health, theme and the account menu on the right. */
export function TopBar({ pathname, name, actingAs, live, onMenu, onStopViewing }: {
  pathname: string; name: string; actingAs: string | null; live: Live;
  onMenu: () => void; onStopViewing: () => void;
}) {
  const { title, crumbs } = crumbsFor(pathname);
  return (
    <header className="sticky top-0 z-30 flex min-h-14 items-center gap-3 border-b border-border bg-bg px-4 py-2 md:px-8">
      <div className="md:hidden">
        <IconButton label="Open menu" icon={<MenuIcon />} tooltipSide="bottom" onClick={onMenu} />
      </div>
      <div className="flex min-w-0 flex-1 flex-col justify-center">
        <h1 className="truncate text-base font-semibold text-text">{title}</h1>
        {crumbs.length > 0 && (
          <nav aria-label="Breadcrumb" className="min-w-0">
            <ol className="flex min-w-0 items-center gap-1 text-xs text-text-dim">
              {crumbs.map((c, i) => (
                <Fragment key={c.href}>
                  {i > 0 && <li aria-hidden="true" className="flex shrink-0"><ChevronRightIcon className="h-3 w-3" /></li>}
                  <li className="min-w-0 truncate">
                    {i === crumbs.length - 1
                      ? <span aria-current="page" className="text-text">{c.label}</span>
                      : <Link href={c.href} className="hover:text-text hover:underline">{c.label}</Link>}
                  </li>
                </Fragment>
              ))}
            </ol>
          </nav>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <ViewAsPill actingAs={actingAs} onStop={onStopViewing} />
        <ClusterChip live={live} />
        <ThemeToggle />
        <UserMenu name={name} />
      </div>
    </header>
  );
}
