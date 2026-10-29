import { useEffect, useState } from "react";

import { ApiError } from "../../api/client";
import { type LaunchSpec, newjob, type Qos, type Template } from "../../api/newjob";
import { navigate } from "../../app/navigation";
import { Card } from "../../components/ui/Card";
import { cx } from "../../components/ui/cx";
import { StepInputs } from "./StepInputs";
import { StepIntent } from "./StepIntent";
import { StepReview } from "./StepReview";

const TITLES = ["What do you want to run?", "Inputs", "Review and submit"];
const STEPS = ["Intent", "Inputs", "Review"];

/** Where you are in the three steps. */
function Stepper({ step }: { step: number }) {
  return (
    <ol aria-label="Progress" className="mb-5 flex items-center gap-2 text-sm">
      {STEPS.map((label, i) => (
        <li key={label} aria-current={i === step ? "step" : undefined}
            className={cx("flex items-center gap-2", i === step ? "font-semibold text-text" : "text-text-dim")}>
          <span aria-hidden="true" className={cx("inline-flex h-6 w-6 items-center justify-center rounded-full text-xs",
            i < step ? "bg-ok-soft text-ok" : i === step ? "bg-accent text-accent-fg" : "bg-neutral-soft")}>
            {i < step ? "✓" : i + 1}
          </span>
          {label}
          {i < STEPS.length - 1 && <span aria-hidden="true" className="h-px w-8 bg-border" />}
        </li>
      ))}
    </ol>
  );
}

/** New job in three steps. ?rerun=<job id> starts from that job's settings. */
export function NewJob() {
  const [step, setStep] = useState(0);
  const [spec, setSpec] = useState<LaunchSpec | null>(null);
  const [qos, setQos] = useState<Qos>({ max_wall_s: null, max_pods_per_user: null });
  const [terminal, setTerminal] = useState(false);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const fail = (err: unknown) =>
    setError(err instanceof ApiError && err.message ? err.message : "Something went wrong.");

  useEffect(() => {
    newjob.defaults("batch").then((d) => { setQos(d.qos); setTerminal(d.terminal_enabled); }, fail);
    newjob.templates().then(setTemplates, () => setTemplates([]));
    const rerun = new URLSearchParams(window.location.search).get("rerun");
    if (rerun) newjob.rerun(rerun).then((r) => { setSpec(r.spec); setStep(1); }, fail);
  }, []);

  async function pick(intent: string) {
    setBusy(true);
    setError("");
    try {
      const d = await newjob.defaults(intent);
      setQos(d.qos);
      if (intent === "smoke") {   // one click: the smoke test needs no choices
        const { job_id } = await newjob.submit(d.spec);
        navigate(`/jobs/${job_id}`);
        return;
      }
      setSpec(d.spec);
      setStep(1);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title={`New job · ${TITLES[step]}`}>
      <Stepper step={step} />
      {error && <p role="alert" className="mb-4 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}
      {step === 0 || !spec ? (
        <StepIntent terminalEnabled={terminal} templates={templates} busy={busy} onPick={pick}
                    onTemplate={(t) => { setSpec(t.spec); setStep(1); }} />
      ) : step === 1 ? (
        <StepInputs spec={spec} onChange={setSpec} onBack={() => setStep(0)}
                    onNext={() => setStep(2)} />
      ) : (
        <StepReview spec={spec} qos={qos} onChange={setSpec} onBack={() => setStep(1)} />
      )}
    </Card>
  );
}
