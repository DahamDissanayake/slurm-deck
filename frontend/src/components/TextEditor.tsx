import { useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { files } from "../api/files";
import { primary, secondary } from "../pages/NewJob/StepInputs";

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
      <p className="mb-2 font-mono text-sm">{path}{dirty && " •"}</p>
      {message && <p role="status" className="mb-2 text-sm text-text-dim">{message}</p>}
      {saved !== null && (
        <textarea aria-label="Editor" value={text} spellCheck={false}
                  onChange={(e) => setText(e.target.value)}
                  className="h-96 w-full rounded-sm border border-border bg-surface-2 p-2 font-mono text-sm" />
      )}
      <div className="mt-2 flex gap-2">
        <button type="button" className={primary} disabled={!dirty} onClick={save}>Save</button>
        <button type="button" className={secondary}
                onClick={() => { if (!dirty || window.confirm(LEAVE)) onClose(); }}>Close</button>
      </div>
    </div>
  );
}
