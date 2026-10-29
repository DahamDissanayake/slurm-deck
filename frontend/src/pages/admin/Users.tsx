import { useEffect, useState } from "react";

import { type AccountRow, admin, day } from "../../api/admin";
import { Link } from "../../app/navigation";
import { SearchIcon } from "../../components/icons";
import { EmptyState } from "../../components/ui/EmptyState";
import { Skeleton } from "../../components/ui/Skeleton";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { Card } from "../../components/ui/Card";
import { inputClass, primaryButton } from "./AdminLayout";

export function Users() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<AccountRow[] | null>(null);

  useEffect(() => {
    const t = setTimeout(() => admin.accounts(q).then(setRows).catch(() => {}), 200);
    return () => clearTimeout(t);
  }, [q]);

  return (
    <Card title="Users">
      <div className="mb-4 flex gap-3">
        <div className="relative flex-1">
          <span aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-dim [&>svg]:h-4 [&>svg]:w-4"><SearchIcon /></span>
          <input aria-label="Search" placeholder="Search email, username or name" value={q}
                 onChange={(e) => setQ(e.target.value)} className={`${inputClass} pl-9`} />
        </div>
        <Link href="/admin/users/new" className={`${primaryButton} whitespace-nowrap`}>New user</Link>
      </div>
      {rows === null ? <Skeleton variant="row" label="Loading users" />
        : rows.length === 0 ? <EmptyState icon={<SearchIcon />} title="No users match" /> : (
      <table className="w-full text-left text-sm [&_th]:py-2 [&_th]:font-medium [&_td]:py-2">
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
              <td><StatusBadge state={a.status === "active" ? "active" : "suspended"} /></td>
              <td>{day(a.last_login_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>)}
    </Card>
  );
}
