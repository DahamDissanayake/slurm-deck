import { useEffect, useState } from "react";

import { logUrl, readLog } from "../api/jobs";
import { DownloadIcon, SearchIcon } from "./icons";
import { buttonClass } from "./ui/Button";
import { cx } from "./ui/cx";
import { Notice } from "./ui/Notice";
import { SegmentedControl } from "./ui/SegmentedControl";

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
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <SegmentedControl label="Log stream" value={stream} onChange={setStream}
                          options={[{ value: "out", label: "Output" }, { value: "err", label: "Errors" }]} />
        <label className="relative">
          <span aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-dim [&>svg]:h-4 [&>svg]:w-4">
            <SearchIcon />
          </span>
          <input aria-label="Search the log" placeholder="Search" value={query}
                 onChange={(e) => setQuery(e.target.value)}
                 className="h-8 w-48 rounded-full border border-border bg-surface pl-9 pr-3 text-md text-text placeholder:text-text-dim focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent" />
        </label>
        {running && <span className="text-xs text-text-dim">Updating every 2 s</span>}
        <a href={logUrl(jobId, stream)} download={`job-${jobId}.${stream}.log`}
           className={cx(buttonClass({ variant: "secondary", size: "sm", pill: true }), "ml-auto gap-1.5 [&>svg]:h-4 [&>svg]:w-4")}>
          <DownloadIcon />Download
        </a>
      </div>
      {clipped && (
        <Notice className="mb-3">Showing the last 1 MB. Download for the full log.</Notice>
      )}
      {error && <p className="mb-3 text-md text-text-dim">{error}</p>}
      <pre className="max-h-[32rem] min-h-24 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-bg p-4 font-mono text-xs leading-5">
        {shown}
      </pre>
    </div>
  );
}
