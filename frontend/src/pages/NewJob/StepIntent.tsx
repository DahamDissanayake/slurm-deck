import type { ReactNode } from "react";

import type { Template } from "../../api/newjob";
import { BoltIcon, FileCodeIcon, ModelIcon, TerminalIcon } from "../../components/icons";
import { focusRing } from "../../components/ui/cx";
import { field } from "./StepInputs";

const INTENTS: [string, string, string, ReactNode][] = [
  ["notebook", "Notebook", "JupyterLab in the browser", <ModelIcon key="n" />],
  ["batch", "Script", "Train, fine-tune, run inference or anything else", <FileCodeIcon key="b" />],
  ["terminal", "Terminal session", "A shell on the GPU node", <TerminalIcon key="t" />],
  ["smoke", "Smoke test", "A one-minute check that the GPU works; starts at once", <BoltIcon key="s" />],
];

/** Step 1: what kind of job, or start from a saved template. */
export function StepIntent({ terminalEnabled, templates, onPick, onTemplate, busy }: {
  terminalEnabled: boolean; templates: Template[]; busy: boolean;
  onPick: (intent: string) => void; onTemplate: (t: Template) => void;
}) {
  const shown = INTENTS.filter(([id]) => id !== "terminal" || terminalEnabled);
  return (
    <div>
      <div className="grid gap-3 md:grid-cols-2">
        {shown.map(([id, title, hint, icon]) => (
          <button key={id} type="button" disabled={busy} onClick={() => onPick(id)}
                  className={`flex items-start gap-4 rounded-lg border border-border bg-surface p-4 text-left shadow-sm transition-colors duration-fast hover:border-accent hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50 ${focusRing}`}>
            <span aria-hidden="true"
                  className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent [&>svg]:h-5 [&>svg]:w-5">
              {icon}
            </span>
            <span>
              <span className="block text-base font-semibold text-text">{title}</span>
              <span className="text-sm text-text-dim">{hint}</span>
            </span>
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
