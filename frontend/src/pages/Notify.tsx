import { useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { newjob } from "../api/newjob";
import { Card } from "../components/ui/Card";
import { input } from "../components/controls";
import { BellIcon } from "../components/icons";
import { Button } from "../components/ui/Button";
import { Skeleton } from "../components/ui/Skeleton";
import { StatusBadge } from "../components/ui/StatusBadge";

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
    <Card title="Notify me">
      {wanted === undefined ? <Skeleton variant="row" count={1} label="Loading notification" /> : (
        <>
          <p className="mb-4 flex items-center gap-2">
            <StatusBadge state={wanted ? "active" : "inactive"} />
            {wanted ? `You'll get one email when ${wanted} pods are free.`
              : "You have no notification set."}
          </p>
          {error && <p role="alert" className="mb-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}
          <div className="flex items-end gap-2">
            <label className="text-sm text-text-dim">Pods wanted
              <input type="number" min={1} value={pods} className={`${input} w-24`}
                     onChange={(e) => setPods(Number(e.target.value))} />
            </label>
            <Button icon={<BellIcon />} onClick={() => run(() => newjob.setNotify(pods), pods)}>
              {wanted ? "Change" : "Notify me"}
            </Button>
            {wanted ? (
              <Button variant="secondary" onClick={() => run(() => newjob.stopNotify(), null)}>Stop</Button>
            ) : null}
          </div>
        </>
      )}
    </Card>
  );
}
