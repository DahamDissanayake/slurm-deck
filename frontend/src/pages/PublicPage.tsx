import { type InputHTMLAttributes, type ReactNode, useId } from "react";
import { full, input } from "../components/controls";
import { AlertIcon, CheckIcon } from "../components/icons";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";

import pkg from "../../package.json";
import { Link } from "../app/navigation";
import { ThemeToggle } from "../app/ThemeToggle";
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
      <Card title={title} className="shadow-md">{children}</Card>
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
    <p role="alert" className={`mb-4 flex items-start gap-2 rounded-md px-3 py-2 text-sm ${tone === "ok"
      ? "bg-ok-soft text-ok" : "bg-danger-soft text-danger"}`}>
      <span aria-hidden="true" className="mt-0.5 inline-flex shrink-0 [&>svg]:h-4 [&>svg]:w-4">
        {tone === "ok" ? <CheckIcon /> : <AlertIcon />}
      </span>
      <span>{children}</span>
    </p>
  );
}

/** The full-width submit button; shows the spinner while the request runs. */
export function SubmitButton({ loading = false, children }: { loading?: boolean; children: ReactNode }) {
  return <Button type="submit" loading={loading} className="w-full">{children}</Button>;
}
