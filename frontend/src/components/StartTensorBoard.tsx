import { useState } from "react";

import { ApiError } from "../api/client";
import { sessions } from "../api/sessions";
import { Button } from "./ui/Button";
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
      <Button onClick={() => setPicking(true)}>Start TensorBoard</Button>
      {error && <p role="alert" className="mt-2 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}
      {picking && <FilePicker mode="dir" onPick={start} onClose={() => setPicking(false)} />}
    </div>
  );
}
