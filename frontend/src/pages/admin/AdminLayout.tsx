import { Link, match, useLocation } from "../../app/navigation";
import { full, input, primary, small } from "../../components/controls";
import { AppAccess } from "./AppAccess";
import { Cluster } from "./Cluster";
import { JobsAdmin } from "./JobsAdmin";
import { Monitoring } from "./Monitoring";
import { NewUser } from "./NewUser";
import { Requests } from "./Requests";
import { Settings } from "./Settings";
import { SharedAssets } from "./SharedAssets";
import { UserDetail } from "./UserDetail";
import { UsageAdmin } from "./UsageAdmin";
import { Users } from "./Users";

const TABS = [["/admin/requests", "Requests"], ["/admin/users", "Users"],
              ["/admin/access", "Application access"], ["/admin/usage", "Usage"],
              ["/admin/jobs", "Jobs"], ["/admin/cluster", "Cluster"],
              ["/admin/shared", "Shared assets"], ["/admin/settings", "Settings"],
              ["/admin/monitoring", "Monitoring"]] as const;

function Page({ path }: { path: string }) {
  if (match("/admin/users/new", path)) return <NewUser />;
  const user = match("/admin/users/:id", path);
  if (user) return <UserDetail id={Number(user.id)} />;
  if (match("/admin/users", path)) return <Users />;
  if (match("/admin/access", path)) return <AppAccess />;
  if (match("/admin/usage", path)) return <UsageAdmin />;
  if (match("/admin/jobs", path)) return <JobsAdmin />;
  if (match("/admin/cluster", path)) return <Cluster />;
  if (match("/admin/shared", path)) return <SharedAssets />;
  if (match("/admin/settings", path)) return <Settings />;
  if (match("/admin/monitoring", path)) return <Monitoring />;
  return <Requests />;
}

/** The admin area: a sub-navigation and the chosen admin page. */
export function AdminLayout() {
  const { pathname } = useLocation();
  return (
    <div>
      <nav aria-label="Admin" className="mb-6 flex gap-4 overflow-x-auto border-b border-border">
        {TABS.map(([href, label]) => {
          const on = pathname.startsWith(href) || (href === "/admin/requests" && pathname === "/admin");
          return (
            <Link key={href} href={href}
                  aria-current={on ? "page" : undefined}
                  className={`-mb-px whitespace-nowrap border-b-2 px-1 pb-2 text-sm font-medium transition-colors duration-fast hover:text-text ${on
                    ? "border-accent text-accent" : "border-transparent text-text-dim"}`}>
              {label}
            </Link>
          );
        })}
      </nav>
      <Page path={pathname} />
    </div>
  );
}

export const inputClass = `${input} ${full}`;
export const smallButton = small;
export const primaryButton = primary;
