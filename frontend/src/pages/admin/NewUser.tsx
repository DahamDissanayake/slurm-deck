import { type FormEvent, useState } from "react";

import { admin, day, gb, type Preview } from "../../api/admin";
import { ApiError } from "../../api/client";
import { navigate } from "../../app/navigation";
import { Panel } from "../../components/Panel";
import { Alert, Field } from "../PublicPage";
import { primaryButton } from "./AdminLayout";

type FolderChoice = "" | "reconnect" | "other";

/** Create an account. A leftover folder or an existing shell account must be
 * dealt with explicitly before Create is allowed. */
export function NewUser() {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [username, setUsername] = useState("");
  const [role, setRole] = useState<"user" | "admin">("user");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [folderChoice, setFolderChoice] = useState<FolderChoice>("");
  const [attach, setAttach] = useState(false);
  const [error, setError] = useState("");

  async function check(name = username) {
    if (!email) return;
    try {
      const p = await admin.preview(email, name);
      setPreview(p);
      if (!name) setUsername(p.suggested_username);
      setFolderChoice("");
      setAttach(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't check that email.");
    }
  }

  const folder = preview?.existing_folder ?? null;
  const ready = !!preview && preview.email_valid && preview.username_valid
    && !!username && !!fullName
    && (!folder || folderChoice !== "") && (folderChoice !== "other");

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      const made = await admin.create({ email, full_name: fullName, username, role,
                                        reconnect_folder: folderChoice === "reconnect",
                                        attach_shell: attach });
      navigate(`/admin/users/${made.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message || err.code : "Creating the account failed.");
    }
  }

  return (
    <Panel title="New user">
      <form onSubmit={submit} className="max-w-lg">
        {error && <Alert>{error}</Alert>}
        <Field label="Email" type="email" required value={email}
               onChange={(e) => setEmail(e.target.value)} onBlur={() => check()} />
        <Field label="Full name" required value={fullName}
               onChange={(e) => setFullName(e.target.value)} />
        <Field label="Username" required value={username}
               onChange={(e) => setUsername(e.target.value)} onBlur={() => check(username)} />
        {preview && !preview.username_valid && (
          <Alert>That username isn't available; choose another.</Alert>
        )}
        <label className="mb-4 block text-sm text-text-dim">
          Role{" "}
          <select value={role} onChange={(e) => setRole(e.target.value as "user" | "admin")}
                  className="ml-2 rounded-sm border border-border bg-surface-2 px-2 py-1 text-text">
            <option value="user">User</option>
            <option value="admin">Admin</option>
          </select>
        </label>
        {folder && (
          <fieldset className="mb-4 rounded-sm border border-warning p-3 text-sm">
            <legend className="px-1 text-warning">
              Existing folder found — {gb(folder.bytes)}, last changed {day(folder.mtime)},
              owned by UID {folder.owner_uid}.
            </legend>
            {(["reconnect", "other"] as const).map((choice) => (
              <label key={choice} className="block">
                <input type="radio" name="folder" checked={folderChoice === choice}
                       onChange={() => setFolderChoice(choice)} className="mr-2" />
                {choice === "reconnect" ? "This is the same person — reconnect"
                  : "Different person — choose another username"}
              </label>
            ))}
          </fieldset>
        )}
        {preview?.shell_account && !folder && (
          <label className="mb-4 block text-sm">
            <input type="checkbox" checked={attach} onChange={(e) => setAttach(e.target.checked)}
                   className="mr-2" />
            Existing shell account found (UID {preview.shell_account.uid}) — attach web account
          </label>
        )}
        <button type="submit" className={primaryButton} disabled={!ready}>Create account</button>
      </form>
    </Panel>
  );
}
