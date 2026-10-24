import { type ReactNode, useCallback, useEffect, useState } from "react";

import { getMe, type Me, signOut, stopViewing } from "../api/auth";
import { Wordmark } from "../components/Wordmark";
import { Link, navigate, useLocation } from "./navigation";
import { ThemeToggle } from "./ThemeToggle";
import { ViewAsBanner } from "./ViewAsBanner";

const NAV = [
  ["/", "Dashboard"], ["/new", "New job"], ["/jobs", "Jobs"], ["/files", "Files"],
  ["/envs", "Environments"], ["/models", "Models"], ["/services", "Services"],
  ["/usage", "Usage"], ["/notify", "Notify"],
] as const;

/** The signed-in frame: sidebar, top bar and the View-as banner. */
export function AppShell({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const { pathname } = useLocation();
  const load = useCallback(() => {
    getMe().then(setMe).catch(() => {});   // a 401 has already gone to /sign-in
  }, []);
  useEffect(load, [load]);

  if (!me) return <div className="p-8 text-text-dim">Loading…</div>;
  const nav = me.account.role === "admin" ? [...NAV, ["/admin", "Admin"] as const] : NAV;
  const active = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  return (
    <div className="flex min-h-screen flex-col">
      <ViewAsBanner actingAs={me.acting_as?.username ?? null}
                    onStop={() => stopViewing().then(load)} />
      <header className="flex items-center justify-between border-b border-border bg-surface px-4 py-3">
        <Link href="/"><Wordmark /></Link>
        <div id="cluster-status" className="text-sm text-text-dim" />
        <div className="flex items-center gap-3 text-sm">
          <ThemeToggle />
          <span className="text-text-dim">{me.account.full_name}</span>
          <Link href="/account/password" className="text-accent">Change password</Link>
          <button type="button" className="text-accent"
                  onClick={() => signOut().finally(() => navigate("/sign-in"))}>
            Sign out
          </button>
        </div>
      </header>
      <div className="flex flex-1">
        <nav aria-label="Main" className="w-52 border-r border-border bg-surface p-3">
          {nav.map(([href, label]) => (
            <Link key={href} href={href}
                  className={`block rounded-sm px-3 py-2 text-sm ${active(href)
                    ? "bg-surface-2 text-accent" : "text-text-dim hover:text-text"}`}>
              {label}
            </Link>
          ))}
        </nav>
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
