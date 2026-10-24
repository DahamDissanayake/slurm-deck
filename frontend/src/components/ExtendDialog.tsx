import { useState } from "react";

import { ApiError } from "../api/client";
import { jobs } from "../api/jobs";

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
         className="mt-3 rounded-sm border border-border bg-surface-2 p-4">
      <p className="mb-3 text-sm">Add time to job {jobId}:</p>
      {error && <p role="alert" className="mb-3 text-sm text-danger">{error}</p>}
      <div className="flex gap-2">
        {[1, 2, 4].map((h) => (
          <button key={h} type="button" disabled={busy} onClick={() => extend(h)}
                  className="rounded-sm border border-accent px-3 py-1 text-sm text-accent disabled:opacity-50">
            +{h} h
          </button>
        ))}
        <button type="button" onClick={onClose} className="ml-auto text-sm text-text-dim">Close</button>
      </div>
    </div>
  );
}
