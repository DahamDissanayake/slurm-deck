import { useEffect, useState } from "react";

import { envs } from "../../api/envs";
import type { LaunchSpec } from "../../api/newjob";

export const field = "mt-1 mb-3 block w-full rounded-sm border border-border bg-surface-2 px-3 py-2 text-text";
export const primary = "rounded-sm bg-accent px-4 py-2 font-semibold text-bg disabled:opacity-50";
export const secondary =
  "rounded-sm border border-border px-4 py-2 text-text hover:border-accent disabled:opacity-50";

type Key = "script" | "conda_env" | "data_path" | "model_path" | "args" | "packages";

// Paths are typed for now (the file picker replaces them); the environment
// field suggests the ready environments from /api/envs.
const FIELDS: [Key, string, string][] = [
  ["script", "Script", "/shared/users/you/train.py"],
  ["conda_env", "Environment", "Conda environment name or path"],
  ["data_path", "Data path", "/shared/datasets/…"],
  ["model_path", "Model path or Hugging Face repo id", "meta-llama/Llama-3.1-8B"],
  ["args", "Arguments", "--epochs 3"],
  ["packages", "Packages to install first", "transformers==4.44 peft"],
];

/** Step 2: what to run and with what. Notebooks and terminals need no script. */
export function StepInputs({ spec, onChange, onBack, onNext }: {
  spec: LaunchSpec; onChange: (s: LaunchSpec) => void; onBack: () => void; onNext: () => void;
}) {
  const fields = spec.intent === "batch" ? FIELDS : FIELDS.filter(([k]) => k !== "script" && k !== "args");
  const [ready, setReady] = useState<string[]>([]);
  useEffect(() => {
    envs.list().then((l) => setReady([...l.prebuilt, ...l.mine].filter((e) => e.ready)
      .map((e) => e.path)), () => setReady([]));
  }, []);
  return (
    <div>
      <datalist id="sd-envs">{ready.map((p) => <option key={p} value={p} />)}</datalist>
      {fields.map(([key, label, hint]) => (
        <label key={key} className="block text-sm text-text-dim">{label}
          <input className={field} placeholder={hint} value={spec[key]}
                 list={key === "conda_env" ? "sd-envs" : undefined}
                 onChange={(e) => onChange({ ...spec, [key]: e.target.value })} />
        </label>
      ))}
      <div className="flex gap-2">
        <button type="button" className={secondary} onClick={onBack}>Back</button>
        <button type="button" className={primary} onClick={onNext}>Next</button>
      </div>
    </div>
  );
}
