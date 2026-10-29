import { useEffect, useRef, useState } from "react";
import { Upload } from "tus-js-client";

import { csrfToken } from "../api/client";
import { type ActiveUpload, ARCHIVE, files, formatBytes, join } from "../api/files";
import { fileIcon, PauseIcon, PlayIcon, XIcon } from "./icons";
import { Button } from "./ui/Button";
import { IconButton } from "./ui/IconButton";
import { Meter } from "./ui/Meter";
import { Notice } from "./ui/Notice";

const ZIP_HINT = "Zip first — 1 million small files upload far slower than one archive.";
const MANY_FILES = 1000;

type Item = { key: string; name: string; size: number; sent: number; speed: number;
              state: "waiting" | "uploading" | "paused" | "done" | "failed" | "cancelled";
              error?: string };
/** Files to upload; a new `id` is a new batch. */
export type Incoming = { files: File[]; id: number };

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

/** The upload tray: resumable uploads into destDir, 64 MB tus chunks,
 * resumable after a reload by choosing the same file again. Files handed in
 * as `incoming` start at once; a big folder or an archive waits for a
 * choice first (zip it, or extract it afterwards). */
export function UploadPanel({ destDir, onDone, incoming }: {
  destDir: string; onDone?: () => void; incoming?: Incoming | null;
}) {
  const [queue, setQueue] = useState<File[]>([]);
  const [extract, setExtract] = useState(false);
  const [items, setItems] = useState<Item[]>([]);
  const [active, setActive] = useState<ActiveUpload[]>([]);
  const uploads = useRef(new Map<string, { upload: Upload; done: () => void }>());
  const handled = useRef<number | null>(null);

  useEffect(() => {
    files.activeUploads().then((r) => setActive(r.uploads), () => setActive([]));
  }, []);

  const update = (key: string, patch: Partial<Item>) =>
    setItems((xs) => xs.map((x) => (x.key === key ? { ...x, ...patch } : x)));

  function send(file: File, key: string, dest: string, unpack: boolean): Promise<void> {
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
          if (unpack && ARCHIVE.test(file.name)) {
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

  async function start(list: File[], unpack: boolean) {
    const batch = list.map((f, i) => ({ f, key: `${Date.now()}-${i}`, rel: relPath(f) }));
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
      await send(b.f, b.key, dir ? join(destDir, dir) : destDir, unpack);
    }
    setActive([]);
    onDone?.();
  }

  useEffect(() => {
    if (!incoming || handled.current === incoming.id || incoming.files.length === 0) return;
    handled.current = incoming.id;
    if (incoming.files.length > MANY_FILES || incoming.files.some((f) => ARCHIVE.test(f.name))) {
      setExtract(false);
      setQueue(incoming.files);
    } else {
      void start(incoming.files, false);
    }
    // start() closes over destDir and onDone, which belong to this batch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incoming]);

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

  if (!queue.length && !items.length && !active.length) return null;
  return (
    <section aria-label="Uploads" className="rounded-lg border border-border bg-surface p-4 text-md shadow-lg">
      <h2 className="mb-3 text-md font-semibold text-text">Uploads</h2>
      {active.length > 0 && (
        <Notice tone="info" className="mb-3">
          Unfinished: {active.map((a) => `${a.filename} (${formatBytes(a.offset)} of ${formatBytes(a.size)})`)
            .join(", ")}. Choose the same file again to resume it.
        </Notice>
      )}
      {queue.length > 0 && (
        <div className="mb-3 space-y-2">
          <p className="text-text">{queue.length} file{queue.length === 1 ? "" : "s"},{" "}
            {formatBytes(queue.reduce((n, f) => n + f.size, 0))}, to {destDir}</p>
          {queue.length > MANY_FILES && <Notice role="note">{ZIP_HINT}</Notice>}
          {queue.some((f) => ARCHIVE.test(f.name)) && (
            <label className="flex items-center gap-2 text-text"><input type="checkbox" checked={extract}
              onChange={(e) => setExtract(e.target.checked)} className="h-4 w-4 accent-accent" /> Extract after upload</label>
          )}
          <div className="flex gap-2">
            <Button size="sm" pill onClick={() => start(queue, extract)}>Start upload</Button>
            <Button variant="ghost" size="sm" pill onClick={() => setQueue([])}>Cancel</Button>
          </div>
        </div>
      )}
      <ul className="max-h-60 space-y-3 overflow-y-auto">
        {items.map((x) => {
          const left = x.speed > 0 ? Math.round((x.size - x.sent) / x.speed) : null;
          const Icon = fileIcon(x.name);
          return (
            <li key={x.key} className="flex items-center gap-3">
              <span aria-hidden="true" className="text-text-dim"><Icon className="h-5 w-5" /></span>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate font-mono text-sm text-text">{x.name}</span>
                  <span className="shrink-0 text-xs text-text-dim">
                    {x.state === "uploading" ? `${formatBytes(x.speed)}/s${left !== null ? `, ${left} s left` : ""}`
                      : x.state}
                  </span>
                </div>
                <Meter label={`${x.name} progress`} value={x.sent} max={x.size || 1}
                       tone={x.state === "failed" ? "danger" : x.state === "done" ? "ok" : "accent"} className="mt-1.5" />
                {x.error && <p role="alert" className="mt-1 text-xs text-danger">{x.error}</p>}
              </div>
              {x.state === "uploading" && (
                <IconButton label={`Pause ${x.name}`} icon={<PauseIcon />} size="sm" onClick={() => control(x.key, "pause")} />)}
              {x.state === "paused" && (
                <IconButton label={`Resume ${x.name}`} icon={<PlayIcon />} size="sm" onClick={() => control(x.key, "resume")} />)}
              {(x.state === "uploading" || x.state === "paused") && (
                <IconButton label={`Cancel ${x.name}`} icon={<XIcon />} size="sm" onClick={() => control(x.key, "cancel")} />)}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
