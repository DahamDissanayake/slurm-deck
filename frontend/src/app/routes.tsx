import type { ReactNode } from "react";

import { AdminLayout } from "../pages/admin/AdminLayout";
import { About } from "../pages/About";
import { Apply } from "../pages/Apply";
import { Environments } from "../pages/Environments";
import { Files } from "../pages/Files";
import { ForgotPassword } from "../pages/ForgotPassword";
import { Home } from "../pages/Home";
import { JobDetail } from "../pages/JobDetail";
import { Jobs } from "../pages/Jobs";
import { Models } from "../pages/Models";
import { NewJob } from "../pages/NewJob";
import { Notify } from "../pages/Notify";
import { Placeholder } from "../pages/Placeholder";
import { Services } from "../pages/Services";
import { SetPassword } from "../pages/SetPassword";
import { SignIn } from "../pages/SignIn";
import { Terminal } from "../pages/Terminal";
import { Usage } from "../pages/Usage";
import { AppShell } from "./AppShell";
import { match, Redirect, useLocation } from "./navigation";

const PUBLIC: [string, () => ReactNode][] = [
  ["/sign-in", () => <SignIn />],
  ["/apply", () => <Apply />],
  ["/set-password", () => <SetPassword />],
  ["/reset-password", () => <SetPassword />],
  ["/forgot-password", () => <ForgotPassword />],
  ["/about", () => <About />],
];

// Every signed-in page; later phases replace the placeholders.
const PAGES: [string, string][] = [
  ["/account/password", "Change password"],
];

export function App() {
  const { pathname } = useLocation();
  for (const [pattern, page] of PUBLIC) {
    if (match(pattern, pathname)) return page();
  }
  if (match("/admin", pathname) || match("/admin/*", pathname)) {
    return <AppShell><AdminLayout /></AppShell>;
  }
  if (pathname === "/new") return <AppShell><NewJob /></AppShell>;
  if (pathname === "/notify") return <AppShell><Notify /></AppShell>;
  if (pathname === "/models") return <AppShell><Models /></AppShell>;
  if (pathname === "/services") return <AppShell><Services /></AppShell>;
  if (pathname === "/usage") return <AppShell><Usage /></AppShell>;
  if (pathname === "/usage/hardware") return <Redirect to="/#hardware" />;
  if (pathname === "/usage/cluster") return <Redirect to="/#cluster" />;
  const terminal = match("/sessions/terminal/:jobId", pathname);
  if (terminal) return <Terminal jobId={terminal.jobId} />;
  if (pathname === "/envs") return <AppShell><Environments /></AppShell>;
  if (match("/files", pathname) || match("/files/*", pathname)) {
    return <AppShell><Files /></AppShell>;
  }
  const job = match("/jobs/:id", pathname);
  if (pathname === "/" || pathname === "/jobs" || job) {
    return (
      <AppShell>
        {job ? <JobDetail id={job.id} /> : pathname === "/" ? <Home /> : <Jobs />}
      </AppShell>
    );
  }
  const found = PAGES.find(([pattern]) => match(pattern, pathname));
  return (
    <AppShell>
      <Placeholder title={found ? found[1] : "Not found"} />
    </AppShell>
  );
}
