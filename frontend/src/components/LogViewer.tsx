import { useEffect, useState } from "react";

import { logUrl, readLog } from "../api/jobs";

const MAX = 1024 * 1024;
const POLL_MS = 2000;

/** A job's log as plain text: React renders it as text, so markup and escape
 * codes show literally. Over 1 MB only the end is shown. While the job runs,
 * new output is fetched every 2 s from where the last read stopped. */
export function LogViewer({ jobId, running }: { jobId: string; running: boolean }) {
  const [stream, setStream] = useState<"out" | "err">("out");
  const [text, setText] = useState("");
  const [clipped, setClipped] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");

  useEffect(() => {
    let stop = false;
    let offset = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setText("");
    setClipped(false);
    setError("");

    async function tick(first: boolean) {
      try {
        let part = await readLog(jobId, stream, offset);
        if (first && part.size > MAX) {
          offset = part.size - MAX;
          part = await readLog(jobId, stream, offset);
          if (!stop) setClipped(true);
        }
        if (stop) return;
        offset += new TextEncoder().encode(part.text).length;
        if (part.text) setText((t) => (first ? part.text : t + part.text));
      } catch {
        if (!stop) setError("This log isn't available yet.");
      }
      if (running && !stop) timer = setTimeout(() => tick(false), POLL_MS);
    }
    tick(true);
    return () => { stop = true; clearTimeout(timer); };
  }, [jobId, stream, running]);

  const shown = query
    ? text.split("\n").filter((l) => l.toLowerCase().includes(query.toLowerCase())).join("\n")
    : text;

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-3 text-sm">
        {(["out", "err"] as const).map((s) => (
          <button key={s} type="button" onClick={() => setStream(s)} aria-pressed={stream === s}
                  className={stream === s ? "text-accent" : "text-text-dim"}>
            {s === "out" ? "Output" : "Errors"}
          </button>
        ))}
        <input aria-label="Search the log" placeholder="Search" value={query}
               onChange={(e) => setQuery(e.target.value)}
               className="rounded-sm border border-border bg-surface-2 px-2 py-1 text-text" />
        <a href={logUrl(jobId, stream)} download={`job-${jobId}.${stream}.log`}
           className="ml-auto text-accent">Download</a>
      </div>
      {clipped && (
        <p className="mb-2 text-sm text-warning">Showing the last 1 MB — Download for the full log.</p>
      )}
      {error && <p className="mb-2 text-sm text-text-dim">{error}</p>}
      <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap rounded-sm border border-border bg-bg p-3 font-mono text-xs">
        {shown}
      </pre>
    </div>
  );
}
