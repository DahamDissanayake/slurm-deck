import { type FormEvent, useCallback, useEffect, useState } from "react";

import { admin, type AllowEntry } from "../../api/admin";
import { ApiError } from "../../api/client";
import { Panel } from "../../components/Panel";
import { Alert } from "../PublicPage";
import { inputClass, smallButton } from "./AdminLayout";

/** The allow-list behind the Apply form. Empty means the form is off. */
export function AppAccess() {
  const [entries, setEntries] = useState<AllowEntry[]>([]);
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(() => {
    admin.allowlist().then(setEntries).catch(() => {});
  }, []);
  useEffect(load, [load]);

  async function add(e: FormEvent) {
    e.preventDefault();
    try {
      await admin.allow(value);
      setValue("");
      setError("");
      load();
    } catch (err) {
      setError(err instanceof ApiError && err.message ? err.message : "Couldn't add that.");
    }
  }

  return (
    <Panel title="Application access">
      <p className="mb-4 text-sm text-text-dim">
        {entries.length === 0
          ? "The list is empty, so the Apply for access form is switched off."
          : "People whose email matches an entry can apply. Domains match exactly, without subdomains."}
      </p>
      {error && <Alert>{error}</Alert>}
      <form onSubmit={add} className="mb-4 flex gap-2">
        <input aria-label="Domain or email" placeholder="example.org or person@example.org"
               value={value} onChange={(e) => setValue(e.target.value)} className={inputClass} />
        <button type="submit" className={smallButton} disabled={!value.trim()}>Add</button>
      </form>
      <ul className="text-sm">
        {entries.map((e) => (
          <li key={e.id} className="flex items-center justify-between border-t border-border py-2">
            <span>{e.value} <span className="text-text-dim">({e.kind})</span></span>
            <button type="button" className={smallButton}
                    onClick={() => admin.disallow(e.id).then(load)}>Remove</button>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
