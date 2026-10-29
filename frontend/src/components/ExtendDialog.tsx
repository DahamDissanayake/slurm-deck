import { useState } from "react";

import { ApiError } from "../api/client";
import { jobs } from "../api/jobs";
import { Button } from "./ui/Button";

/** Add 1, 2 or 4 hours to a running job. A refusal (such as going over the
 * cap) is shown exactly as the server words it. */
export function ExtendDialog({ jobId, onClose, onDone }: {
  jobId: string; onClose: () => void; onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function extend(hours: number) {
    setBusy(true);
    setError("");
    try {
      await jobs.extend(jobId, hours);
      onDone();
    } catch (err) {
      setError(err instanceof ApiError && err.message ? err.message : "Extending failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div role="dialog" aria-label={`Extend job ${jobId}`}
         className="mt-3 rounded-md border border-border bg-surface-2 p-4">
      <p className="mb-3 text-md text-text">Add time to job {jobId}:</p>
      {error && <p role="alert" className="mb-3 text-sm text-danger">{error}</p>}
      <div className="flex flex-wrap items-center gap-2">
        {[1, 2, 4].map((h) => (
          <Button key={h} variant="secondary" size="sm" pill disabled={busy} onClick={() => extend(h)}>
            +{h} h
          </Button>
        ))}
        <Button variant="ghost" size="sm" pill onClick={onClose} className="ml-auto">Close</Button>
      </div>
    </div>
  );
}
