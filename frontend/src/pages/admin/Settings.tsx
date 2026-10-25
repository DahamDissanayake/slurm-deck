import { useEffect, useState } from "react";

import { type SettingsReply, type SettingValues, adminOps } from "../../api/adminOps";
import { ApiError } from "../../api/client";
import { Panel } from "../../components/Panel";
import { inputClass, primaryButton } from "./AdminLayout";

type Key = keyof SettingValues;
const TIME = /^(\d{1,3}):([0-5]\d):([0-5]\d)$/;

/** The same rules as the server, so a mistake shows before Save. */
function problem(key: Key, v: string, pmax: number | null): string {
  const n = Number(v);
  switch (key) {
    case "default_time_limit": {
      const m = TIME.exec(v);
      if (!m) return "Use HH:MM:SS, like 08:00:00.";
      const secs = +m[1] * 3600 + +m[2] * 60 + +m[3];
      return secs < 60 || (pmax && secs > pmax) ? "That is outside what the partition allows." : "";
    }
    case "extension_cap_hours": {
      const top = pmax ? Math.floor(pmax / 3600) : 720;
      return Number.isInteger(n) && n >= 1 && n <= top ? "" : `Use a whole number from 1 to ${top}.`;
    }
    case "submit_rate_per_hour":
      return Number.isInteger(n) && n >= 0 && n <= 10000 ? "" : "Use a whole number from 0 to 10000.";
    case "disk_alert_percent":
      return Number.isInteger(n) && n >= 50 && n <= 99 ? "" : "Use a whole number from 50 to 99.";
    case "maintenance_banner":
      return v.length <= 500 ? "" : "Use at most 500 characters.";
    case "cluster_location":
      return v.length <= 100 ? "" : "Use at most 100 characters.";
    default:
      return "";
  }
}

const LABELS: [Key, string, string][] = [
  ["default_time_limit", "Default job time (HH:MM:SS)", "text"],
  ["extension_cap_hours", "Longest a job may be extended to (hours)", "number"],
  ["submit_rate_per_hour", "Jobs a person may submit per hour (0 = no limit)", "number"],
  ["disk_alert_percent", "Email admins when the shared disk is this full (%)", "number"],
  ["cluster_location", "Where the cluster is", "text"],
];

const show = (v: unknown) => (v == null ? "" : String(v));

/** The admin settings form: validated as you type, saved only when every value is good. */
export function Settings() {
  const [reply, setReply] = useState<SettingsReply | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [flags, setFlags] = useState<Pick<SettingValues, "mail_enabled" | "terminal_jobs_enabled">>(
    { mail_enabled: true, terminal_jobs_enabled: true });
  const [note, setNote] = useState("");

  function load(r: SettingsReply) {
    setReply(r);
    setForm(Object.fromEntries(Object.entries(r.settings).map(([k, v]) => [k, show(v)])));
    setFlags({ mail_enabled: r.settings.mail_enabled, terminal_jobs_enabled: r.settings.terminal_jobs_enabled });
  }
  useEffect(() => { adminOps.settings().then(load, () => setNote("Couldn't load the settings.")); }, []);
  if (!reply) return <Panel title="Settings"><p className="text-text-dim">{note || "Loading…"}</p></Panel>;

  const pmax = reply.partition_max_s;
  const errors = Object.fromEntries((Object.keys(reply.settings) as Key[])
    .filter((k) => typeof reply.settings[k] !== "boolean")
    .map((k) => [k, problem(k, form[k] ?? "", pmax)]));
  const invalid = Object.values(errors).some(Boolean);

  async function save() {
    const changes: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(form)) {
      if (typeof reply!.settings[k as Key] === "boolean" || v === show(reply!.settings[k as Key])) continue;
      const numeric = typeof reply!.settings[k as Key] === "number";
      changes[k] = numeric ? Number(v) : v;
    }
    for (const [k, v] of Object.entries(flags)) if (v !== reply!.settings[k as Key]) changes[k] = v;
    try {
      load(await adminOps.saveSettings(changes));
      setNote("Saved.");
    } catch (e) {
      setNote(e instanceof ApiError && e.message ? e.message : "That didn't save.");
    }
  }

  return (
    <Panel title="Settings">
      <div className="grid max-w-xl gap-4 text-sm">
        {LABELS.map(([key, label, type]) => (
          <label key={key}>{label}
            <input className={inputClass} type={type} value={form[key] ?? ""}
                   onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
            {errors[key] && <span role="alert" className="text-danger">{errors[key]}</span>}
          </label>
        ))}
        <label>Message shown to everyone (leave empty for none)
          <textarea className={inputClass} rows={2} value={form.maintenance_banner ?? ""}
                    onChange={(e) => setForm({ ...form, maintenance_banner: e.target.value })} />
          {errors.maintenance_banner && <span role="alert" className="text-danger">{errors.maintenance_banner}</span>}
        </label>
        {(["mail_enabled", "terminal_jobs_enabled"] as const).map((k) => (
          <label key={k}>
            <input type="checkbox" checked={flags[k]} onChange={(e) => setFlags({ ...flags, [k]: e.target.checked })} />
            {" "}{k === "mail_enabled" ? "Send email" : "Allow terminal sessions"}
          </label>
        ))}
        <div className="flex items-center gap-3">
          <button type="button" className={primaryButton} disabled={invalid} onClick={save}>Save</button>
          {note && <span role="status">{note}</span>}
        </div>
      </div>
    </Panel>
  );
}
