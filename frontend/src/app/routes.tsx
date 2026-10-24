import type { ReactNode } from "react";

import { AdminLayout } from "../pages/admin/AdminLayout";
import { Apply } from "../pages/Apply";
import { ForgotPassword } from "../pages/ForgotPassword";
import { Placeholder } from "../pages/Placeholder";
import { SetPassword } from "../pages/SetPassword";
import { SignIn } from "../pages/SignIn";
import { AppShell } from "./AppShell";
import { match, useLocation } from "./navigation";

const PUBLIC: [string, () => ReactNode][] = [
  ["/sign-in", () => <SignIn />],
  ["/apply", () => <Apply />],
  ["/set-password", () => <SetPassword />],
  ["/reset-password", () => <SetPassword />],
  ["/forgot-password", () => <ForgotPassword />],
];

// Every signed-in page; later phases replace the placeholders.
const PAGES: [string, string][] = [
  ["/", "Dashboard"], ["/new", "New job"], ["/jobs", "Jobs"], ["/jobs/:id", "Job"],
  ["/files/*", "Files"], ["/files", "Files"], ["/envs", "Environments"], ["/models", "Models"],
  ["/services", "Services"], ["/usage", "Usage"], ["/notify", "Notify"],
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
  const found = PAGES.find(([pattern]) => match(pattern, pathname));
  return (
    <AppShell>
      <Placeholder title={found ? found[1] : "Not found"} />
    </AppShell>
  );
}
