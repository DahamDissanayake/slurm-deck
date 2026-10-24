import { useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { newjob } from "../api/newjob";
import { Panel } from "../components/Panel";
import { field, primary, secondary } from "./NewJob/StepInputs";

/** "Email me when N pods are free": one subscription per account, sent once. */
export function Notify() {
  const [wanted, setWanted] = useState<number | null | undefined>(undefined);
  const [pods, setPods] = useState(1);
  const [error, setError] = useState("");

  useEffect(() => { newjob.notify().then((r) => setWanted(r.wanted_pods), () => setWanted(null)); }, []);

  async function run(action: () => Promise<unknown>, next: number | null) {
    setError("");
    try {
      await action();
      setWanted(next);
    } catch (err) {
      setError(err instanceof ApiError && err.message ? err.message : "That didn't work.");
    }
  }

  return (
    <Panel title="Notify me">
      {wanted === undefined ? <p className="text-text-dim">Loading…</p> : (
        <>
          <p className="mb-4">
            {wanted ? `You'll get one email when ${wanted} pods are free.`
              : "You have no notification set."}
          </p>
          {error && <p role="alert" className="mb-3 text-danger">{error}</p>}
          <div className="flex items-end gap-2">
            <label className="text-sm text-text-dim">Pods wanted
              <input type="number" min={1} value={pods} className={`${field} mb-0 w-24`}
                     onChange={(e) => setPods(Number(e.target.value))} />
            </label>
            <button type="button" className={primary}
                    onClick={() => run(() => newjob.setNotify(pods), pods)}>
              {wanted ? "Change" : "Notify me"}
            </button>
            {wanted ? (
              <button type="button" className={secondary}
                      onClick={() => run(() => newjob.stopNotify(), null)}>Stop</button>
            ) : null}
          </div>
        </>
      )}
    </Panel>
  );
}
