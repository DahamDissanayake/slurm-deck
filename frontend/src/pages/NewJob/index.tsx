import { useEffect, useState } from "react";

import { ApiError } from "../../api/client";
import { type LaunchSpec, newjob, type Qos, type Template } from "../../api/newjob";
import { navigate } from "../../app/navigation";
import { Panel } from "../../components/Panel";
import { StepInputs } from "./StepInputs";
import { StepIntent } from "./StepIntent";
import { StepReview } from "./StepReview";

const TITLES = ["What do you want to run?", "Inputs", "Review and submit"];

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
    <Panel title={`New job · ${TITLES[step]}`}>
      {error && <p role="alert" className="mb-4 text-danger">{error}</p>}
      {step === 0 || !spec ? (
        <StepIntent terminalEnabled={terminal} templates={templates} busy={busy} onPick={pick}
                    onTemplate={(t) => { setSpec(t.spec); setStep(1); }} />
      ) : step === 1 ? (
        <StepInputs spec={spec} onChange={setSpec} onBack={() => setStep(0)}
                    onNext={() => setStep(2)} />
      ) : (
        <StepReview spec={spec} qos={qos} onChange={setSpec} onBack={() => setStep(1)} />
      )}
    </Panel>
  );
}
