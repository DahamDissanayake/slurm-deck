import { useCallback, useEffect, useState } from "react";

import { admin, type ApplicationRow, day } from "../../api/admin";
import { ApiError } from "../../api/client";
import { Card } from "../../components/ui/Card";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { Alert, Field } from "../PublicPage";

/** Pending access applications: approve (creating the account) or reject with a note. */
export function Requests() {
  const [rows, setRows] = useState<ApplicationRow[]>([]);
  const [open, setOpen] = useState<{ app: ApplicationRow; mode: "approve" | "reject" } | null>(null);
  const load = useCallback(() => {
    admin.applications().then(setRows).catch(() => {});
  }, []);
  useEffect(load, [load]);

  return (
    <Card title="Requests">
      {rows.length === 0 && <EmptyState title="No applications are waiting" />}
      {rows.map((app) => (
        <div key={app.id} className="mb-4 border-b border-border pb-4 text-sm">
          <p className="font-semibold">{app.full_name} · {app.email}</p>
          <p className="text-text-dim">
            {app.role_title}{app.organisation ? ` at ${app.organisation}` : ""} · {app.contact_number}
            {" "}· applied {day(app.created_at)}
          </p>
          {app.reason && <p className="mt-1">{app.reason}</p>}
          <div className="mt-2 flex gap-2">
            <Button size="sm" variant="secondary"
                    onClick={() => setOpen({ app, mode: "approve" })}>Approve…</Button>
            <Button size="sm" variant="danger"
                    onClick={() => setOpen({ app, mode: "reject" })}>Reject…</Button>
          </div>
          {open?.app.id === app.id && (
            <Decide app={app} mode={open.mode} onClose={() => setOpen(null)}
                    onDone={() => { setOpen(null); load(); }} />
          )}
        </div>
      ))}
    </Card>
  );
}

function Decide({ app, mode, onClose, onDone }: {
  app: ApplicationRow; mode: "approve" | "reject"; onClose: () => void; onDone: () => void;
}) {
  const [username, setUsername] = useState("");
  const [role, setRole] = useState("user");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (mode === "approve") {
      admin.preview(app.email).then((p) => setUsername(p.suggested_username)).catch(() => {});
    }
  }, [app.email, mode]);

  async function go() {
    try {
      await (mode === "approve" ? admin.approve(app.id, username, role, false)
        : admin.reject(app.id, note));
      onDone();
    } catch (err) {
      setError(err instanceof ApiError && err.message ? err.message : "That didn't work.");
    }
  }

  return (
    <div role="dialog" aria-label={mode === "approve" ? "Approve" : "Reject"}
         className="mt-3 max-w-md rounded-lg border border-border bg-surface-2 p-4">
      {error && <Alert>{error}</Alert>}
      {mode === "approve" ? (
        <>
          <Field label="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
          <label className="mb-3 block text-sm text-text-dim">
            Role{" "}
            <select value={role} onChange={(e) => setRole(e.target.value)}
                    className="ml-2 h-8 rounded-md border border-border bg-surface px-2 text-text">
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </select>
          </label>
        </>
      ) : (
        <Field label="Note to the applicant (optional)" value={note}
               onChange={(e) => setNote(e.target.value)} />
      )}
      <div className="flex gap-2">
        <Button size="sm" disabled={mode === "approve" && !username}
                onClick={go}>{mode === "approve" ? "Approve and create" : "Reject"}</Button>
        <Button size="sm" variant="secondary" onClick={onClose}>Cancel</Button>
      </div>
    </div>
  );
}
