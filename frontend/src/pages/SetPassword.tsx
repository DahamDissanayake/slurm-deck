import { type FormEvent, useState } from "react";

import { setPassword } from "../api/auth";
import { ApiError } from "../api/client";
import { Link, navigate } from "../app/navigation";
import { Alert, button, Field, PublicPage } from "./PublicPage";

const LINK_ERRORS: Record<string, string> = {
  link_used: "This link has already been used. Ask for a new one.",
  link_expired: "This link has expired. Ask for a new one.",
  link_invalid: "This link isn't valid. Ask for a new one.",
};

/** The one-time token rides in the URL fragment, so it never reaches a server log. */
function tokenFromFragment(): string {
  return new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "";
}

/** Set a first password or reset one, from an emailed link; then signed in. */
export function SetPassword() {
  const [pw, setPw] = useState("");
  const [again, setAgain] = useState("");
  const [problems, setProblems] = useState<string[]>([]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (pw !== again) {
      setProblems(["The two passwords don't match."]);
      return;
    }
    try {
      await setPassword(tokenFromFragment(), pw);
      navigate("/");
    } catch (err) {
      const code = err instanceof ApiError ? err.code : "";
      setProblems(LINK_ERRORS[code] ? [LINK_ERRORS[code]]
        : err instanceof ApiError && err.message ? [err.message]
          : ["That didn't work. Try again."]);
    }
  }

  return (
    <PublicPage title="Choose your password">
      <form onSubmit={submit}>
        {problems.map((p) => <Alert key={p}>{p}</Alert>)}
        <Field label="New password" type="password" autoComplete="new-password" required
               minLength={12} value={pw} onChange={(e) => setPw(e.target.value)} />
        <Field label="Repeat it" type="password" autoComplete="new-password" required
               value={again} onChange={(e) => setAgain(e.target.value)} />
        <p className="mb-4 text-xs text-text-dim">
          At least 12 characters; not a common password; not your email or username.
        </p>
        <button type="submit" className={button}>Set password</button>
      </form>
      <Link href="/forgot-password" className="mt-4 block text-sm text-accent">
        Need a new link?
      </Link>
    </PublicPage>
  );
}
