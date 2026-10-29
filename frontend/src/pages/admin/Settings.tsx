import { useEffect, useState } from "react";

import { type SettingsReply, type SettingValues, adminOps } from "../../api/adminOps";
import { ApiError } from "../../api/client";
import { Card } from "../../components/ui/Card";
import { Button } from "../../components/ui/Button";
import { ErrorState } from "../../components/ui/ErrorState";
import { Skeleton } from "../../components/ui/Skeleton";
import { inputClass } from "./AdminLayout";

type Key = keyof SettingValues;
type Kind = "time" | "whole" | "text";
// key, label, kind, low, high (high 0 on the cap means "the partition's longest job")
const FIELDS: [Key, string, Kind, number, number][] = [
  ["default_time_limit", "Default job time (HH:MM:SS)", "time", 60, 0],
  ["extension_cap_hours", "Longest a job may be extended to (hours)", "whole", 1, 0],
  ["submit_rate_per_hour", "Jobs a person may submit per hour (0 = no limit)", "whole", 0, 10000],
  ["disk_alert_percent", "Email admins when the shared disk is this full (%)", "whole", 50, 99],
  ["cluster_location", "Where the cluster is", "text", 0, 100],
  ["maintenance_banner", "Message shown to everyone (empty for none)", "text", 0, 500],
];

/** The same rules as the server, so a mistake shows before Save. */
function problem([key, , kind, low, high]: (typeof FIELDS)[number], v: string, pmax: number | null) {
  if (kind === "text") return v.length <= high ? "" : `Use at most ${high} characters.`;
  if (kind === "time") {
    const m = /^(\d{1,3}):([0-5]\d):([0-5]\d)$/.exec(v);
    const secs = m ? +m[1] * 3600 + +m[2] * 60 + +m[3] : 0;
    return m && secs >= low && (!pmax || secs <= pmax) ? "" : "Use HH:MM:SS, up to the partition's longest job.";
  }
  const top = key === "extension_cap_hours" ? Math.floor((pmax ?? 720 * 3600) / 3600) : high;
  const n = Number(v);
  return v !== "" && Number.isInteger(n) && n >= low && n <= top ? "" : `Use a whole number from ${low} to ${top}.`;
}

const TOGGLES: [Key, string][] = [["mail_enabled", "Send email"], ["terminal_jobs_enabled", "Allow terminal sessions"]];
const GROUPS: [string, Key[]][] = [
  ["Jobs", ["default_time_limit", "extension_cap_hours", "submit_rate_per_hour", "terminal_jobs_enabled"]],
  ["Email and alerts", ["mail_enabled", "disk_alert_percent"]],
  ["Site", ["cluster_location", "maintenance_banner"]],
];

const show = (v: unknown) => (v == null ? "" : String(v));
/** The admin settings form: validated as you type, saved only when every value is good. */
export function Settings() {
  const [reply, setReply] = useState<SettingsReply | null>(null);
  const [form, setForm] = useState<Record<string, string | boolean>>({});
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  function load(r: SettingsReply) {
    setReply(r);
    setForm(Object.fromEntries(Object.entries(r.settings).map(([k, v]) => [k, typeof v === "boolean" ? v : show(v)])));
  }
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    setNote("");
    adminOps.settings().then(load, () => setNote("Couldn't load the settings."));
  }, [attempt]);
  if (!reply) {
    return (
      <Card title="Settings">
        {note ? <ErrorState title={note} onRetry={() => setAttempt((n) => n + 1)} />
          : <Skeleton variant="row" count={4} label="Loading settings" />}
      </Card>
    );
  }

  const errors = Object.fromEntries(FIELDS.map((f) => [f[0], problem(f, String(form[f[0]] ?? ""), reply.partition_max_s)]));
  const invalid = Object.values(errors).some(Boolean);

  async function save() {
    const changes: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(form)) {
      const old = reply!.settings[k as Key];
      if (v !== (typeof old === "boolean" ? old : show(old))) changes[k] = typeof old === "number" ? Number(v) : v;
    }
    setSaving(true);
    try {
      load(await adminOps.saveSettings(changes));
      setNote("Saved.");
    } catch (e) {
      setNote(e instanceof ApiError && e.message ? e.message : "That didn't save.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card title="Settings">
      <div className="grid max-w-xl gap-6 text-sm">
        {GROUPS.map(([legend, keys]) => (
          <fieldset key={legend} className="grid gap-4 rounded-lg border border-border p-4">
            <legend className="px-2 text-sm font-semibold text-text">{legend}</legend>
            {FIELDS.filter((f) => keys.includes(f[0])).map((f) => (
              <label key={f[0]} className="text-text-dim">{f[1]}
                <input className={`${inputClass} mt-1`} value={String(form[f[0]] ?? "")}
                       onChange={(e) => setForm({ ...form, [f[0]]: e.target.value })} />
                {errors[f[0]] && <span role="alert" className="mt-1 block text-danger">{errors[f[0]]}</span>}
              </label>
            ))}
            {TOGGLES.filter(([k]) => keys.includes(k)).map(([k, text]) => (
              <label key={k} className="flex items-center gap-2 text-text">
                <input type="checkbox" checked={form[k] === true} onChange={(e) => setForm({ ...form, [k]: e.target.checked })} />
                {text}
              </label>
            ))}
          </fieldset>
        ))}
        <div className="flex items-center gap-3">
          <Button disabled={invalid} loading={saving} onClick={save}>Save</Button>
          {note && <span role="status" className="text-text-dim">{note}</span>}
        </div>
      </div>
    </Card>
  );
}
