import { useEffect, useRef, useState } from "react";
import { Upload } from "tus-js-client";

import { csrfToken } from "../api/client";
import { type ActiveUpload, ARCHIVE, files, formatBytes, join } from "../api/files";
import { primary, secondary } from "../pages/NewJob/StepInputs";

const ZIP_HINT = "Zip first — 1 million small files upload far slower than one archive.";
const MANY_FILES = 1000;

type Item = { key: string; name: string; size: number; sent: number; speed: number;
              state: "waiting" | "uploading" | "paused" | "done" | "failed" | "cancelled";
              error?: string };

const relPath = (f: File) => (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
const dirOf = (rel: string) => rel.split("/").slice(0, -1).join("/");

/** The server's own words when it refuses an upload (no space, no write access). */
function reason(err: Error): string {
  const body = (err as Error & { originalResponse?: { getBody(): string } | null })
    .originalResponse?.getBody();
  try {
    return JSON.parse(body ?? "").message || "The upload failed.";
  } catch {
    return "The upload failed.";
  }
}

/** Resumable uploads into destDir: files or a whole folder, 64 MB tus chunks,
 * resumable after a reload by choosing the same file again. */
export function UploadPanel({ destDir, onDone }: { destDir: string; onDone?: () => void }) {
  const [queue, setQueue] = useState<File[]>([]);
  const [extract, setExtract] = useState(false);
  const [items, setItems] = useState<Item[]>([]);
  const [active, setActive] = useState<ActiveUpload[]>([]);
  const uploads = useRef(new Map<string, { upload: Upload; done: () => void }>());

  useEffect(() => {
    files.activeUploads().then((r) => setActive(r.uploads), () => setActive([]));
  }, []);

  const update = (key: string, patch: Partial<Item>) =>
    setItems((xs) => xs.map((x) => (x.key === key ? { ...x, ...patch } : x)));

  function send(file: File, key: string, dest: string): Promise<void> {
    return new Promise((resolve) => {
      let last = { t: Date.now(), bytes: 0 };
      const upload = new Upload(file, {
        endpoint: "/api/uploads",
        chunkSize: 64 * 1024 * 1024,
        retryDelays: [0, 1000, 3000, 5000, 10000, 30000],
        headers: { "X-CSRF-Token": csrfToken() },
        metadata: { filename: file.name, dest_dir: dest, replace: "0" },
        removeFingerprintOnSuccess: true,
        onProgress: (sent) => {
          const now = Date.now();
          const speed = now > last.t ? ((sent - last.bytes) * 1000) / (now - last.t) : 0;
          if (now - last.t > 1000) last = { t: now, bytes: sent };
          update(key, { sent, speed, state: "uploading" });
        },
        onSuccess: async () => {
          update(key, { sent: file.size, state: "done" });
          if (extract && ARCHIVE.test(file.name)) {
            await files.extract(join(dest, file.name), dest).catch(
              () => update(key, { error: "It uploaded, but extracting it didn't work." }));
          }
          resolve();
        },
        onError: (err) => { update(key, { state: "failed", error: reason(err) }); resolve(); },
      });
      uploads.current.set(key, { upload, done: resolve });
      upload.findPreviousUploads().then((prev) => {
        if (prev.length) upload.resumeFromPreviousUpload(prev[0]);
        upload.start();
      });
    });
  }

  async function start() {
    const batch = queue.map((f, i) => ({ f, key: `${Date.now()}-${i}`, rel: relPath(f) }));
    setQueue([]);
    setItems((xs) => [...xs, ...batch.map(({ f, key, rel }) => ({
      key, name: rel, size: f.size, sent: 0, speed: 0, state: "waiting" as const }))]);
    const dirs = [...new Set(batch.map((b) => dirOf(b.rel)).filter(Boolean))].sort();
    for (const d of dirs) {
      // Parents sort before their children; an existing folder is fine.
      await files.mkdir(join(destDir, d)).catch(() => undefined);
    }
    for (const b of batch) {
      const dir = dirOf(b.rel);
      await send(b.f, b.key, dir ? join(destDir, dir) : destDir);
    }
    setActive([]);
    onDone?.();
  }

  function control(key: string, action: "pause" | "resume" | "cancel") {
    const u = uploads.current.get(key);
    if (!u) return;
    if (action === "resume") {
      u.upload.start();
      update(key, { state: "uploading" });
      return;
    }
    u.upload.abort(action === "cancel");
    update(key, { state: action === "cancel" ? "cancelled" : "paused" });
    if (action === "cancel") u.done();
  }

  const pick = (list: FileList | null) => setQueue(list ? Array.from(list) : []);
  return (
    <div className="text-sm">
      {active.length > 0 && (
        <p className="mb-2 text-text-dim">
          Unfinished: {active.map((a) => `${a.filename} (${formatBytes(a.offset)} of ${formatBytes(a.size)})`)
            .join(", ")}. Choose the same file again to resume it.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <label className={secondary}>Upload files
          <input type="file" multiple className="sr-only" onChange={(e) => pick(e.target.files)} />
        </label>
        <label className={secondary}>Upload folder
          <input type="file" multiple className="sr-only" onChange={(e) => pick(e.target.files)}
                 {...{ webkitdirectory: "" }} />
        </label>
      </div>
      {queue.length > 0 && (
        <div className="mt-3">
          <p>{queue.length} file{queue.length === 1 ? "" : "s"},{" "}
            {formatBytes(queue.reduce((n, f) => n + f.size, 0))}, to {destDir}</p>
          {queue.length > MANY_FILES && <p role="note" className="text-warning">{ZIP_HINT}</p>}
          {queue.some((f) => ARCHIVE.test(f.name)) && (
            <label className="block"><input type="checkbox" checked={extract}
              onChange={(e) => setExtract(e.target.checked)} /> Extract after upload</label>
          )}
          <button type="button" className={`${primary} mt-2`} onClick={start}>Start upload</button>
        </div>
      )}
      <ul className="mt-3 space-y-1">
        {items.map((x) => {
          const left = x.speed > 0 ? Math.round((x.size - x.sent) / x.speed) : null;
          return (
            <li key={x.key} className="flex flex-wrap items-center gap-2">
              <span className="font-mono">{x.name}</span>
              <progress max={x.size || 1} value={x.sent} aria-label={`${x.name} progress`} />
              <span className="text-text-dim">
                {x.state === "uploading" ? `${formatBytes(x.speed)}/s${left !== null ? `, ${left} s left` : ""}`
                  : x.state}
              </span>
              {x.error && <span role="alert" className="text-danger">{x.error}</span>}
              {x.state === "uploading" && (
                <button type="button" onClick={() => control(x.key, "pause")}>Pause</button>)}
              {x.state === "paused" && (
                <button type="button" onClick={() => control(x.key, "resume")}>Resume</button>)}
              {(x.state === "uploading" || x.state === "paused") && (
                <button type="button" onClick={() => control(x.key, "cancel")}>Cancel</button>)}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
