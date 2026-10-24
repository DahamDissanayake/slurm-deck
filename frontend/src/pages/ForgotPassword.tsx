import { type FormEvent, useState } from "react";

import { forgotPassword } from "../api/auth";
import { Link } from "../app/navigation";
import { Alert, button, Field, PublicPage } from "./PublicPage";

/** Ask for a reset link. The reply is the same whether or not the account exists. */
export function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    await forgotPassword(email).catch(() => {});
    setSent(true);
  }

  return (
    <PublicPage title="Reset your password">
      {sent ? (
        <Alert tone="ok">If that email has an account, a reset link is on its way.</Alert>
      ) : (
        <form onSubmit={submit}>
          <Field label="Email" type="email" required value={email}
                 onChange={(e) => setEmail(e.target.value)} />
          <button type="submit" className={button}>Send reset link</button>
        </form>
      )}
      <Link href="/sign-in" className="mt-4 block text-sm text-accent">Back to sign-in</Link>
    </PublicPage>
  );
}
