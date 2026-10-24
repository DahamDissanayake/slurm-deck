import { Link, match, useLocation } from "../../app/navigation";
import { AppAccess } from "./AppAccess";
import { NewUser } from "./NewUser";
import { Requests } from "./Requests";
import { UserDetail } from "./UserDetail";
import { Users } from "./Users";

// Later phases add Settings, Jobs, Usage, Cluster, Shared assets and Monitoring.
const TABS = [["/admin/requests", "Requests"], ["/admin/users", "Users"],
              ["/admin/access", "Application access"]] as const;

function Page({ path }: { path: string }) {
  if (match("/admin/users/new", path)) return <NewUser />;
  const user = match("/admin/users/:id", path);
  if (user) return <UserDetail id={Number(user.id)} />;
  if (match("/admin/users", path)) return <Users />;
  if (match("/admin/access", path)) return <AppAccess />;
  return <Requests />;
}

/** The admin area: a sub-navigation and the chosen admin page. */
export function AdminLayout() {
  const { pathname } = useLocation();
  return (
    <div>
      <nav aria-label="Admin" className="mb-6 flex gap-4 border-b border-border">
        {TABS.map(([href, label]) => {
          const on = pathname.startsWith(href) || (href === "/admin/requests" && pathname === "/admin");
          return (
            <Link key={href} href={href}
                  className={`-mb-px border-b-2 px-1 pb-2 text-sm ${on
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

export const inputClass =
  "w-full rounded-sm border border-border bg-surface-2 px-3 py-2 text-text";
export const smallButton =
  "rounded-sm border border-border px-3 py-1 text-sm text-text hover:border-accent disabled:opacity-50";
export const primaryButton =
  "rounded-sm bg-accent px-4 py-2 font-semibold text-bg disabled:opacity-50";
