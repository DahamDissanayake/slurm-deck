import { type ReactNode, useEffect, useState } from "react";

import { type AgentEvent, type AuditRow, type MailRow, adminOps } from "../../api/adminOps";
import { Panel } from "../../components/Panel";
import { inputClass, smallButton } from "./AdminLayout";
import { ServiceUnits } from "./Cluster";

type Tab = "audit" | "agent" | "mail" | "services";
const TABS: [Tab, string][] = [["audit", "Audit"], ["agent", "deck-agent log"],
                               ["mail", "Mail log"], ["services", "Services"]];
const when = (iso: string) => new Date(iso).toLocaleString();

function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <table className="w-full text-left text-sm">
      <thead className="text-text-dim"><tr>{head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className="border-t border-border">{r.map((c, j) => <td key={j}>{c}</td>)}</tr>
        ))}
      </tbody>
    </table>
  );
}

function Pager({ page, more, go }: { page: number; more: boolean; go: (p: number) => void }) {
  return (
    <div className="mt-3 flex items-center gap-3 text-sm">
      <button type="button" className={smallButton} disabled={page <= 1} onClick={() => go(page - 1)}>Previous</button>
      <span>Page {page}</span>
      <button type="button" className={smallButton} disabled={!more} onClick={() => go(page + 1)}>Next</button>
    </div>
  );
}

function Audit() {
  const [f, setF] = useState({ actor: "", action: "", from: "", to: "" });
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [more, setMore] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    adminOps.audit({ ...f, page }).then((r) => { setRows(r.events); setMore(r.has_more); setError(""); },
      () => setError("Couldn't load the audit trail. Check the dates."));
  }, [f, page]);
  const filter = (key: keyof typeof f, label: string) => (
    <label className="text-sm">{label}
      <input className={`${inputClass} ml-2 w-36`} value={f[key]}
             onChange={(e) => { setPage(1); setF({ ...f, [key]: e.target.value }); }} />
    </label>
  );
  return (
    <>
      <div className="mb-3 flex flex-wrap gap-3">
        {filter("actor", "Who")}{filter("action", "Action starts with")}
        {filter("from", "From (YYYY-MM-DD)")}{filter("to", "To")}
      </div>
      {error && <p role="alert" className="text-danger">{error}</p>}
      <Table head={["When", "Who", "Action", "Target", "Result", "From"]} rows={rows.map((e) => [
        when(e.ts), `${e.actor ?? "system"}${e.acting_admin ? ` (via ${e.acting_admin})` : ""}`,
        <code key="a">{e.action}</code>, e.target, e.result, e.source])} />
      <Pager page={page} more={more} go={setPage} />
    </>
  );
}

function AgentLog() {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  useEffect(() => { adminOps.agentLog().then((r) => setEvents(r.events), () => setEvents([])); }, []);
  return <Table head={["When", "Who", "Verb", "Target", "Result"]} rows={events.map((e) => [
    when(e.ts), e.actor ?? "worker", e.verb, e.target, e.result])} />;
}

function MailLog() {
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState<MailRow[]>([]);
  const [more, setMore] = useState(false);
  useEffect(() => {
    adminOps.mail(status, page).then((r) => { setRows(r.mail); setMore(r.has_more); }, () => setRows([]));
  }, [status, page]);
  return (
    <>
      <label className="mb-3 block text-sm">Show
        <select className={`${inputClass} ml-2 w-40`} value={status}
                onChange={(e) => { setPage(1); setStatus(e.target.value); }}>
          {["", "sent", "pending", "failed", "disabled"].map((s) => <option key={s} value={s}>{s || "all"}</option>)}
        </select>
      </label>
      <Table head={["When", "To", "Subject", "Status", "Error"]} rows={rows.map((m) => [
        when(m.created_at), m.to, m.subject, m.status, m.status === "failed" ? m.error : ""])} />
      <Pager page={page} more={more} go={setPage} />
    </>
  );
}

/** Audit trail, deck-agent's own log, the mail log and service health. */
export function Monitoring() {
  const [tab, setTab] = useState<Tab>("audit");
  return (
    <Panel title="Monitoring">
      <div role="tablist" className="mb-4 flex gap-4 border-b border-border text-sm">
        {TABS.map(([t, label]) => (
          <button key={t} role="tab" type="button" aria-selected={tab === t} onClick={() => setTab(t)}
                  className={`-mb-px border-b-2 px-1 pb-2 ${tab === t
                    ? "border-accent text-accent" : "border-transparent text-text-dim"}`}>{label}</button>
        ))}
      </div>
      {tab === "audit" && <Audit />}{tab === "agent" && <AgentLog />}
      {tab === "mail" && <MailLog />}{tab === "services" && <ServiceUnits />}
    </Panel>
  );
}
