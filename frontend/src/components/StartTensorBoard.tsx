import { useState } from "react";

import { ApiError } from "../api/client";
import { sessions } from "../api/sessions";
import { primary } from "../pages/NewJob/StepInputs";
import { FilePicker } from "./FilePicker";

/** "Start TensorBoard": pick the folder with the training logs, then submit. */
export function StartTensorBoard({ onStarted }: { onStarted: () => void }) {
  const [picking, setPicking] = useState(false);
  const [error, setError] = useState("");

  async function start(dir: string) {
    setError("");
    try {
      await sessions.startTensorBoard(dir);
      onStarted();
    } catch (err) {
      setError(err instanceof ApiError && err.message ? err.message : "TensorBoard didn't start.");
    }
  }

  return (
    <div>
      <button type="button" className={primary} onClick={() => setPicking(true)}>
        Start TensorBoard
      </button>
      {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
      {picking && <FilePicker mode="dir" onPick={start} onClose={() => setPicking(false)} />}
    </div>
  );
}
