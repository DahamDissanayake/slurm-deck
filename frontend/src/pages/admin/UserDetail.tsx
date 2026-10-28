import { useCallback, useEffect, useState } from "react";

import { type AccountRow, admin, day } from "../../api/admin";
import { ApiError } from "../../api/client";
import { navigate } from "../../app/navigation";
import { Panel } from "../../components/Panel";
import { Alert, Field } from "../PublicPage";
import { smallDanger } from "../../components/controls";
import { smallButton } from "./AdminLayout";

/** One account: its details and the admin actions on it. */
export function UserDetail({ id }: { id: number }) {
  const [a, setA] = useState<AccountRow | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(() => {
    admin.accounts().then((rows) => setA(rows.find((r) => r.id === id) ?? null)).catch(() => {});
  }, [id]);
  useEffect(load, [load]);

  async function act(fn: () => Promise<unknown>, done: string) {
    try {
      await fn();
      setMessage({ ok: true, text: done });
      load();
    } catch (err) {
      setMessage({ ok: false, text: err instanceof ApiError && err.message ? err.message
        : "That didn't work." });
    }
  }

  if (!a) return <Panel title="User"><p className="text-text-dim">Loading…</p></Panel>;
  const viewable = a.status === "active" && a.role === "user" && a.linux_kind === "hidden";
  return (
    <Panel title={a.username}>
      {message && <Alert tone={message.ok ? "ok" : "danger"}>{message.text}</Alert>}
      <dl className="mb-6 grid grid-cols-[10rem_1fr] gap-y-1 text-sm">
        <dt className="text-text-dim">Name</dt><dd>{a.full_name}</dd>
        <dt className="text-text-dim">Email</dt><dd>{a.email}</dd>
        <dt className="text-text-dim">Role</dt><dd>{a.role}</dd>
        <dt className="text-text-dim">Status</dt><dd>{a.status}</dd>
        <dt className="text-text-dim">Linux account</dt><dd>{a.linux_kind}, UID {a.uid ?? "?"}</dd>
        <dt className="text-text-dim">Last sign-in</dt><dd>{day(a.last_login_at)}</dd>
      </dl>
      <div className="flex flex-wrap gap-2">
        {a.status === "active"
          ? <button type="button" className={smallButton}
                    onClick={() => act(() => admin.disable(a.id), "Disabled; their sessions ended.")}>
              Disable</button>
          : <button type="button" className={smallButton}
                    onClick={() => act(() => admin.enable(a.id), "Enabled.")}>Enable</button>}
        <button type="button" className={smallButton}
                onClick={() => act(() => admin.resetPassword(a.id), "Reset link sent.")}>
          Send reset link</button>
        {viewable && (
          <button type="button" className={smallButton}
                  onClick={() => admin.viewAs(a.id).then(() => navigate("/"))}>View as user</button>
        )}
        <button type="button" className={`${smallDanger}`}
                onClick={() => setDeleting(true)}>Delete…</button>
      </div>
      {deleting && <DeleteDialog account={a} onCancel={() => setDeleting(false)}
                                 onDone={() => navigate("/admin/users")} />}
    </Panel>
  );
}

function DeleteDialog({ account, onCancel, onDone }: {
  account: AccountRow; onCancel: () => void; onDone: () => void;
}) {
  const [purge, setPurge] = useState(false);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState("");
  const allowed = !purge || typed === account.username;

  async function remove() {
    try {
      await admin.remove(account.id, purge, typed);
      onDone();
    } catch (err) {
      setError(err instanceof ApiError && err.message ? err.message : "Deleting failed.");
    }
  }

  return (
    <div role="dialog" aria-label="Delete account" className="mt-6 rounded-sm border border-danger p-4">
      {error && <Alert>{error}</Alert>}
      <p className="mb-3 text-sm">
        Deleting {account.username} cancels their jobs and removes their accounts. Their folder is
        kept as <code>{account.username}.offboarded</code> unless you purge it.
      </p>
      <label className="mb-3 block text-sm">
        <input type="checkbox" checked={purge} onChange={(e) => setPurge(e.target.checked)}
               className="mr-2" />
        Also delete their files (purge)
      </label>
      {purge && <Field label={`Type ${account.username} to confirm`} value={typed}
                       onChange={(e) => setTyped(e.target.value)} />}
      <div className="flex gap-2">
        <button type="button" className={`${smallDanger}`} disabled={!allowed}
                onClick={remove}>
          {purge ? "Delete account and files" : "Delete account, keep files"}
        </button>
        <button type="button" className={smallButton} onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
