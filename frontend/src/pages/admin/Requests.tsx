import { useCallback, useEffect, useState } from "react";

import { admin, type ApplicationRow, day } from "../../api/admin";
import { ApiError } from "../../api/client";
import { Panel } from "../../components/Panel";
import { Alert, Field } from "../PublicPage";
import { smallButton } from "./AdminLayout";

/** Pending access applications: approve (creating the account) or reject with a note. */
export function Requests() {
  const [rows, setRows] = useState<ApplicationRow[]>([]);
  const [open, setOpen] = useState<{ app: ApplicationRow; mode: "approve" | "reject" } | null>(null);
  const load = useCallback(() => {
    admin.applications().then(setRows).catch(() => {});
  }, []);
  useEffect(load, [load]);

  return (
    <Panel title="Requests">
      {rows.length === 0 && <p className="text-text-dim">No applications are waiting.</p>}
      {rows.map((app) => (
        <div key={app.id} className="mb-4 border-b border-border pb-4 text-sm">
          <p className="font-semibold">{app.full_name} · {app.email}</p>
          <p className="text-text-dim">
            {app.role_title}{app.organisation ? ` at ${app.organisation}` : ""} · {app.contact_number}
            {" "}· applied {day(app.created_at)}
          </p>
          {app.reason && <p className="mt-1">{app.reason}</p>}
          <div className="mt-2 flex gap-2">
            <button type="button" className={smallButton}
                    onClick={() => setOpen({ app, mode: "approve" })}>Approve…</button>
            <button type="button" className={smallButton}
                    onClick={() => setOpen({ app, mode: "reject" })}>Reject…</button>
          </div>
          {open?.app.id === app.id && (
            <Decide app={app} mode={open.mode} onClose={() => setOpen(null)}
                    onDone={() => { setOpen(null); load(); }} />
          )}
        </div>
      ))}
    </Panel>
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
         className="mt-3 max-w-md rounded-sm border border-border p-3">
      {error && <Alert>{error}</Alert>}
      {mode === "approve" ? (
        <>
          <Field label="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
          <label className="mb-3 block text-sm text-text-dim">
            Role{" "}
            <select value={role} onChange={(e) => setRole(e.target.value)}
                    className="ml-2 rounded-sm border border-border bg-surface-2 px-2 py-1 text-text">
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
        <button type="button" className={smallButton} disabled={mode === "approve" && !username}
                onClick={go}>{mode === "approve" ? "Approve and create" : "Reject"}</button>
        <button type="button" className={smallButton} onClick={onClose}>Cancel</button>
      </div>
    </div>
  );
}
