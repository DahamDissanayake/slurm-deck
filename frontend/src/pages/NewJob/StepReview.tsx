import { useEffect, useState } from "react";

import { ApiError } from "../../api/client";
import { type ClusterStatus, type LaunchSpec, newjob, type Qos, qosProblems } from "../../api/newjob";
import { navigate } from "../../app/navigation";
import { PodStepper } from "../../components/PodStepper";
import { ScriptPreview } from "../../components/ScriptPreview";
import { field, primary, secondary } from "./StepInputs";

const gb = (mb: number) => (mb / 1024).toFixed(1);

/** Step 3: size, time and options; the live problems list; Submit. */
export function StepReview({ spec, qos, onChange, onBack }: {
  spec: LaunchSpec; qos: Qos; onChange: (s: LaunchSpec) => void; onBack: () => void;
}) {
  const [status, setStatus] = useState<ClusterStatus | null>(null);
  const [script, setScript] = useState("");
  const [serverProblems, setServerProblems] = useState<string[]>([]);
  const [showScript, setShowScript] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { newjob.status().then(setStatus, () => setStatus(null)); }, []);

  useEffect(() => {   // re-check the spec on the server a moment after each change
    let stale = false;
    const t = setTimeout(() => {
      newjob.preview(spec).then(
        (r) => { if (!stale) { setScript(r.script); setServerProblems(r.problems); } },
        (err) => { if (!stale) setServerProblems([err instanceof ApiError && err.message
                                                   ? err.message : "Couldn't check this job."]); });
    }, 250);
    return () => { stale = true; clearTimeout(t); };
  }, [spec]);

  const problems = [...new Set([...qosProblems(spec, qos), ...serverProblems])];
  const total = status?.pods_total ?? null;
  const free = total == null ? null : total - (status?.pods_used ?? 0);
  const node = status?.node;
  const max = qos.max_pods_per_user ?? total ?? 8;

  function setPods(k: number) {
    const per = (n: number) => n / Math.max(spec.gpu_shards, 1);
    onChange({ ...spec, gpu_shards: k, cpus: Math.round(per(spec.cpus) * k),
               mem_gb: Math.round(per(spec.mem_gb) * k) });
  }

  async function submit() {
    setBusy(true);
    setNote("");
    try {
      const { job_id } = await newjob.submit(spec);
      navigate(`/jobs/${job_id}`);
    } catch (err) {
      setNote(err instanceof ApiError && err.message ? err.message : "Submitting failed.");
      setBusy(false);
    }
  }

  async function saveTemplate() {
    try {
      await newjob.saveTemplate(templateName, spec);
      setNote(`Saved as template "${templateName}".`);
    } catch (err) {
      setNote(err instanceof ApiError && err.message ? err.message : "Saving failed.");
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h3 className="mb-2 text-sm text-text-dim">Pods</h3>
        <PodStepper value={spec.gpu_shards} max={max} free={free} total={total} onChange={setPods} />
        {node && node.shard_total > 0 && (
          <p className="mt-2 text-sm text-text-dim">
            Pods share one GPU's memory; your share is about{" "}
            {gb((node.gpu_mem_total_mb / node.shard_total) * spec.gpu_shards)} GB.
          </p>
        )}
        {node?.live_stats && (
          <p className="text-sm text-text-dim">
            GPU memory free right now: {gb(node.gpu_mem_total_mb - node.gpu_mem_used_mb)} GB of{" "}
            {gb(node.gpu_mem_total_mb)} GB
          </p>
        )}
        <p className="mt-2 text-sm">{spec.cpus} CPUs · {spec.mem_gb} GB RAM</p>
      </div>
      <label className="block text-sm text-text-dim">Time limit (HH:MM:SS)
        <input className={field} value={spec.time_limit}
               onChange={(e) => onChange({ ...spec, time_limit: e.target.value })} />
      </label>
      <label className="block text-sm">
        <input type="checkbox" className="mr-2" checked={spec.mail}
               onChange={(e) => onChange({ ...spec, mail: e.target.checked })} />
        Email me when the job starts and ends
      </label>
      <details className="text-sm">
        <summary className="cursor-pointer text-text-dim">Advanced</summary>
        <label className="mt-2 block text-text-dim">Array (e.g. 0-9)
          <input className={field} value={spec.array}
                 onChange={(e) => onChange({ ...spec, array: e.target.value })} />
        </label>
        <label className="block text-text-dim">Run after job (dependency, e.g. afterok:512)
          <input className={field} value={spec.dependency}
                 onChange={(e) => onChange({ ...spec, dependency: e.target.value })} />
        </label>
      </details>
      <div className="flex gap-2">
        <input aria-label="Template name" placeholder="Template name" value={templateName}
               onChange={(e) => setTemplateName(e.target.value)} className={`${field} mb-0 mt-0`} />
        <button type="button" className={secondary} disabled={!templateName.trim()}
                onClick={saveTemplate}>Save as template</button>
      </div>
      <button type="button" className="text-sm text-accent" onClick={() => setShowScript(!showScript)}>
        {showScript ? "Hide script" : "Preview script"}
      </button>
      {showScript && <ScriptPreview script={script} />}
      {problems.length > 0 && (
        <ul aria-label="Problems" className="list-disc rounded-sm border border-danger p-3 pl-8 text-sm text-danger">
          {problems.map((p) => <li key={p}>{p}</li>)}
        </ul>
      )}
      {note && <p role="status" className="text-sm">{note}</p>}
      <div className="flex gap-2">
        <button type="button" className={secondary} onClick={onBack}>Back</button>
        <button type="button" className={primary} disabled={busy || problems.length > 0}
                onClick={submit}>Submit job</button>
      </div>
    </div>
  );
}
