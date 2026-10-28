import { type ReactNode, useEffect, useState } from "react";

import pkg from "../../package.json";
import { getMe } from "../api/auth";
import { Link } from "../app/navigation";
import { ThemeToggle } from "../app/ThemeToggle";
import { Panel } from "../components/Panel";
import { Wordmark } from "../components/Wordmark";

const REPO = "https://github.com/DahamDissanayake/slurm-deck/";

const TIMELINE: [string, string][] = [
  ["May 2026", "The first build: an SSH terminal (TUI) app on Slurm."],
  ["v1.0 · 16 Jul 2026", "Baseline release."],
  ["v1.1 · 25 Jul 2026", "One access model for shared storage, notebook isolation and session audit."],
  ["v1.2 · 25 Jul 2026", "The launch flow redesigned."],
  ["v1.3 · 26 Jul 2026", "One design across the TUI."],
  ["v1.4 · 28 Jul 2026", "Renamed from IIT GPU Manager to Slurm Deck."],
  ["October 2026", "Work starts on the browser platform (v2.0), which replaces the SSH TUI. "
    + "It covers jobs, uploads, notebooks, environments, usage and admin, each shaped by what the researchers needed."],
];

const FEATURES = ["Jobs", "Files and uploads", "Environments", "Models", "Services and notebooks",
  "Usage", "Notifications", "Admin"];

function Ext({ href, children }: { href: string; children: ReactNode }) {
  return <a className="text-accent" href={href} target="_blank" rel="noreferrer">{children}</a>;
}

/** Public: works signed out, so it never goes through AppShell or the sign-in redirect. */
export function About() {
  const [signedIn, setSignedIn] = useState(false);
  useEffect(() => { getMe().then(() => setSignedIn(true), () => setSignedIn(false)); }, []);

  return (
    <div className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 p-6">
      <header className="flex items-center justify-between">
        <Wordmark className="text-2xl" />
        <div className="flex items-center gap-3 text-sm">
          {signedIn
            ? <Link href="/" className="text-accent">Back to dashboard</Link>
            : <Link href="/sign-in" className="text-accent">Sign in</Link>}
          <ThemeToggle />
        </div>
      </header>

      <Panel title="What Slurm Deck is">
        <p>
          An open-source platform for sharing GPU machines between researchers. People schedule
          jobs, manage files and datasets, and open notebook sessions from a browser. It is built
          to make everyday MLOps work on shared hardware easier.
        </p>
      </Panel>

      <Panel title="How it started">
        <p>
          It began at the IIT research unit, which had a single GPU machine and several researchers
          who all needed to run models on it. There was no fair way to share it or queue work. The
          project started as a way to manage that one machine&apos;s resources and schedule
          everyone&apos;s tasks with Slurm. It grew one requirement at a time into the version
          running today.
        </p>
      </Panel>

      <Panel title="How it grew">
        <ol className="space-y-3">
          {TIMELINE.map(([when, what]) => (
            <li key={when}><span className="font-mono text-accent">{when}</span><br />{what}</li>
          ))}
        </ol>
      </Panel>

      <Panel title="What it does today">
        <ul className="grid grid-cols-2 gap-1 sm:grid-cols-4">
          {FEATURES.map((f) => <li key={f}>{f}</li>)}
        </ul>
      </Panel>

      <Panel title="People">
        <ul className="space-y-1">
          <li>
            <span>Daham Dissanayake</span>, creator,{" "}
            <Ext href="https://github.com/DahamDissanayake">@DahamDissanayake</Ext>
          </li>
          <li>
            Supervisor, <Ext href="https://github.com/indrajithek">@indrajithek</Ext>
          </li>
        </ul>
      </Panel>

      <Panel title="Open source">
        <p>
          MIT licence. Source at <Ext href={REPO}>github.com/DahamDissanayake/slurm-deck</Ext>.
          Other sites can run it on their own hardware, and contributions go through the repo.
        </p>
      </Panel>

      <footer className="text-center text-xs text-text-dim">
        Slurm Deck · v{pkg.version} · MIT
      </footer>
    </div>
  );
}
