import { useState } from "react";

import { ApiError } from "../../api/client";
import { AREAS, cluster } from "../../api/cluster";
import { FilePicker } from "../../components/FilePicker";
import { Panel } from "../../components/Panel";
import { inputClass, primaryButton, smallButton } from "./AdminLayout";

const say = (e: unknown, fallback: string) =>
  e instanceof ApiError && e.message ? e.message : fallback;

/** Copy something from a user's area into a shared area, or remove it from one. */
export function SharedAssets() {
  const [src, setSrc] = useState("");
  const [area, setArea] = useState(AREAS[1]);
  const [name, setName] = useState("");
  const [replace, setReplace] = useState(false);
  const [picking, setPicking] = useState(false);
  const [note, setNote] = useState("");

  async function publish() {
    try {
      const r = await cluster.publish(src.trim(), area, name.trim(), replace) as { path: string };
      setNote(`Published to ${r.path}.`);
    } catch (e) {
      setNote(say(e, "Publishing failed."));
    }
  }
  async function remove() {
    if (!window.confirm(`Remove ${area}/${name.trim()} from the shared area? This can't be undone.`)) return;
    try {
      await cluster.unpublish(area, name.trim());
      setNote(`Removed ${area}/${name.trim()}.`);
    } catch (e) {
      setNote(say(e, "Removing failed."));
    }
  }

  return (
    <Panel title="Shared assets">
      <p className="mb-3 text-sm text-text-dim">
        Copies a folder or file from a user's area into <code>/shared</code>. Users can read the
        shared areas but not change them.
      </p>
      <div className="grid max-w-xl gap-3 text-sm">
        <label>Source (a path under /shared/users)
          <div className="flex gap-2">
            <input className={inputClass} value={src} onChange={(e) => setSrc(e.target.value)} />
            <button type="button" className={smallButton} onClick={() => setPicking(true)}>Browse</button>
          </div>
        </label>
        <label>Shared area
          <select className={inputClass} value={area} onChange={(e) => setArea(e.target.value)}>
            {AREAS.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
        <label>Name
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label><input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
          {" "}Replace it if the name is already there</label>
        <div className="flex gap-2">
          <button type="button" className={primaryButton} disabled={!src.trim() || !name.trim()}
                  onClick={publish}>Publish</button>
          <button type="button" className={smallButton} disabled={!name.trim()} onClick={remove}>
            Remove from {area}
          </button>
        </div>
        {note && <p role="status">{note}</p>}
      </div>
      {picking && <FilePicker mode="dir" onClose={() => setPicking(false)} onPick={setSrc} />}
    </Panel>
  );
}
