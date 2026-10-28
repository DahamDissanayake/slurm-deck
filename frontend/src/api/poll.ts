import { useEffect, useState } from "react";

/** load()'s latest result, refreshed every ms; `failed` if the last try failed. */
export function usePolled<T>(load: () => Promise<T>, ms: number):
    { data: T | null; failed: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let stopped = false;
    const run = () => load().then(
      (d) => { if (!stopped) { setData(d); setFailed(false); } },
      () => { if (!stopped) setFailed(true); });
    run();
    const timer = setInterval(run, ms);
    return () => { stopped = true; clearInterval(timer); };
  }, [load, ms]);
  return { data, failed };
}
