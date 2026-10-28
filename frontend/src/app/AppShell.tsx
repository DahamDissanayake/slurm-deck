import { type ReactNode, useCallback, useEffect, useState } from "react";

import { getMe, type Me, stopViewing } from "../api/auth";
import { useLive } from "../api/live";
import { useLocation } from "./navigation";
import { Drawer, navFor, Sidebar, useRailExpanded } from "./Sidebar";
import { TopBar } from "./TopBar";

/** The signed-in frame: the icon rail (a drawer on small screens), the top
 * bar and a page container. */
export function AppShell({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [expanded, toggle] = useRailExpanded();
  const [drawer, setDrawer] = useState(false);
  const live = useLive();
  const { pathname } = useLocation();
  const load = useCallback(() => {
    getMe().then(setMe).catch(() => {});   // a 401 has already gone to /sign-in
  }, []);
  useEffect(load, [load]);

  if (!me) return <div className="p-8 text-text-dim">Loading…</div>;
  const nav = navFor(me.account.role);

  return (
    <div className="flex min-h-screen bg-bg">
      <Sidebar items={nav} pathname={pathname} expanded={expanded} onToggle={toggle} />
      {drawer && <Drawer items={nav} pathname={pathname} onClose={() => setDrawer(false)} />}
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar pathname={pathname} name={me.account.full_name} actingAs={me.acting_as?.username ?? null}
                live={live} onMenu={() => setDrawer(true)} onStopViewing={() => stopViewing().then(load)} />
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-8">{children}</main>
      </div>
    </div>
  );
}
