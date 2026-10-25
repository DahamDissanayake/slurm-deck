import { type ReactNode, useEffect, useState } from "react";

import { type AgentEvent, type AuditRow, type MailRow, adminOps } from "../../api/adminOps";
import { Panel } from "../../components/Panel";
import { inputClass, smallButton } from "./AdminLayout";
import { ServiceUnits } from "./Cluster";

type Tab = "audit" | "agent" | "mail" | "services";
const TABS: [Tab, string][] = [["audit", "Audit"], ["agent", "deck-agent log"],
                               ["mail", "Mail log"], ["services", "Services"]];
const when = (iso: string) => new Date(iso).toLocaleString();

/** Rows of cells under a header; with a pager when the list is paged on the server. */
function Table({ head, rows, pager }: { head: string[]; rows: ReactNode[][];
                                         pager?: [number, boolean, (p: number) => void] }) {
  return (
    <>
      <table className="w-full text-left text-sm">
        <thead className="text-text-dim"><tr>{head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-border">{r.map((c, j) => <td key={j}>{c}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {pager && (
        <div className="mt-3 flex items-center gap-3 text-sm">
          <button type="button" className={smallButton} disabled={pager[0] <= 1}
                  onClick={() => pager[2](pager[0] - 1)}>Previous</button>
          <span>Page {pager[0]}</span>
          <button type="button" className={smallButton} disabled={!pager[1]}
                  onClick={() => pager[2](pager[0] + 1)}>Next</button>
        </div>
      )}
    </>
  );
}

function Audit() {
  const [f, setF] = useState({ actor: "", action: "", from: "", to: "" });
  const [page, setPage] = useState(1);
  const [data, setData] = useState<{ events: AuditRow[]; has_more: boolean } | null>(null);
  useEffect(() => { adminOps.audit({ ...f, page }).then(setData, () => setData(null)); }, [f, page]);
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
      {!data && <p role="alert" className="text-danger">Couldn't load the audit trail. Check the dates.</p>}
      <Table head={["When", "Who", "Action", "Target", "Result", "From"]}
             pager={[page, !!data?.has_more, setPage]} rows={(data?.events ?? []).map((e) => [
               when(e.ts), `${e.actor ?? "system"}${e.acting_admin ? ` (via ${e.acting_admin})` : ""}`,
               <code key="a">{e.action}</code>, e.target, e.result, e.source])} />
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
  const [data, setData] = useState<{ mail: MailRow[]; has_more: boolean } | null>(null);
  useEffect(() => { adminOps.mail(status, page).then(setData, () => setData(null)); }, [status, page]);
  return (
    <>
      <label className="mb-3 block text-sm">Show
        <select className={`${inputClass} ml-2 w-40`} value={status}
                onChange={(e) => { setPage(1); setStatus(e.target.value); }}>
          {["", "sent", "pending", "failed", "disabled"].map((s) => <option key={s} value={s}>{s || "all"}</option>)}
        </select>
      </label>
      <Table head={["When", "To", "Subject", "Status", "Error"]} pager={[page, !!data?.has_more, setPage]}
             rows={(data?.mail ?? []).map((m) => [when(m.created_at), m.to, m.subject, m.status,
                                                  m.status === "failed" ? m.error : ""])} />
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
