import { useEffect, useState } from "react";

import { type AccountRow, admin, day } from "../../api/admin";
import { Link } from "../../app/navigation";
import { Panel } from "../../components/Panel";
import { inputClass, primaryButton } from "./AdminLayout";

export function Users() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<AccountRow[]>([]);

  useEffect(() => {
    const t = setTimeout(() => admin.accounts(q).then(setRows).catch(() => {}), 200);
    return () => clearTimeout(t);
  }, [q]);

  return (
    <Panel title="Users">
      <div className="mb-4 flex gap-3">
        <input aria-label="Search" placeholder="Search email, username or name" value={q}
               onChange={(e) => setQ(e.target.value)} className={inputClass} />
        <Link href="/admin/users/new" className={`${primaryButton} whitespace-nowrap`}>New user</Link>
      </div>
      <table className="w-full text-left text-sm">
        <thead className="text-text-dim">
          <tr><th>Username</th><th>Name</th><th>Email</th><th>Role</th><th>Status</th>
            <th>Last sign-in</th></tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id} className="border-t border-border">
              <td className="py-2"><Link href={`/admin/users/${a.id}`} className="text-accent">
                {a.username}</Link></td>
              <td>{a.full_name}</td><td>{a.email}</td><td>{a.role}</td>
              <td className={a.status === "active" ? "text-ok" : "text-warning"}>{a.status}</td>
              <td>{day(a.last_login_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}
