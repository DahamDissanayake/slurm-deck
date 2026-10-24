import type { Template } from "../../api/newjob";
import { field } from "./StepInputs";

const INTENTS = [
  ["notebook", "Notebook", "JupyterLab in the browser"],
  ["batch", "Script", "Train, fine-tune, run inference or anything else"],
  ["terminal", "Terminal session", "A shell on the GPU node"],
  ["smoke", "Smoke test", "A one-minute check that the GPU works; starts at once"],
] as const;

/** Step 1: what kind of job, or start from a saved template. */
export function StepIntent({ terminalEnabled, templates, onPick, onTemplate, busy }: {
  terminalEnabled: boolean; templates: Template[]; busy: boolean;
  onPick: (intent: string) => void; onTemplate: (t: Template) => void;
}) {
  const shown = INTENTS.filter(([id]) => id !== "terminal" || terminalEnabled);
  return (
    <div>
      <div className="grid gap-3 md:grid-cols-2">
        {shown.map(([id, title, hint]) => (
          <button key={id} type="button" disabled={busy} onClick={() => onPick(id)}
                  className="rounded-sm border border-border bg-surface-2 p-4 text-left hover:border-accent disabled:opacity-50">
            <span className="block font-semibold">{title}</span>
            <span className="text-sm text-text-dim">{hint}</span>
          </button>
        ))}
      </div>
      {templates.length > 0 && (
        <label className="mt-6 block text-sm text-text-dim">Start from a template
          <select className={field} value=""
                  onChange={(e) => {
                    const t = templates.find((x) => String(x.id) === e.target.value);
                    if (t) onTemplate(t);
                  }}>
            <option value="">Choose…</option>
            {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </label>
      )}
    </div>
  );
}
