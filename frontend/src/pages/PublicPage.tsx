import { type InputHTMLAttributes, type ReactNode, useId } from "react";
import { full, input, primary } from "../components/controls";

import pkg from "../../package.json";
import { Link } from "../app/navigation";
import { ThemeToggle } from "../app/ThemeToggle";
import { Panel } from "../components/Panel";
import { Wordmark } from "../components/Wordmark";

const SOURCE = "https://github.com/DahamDissanayake/slurm-deck";

/** The signed-out frame: wordmark, tagline, one double-ruled panel, footer. */
export function PublicPage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 p-6">
      <div className="flex items-start justify-between">
        <div>
          <Wordmark className="text-3xl" />
          <p className="mt-2 text-text-dim">Run your GPU work on the cluster from your browser.</p>
        </div>
        <ThemeToggle />
      </div>
      <Panel title={title}>{children}</Panel>
      <footer className="text-center text-xs text-text-dim">
        Slurm Deck · v{pkg.version} · MIT ·{" "}
        <Link href="/about" className="text-accent">About</Link> ·{" "}
        <a className="text-accent" href={SOURCE}>source</a>
      </footer>
    </div>
  );
}

/** A labelled input; the label is what screen readers and tests find it by. */
export function Field({ label, ...rest }: InputHTMLAttributes<HTMLInputElement> & {
  label: string;
}) {
  const id = useId();
  return (
    <div className="mb-4">
      <label htmlFor={id} className="mb-1 block text-sm text-text-dim">{label}</label>
      <input id={id} {...rest} className={`${input} ${full}`} />
    </div>
  );
}

export function Alert({ children, tone = "danger" }: { children: ReactNode; tone?: "danger" | "ok" }) {
  return (
    <p role="alert" className={`mb-4 text-sm ${tone === "ok" ? "text-ok" : "text-danger"}`}>
      {children}
    </p>
  );
}

export const button = `${primary} ${full}`;
