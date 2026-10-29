import { type FormEvent, useState } from "react";

import { apply, type Application } from "../api/auth";
import { ApiError } from "../api/client";
import { Link } from "../app/navigation";
import { Alert, Field, PublicPage, SubmitButton } from "./PublicPage";

const EMPTY: Application = { email: "", full_name: "", role_title: "", organisation: "",
                             contact_number: "", reason: "", website: "" };

/** The Apply for access form (spec §5.4); the server's words are shown as they are. */
export function Apply() {
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const set = (key: keyof Application) => (e: { target: { value: string } }) =>
    setForm({ ...form, [key]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      setResult({ ok: true, text: (await apply(form)).message });
    } catch (err) {
      setResult({ ok: false, text: err instanceof ApiError && err.message
        ? err.message : "The application couldn't be sent. Try again later." });
    } finally {
      setBusy(false);
    }
  }

  if (result?.ok) {
    return (
      <PublicPage title="Apply for access">
        <Alert tone="ok">{result.text}</Alert>
        <Link href="/sign-in" className="text-accent">Back to sign-in</Link>
      </PublicPage>
    );
  }
  return (
    <PublicPage title="Apply for access">
      <form onSubmit={submit}>
        {result && <Alert>{result.text}</Alert>}
        <Field label="Email" type="email" required value={form.email} onChange={set("email")} />
        <Field label="Full name" required value={form.full_name} onChange={set("full_name")} />
        <Field label="Role or position" required placeholder="e.g. undergraduate, researcher"
               value={form.role_title} onChange={set("role_title")} />
        <Field label="Organisation (optional)" value={form.organisation}
               onChange={set("organisation")} />
        <Field label="Contact number" type="tel" required value={form.contact_number}
               onChange={set("contact_number")} />
        <Field label="Reason or project (optional)" value={form.reason} onChange={set("reason")} />
        {/* Honeypot: hidden from people, filled in by bots. */}
        <input type="text" name="website" tabIndex={-1} autoComplete="off" aria-hidden="true"
               className="hidden" value={form.website} onChange={set("website")} />
        <SubmitButton loading={busy}>Send application</SubmitButton>
      </form>
    </PublicPage>
  );
}
