import { useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { files } from "../api/files";
import { Button } from "./ui/Button";
import { Notice } from "./ui/Notice";

const LEAVE = "You have unsaved changes. Leave without saving?";

/** Edits a UTF-8 text file of up to 1 MiB. While there are unsaved changes,
 * closing, in-app links and leaving the page all ask first. */
export function TextEditor({ path, onClose }: { path: string; onClose: () => void }) {
  const [saved, setSaved] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [message, setMessage] = useState("");
  const dirty = saved !== null && text !== saved;

  useEffect(() => {
    files.getText(path).then((r) => { setSaved(r.text); setText(r.text); },
      (e) => setMessage(e instanceof ApiError && e.message ? e.message : "This file can't be edited."));
  }, [path]);

  useEffect(() => {
    if (!dirty) return;
    const unload = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    // Capture phase, so this runs before Link's own click handler.
    const click = (e: MouseEvent) => {
      if ((e.target as Element | null)?.closest?.("a[href]") && !window.confirm(LEAVE)) {
        e.preventDefault();
      }
    };
    window.addEventListener("beforeunload", unload);
    document.addEventListener("click", click, true);
    return () => {
      window.removeEventListener("beforeunload", unload);
      document.removeEventListener("click", click, true);
    };
  }, [dirty]);

  async function save() {
    try {
      await files.putText(path, text);
      setSaved(text);
      setMessage("Saved.");
    } catch (e) {
      setMessage(e instanceof ApiError && e.message ? e.message : "It didn't save.");
    }
  }

  return (
    <div>
      <p className="mb-2 font-mono text-md text-text">{path}{dirty && " •"}</p>
      {message && <Notice tone="info" className="mb-2 py-2">{message}</Notice>}
      {saved !== null && (
        <textarea aria-label="Editor" value={text} spellCheck={false}
                  onChange={(e) => setText(e.target.value)}
                  className="h-96 w-full rounded-md border border-border bg-bg p-3 font-mono text-sm text-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent" />
      )}
      <div className="mt-3 flex gap-2">
        <Button size="sm" pill disabled={!dirty} onClick={save}>Save</Button>
        <Button variant="secondary" size="sm" pill
                onClick={() => { if (!dirty || window.confirm(LEAVE)) onClose(); }}>Close</Button>
      </div>
    </div>
  );
}
