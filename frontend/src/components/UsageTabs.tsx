import { Link, useLocation } from "../app/navigation";

const TABS = [["/usage", "Usage"], ["/usage/hardware", "Hardware stats"],
              ["/usage/cluster", "Cluster status"]] as const;

/** The three pages under Usage. */
export function UsageTabs() {
  const { pathname } = useLocation();
  return (
    <nav aria-label="Usage" className="mb-4 flex gap-4 border-b border-border text-sm">
      {TABS.map(([href, label]) => (
        <Link key={href} href={href}
              className={`-mb-px border-b-2 px-1 pb-2 ${pathname === href
                ? "border-accent text-accent" : "border-transparent text-text-dim"}`}>
          {label}
        </Link>
      ))}
    </nav>
  );
}
