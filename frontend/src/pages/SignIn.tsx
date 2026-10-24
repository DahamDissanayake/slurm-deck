import { type FormEvent, useEffect, useState } from "react";

import { applyOpen, signIn } from "../api/auth";
import { ApiError } from "../api/client";
import { Link, navigate } from "../app/navigation";
import { Alert, button, Field, PublicPage } from "./PublicPage";

function explain(e: unknown): string {
  if (!(e instanceof ApiError)) return "The cluster isn't answering. Try again in a moment.";
  if (e.code === "bad_credentials") return "That email and password don't match.";
  if (e.code === "locked") return "Too many failed sign-ins. Try again in a few minutes.";
  if (e.code === "rate_limited") return "Too many sign-in attempts from here. Try again later.";
  return e.message || "Sign-in failed.";
}

/** Only same-site paths are followed after sign-in. */
function nextPath(): string {
  const next = new URLSearchParams(window.location.search).get("next") ?? "/";
  return next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export function SignIn() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    applyOpen().then(setOpen).catch(() => setOpen(false));
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await signIn(email, password);
      navigate(nextPath());
    } catch (err) {
      setError(explain(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <PublicPage title="Sign in">
      <form onSubmit={submit}>
        {error && <Alert>{error}</Alert>}
        <Field label="Email" type="email" autoComplete="username" required value={email}
               onChange={(e) => setEmail(e.target.value)} />
        <Field label="Password" type="password" autoComplete="current-password" required
               value={password} onChange={(e) => setPassword(e.target.value)} />
        <button type="submit" className={button} disabled={busy}>Sign in</button>
      </form>
      <div className="mt-4 flex justify-between text-sm">
        <Link href="/forgot-password" className="text-accent">Forgot password</Link>
        {open && <Link href="/apply" className="text-accent">Apply for access</Link>}
      </div>
      <p className="mt-4 text-xs text-text-dim">
        First visit? <a href="/ca.crt" className="text-accent">Download the site certificate</a>
      </p>
    </PublicPage>
  );
}
