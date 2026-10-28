import "@xterm/xterm/css/xterm.css";

import { FitAddon } from "@xterm/addon-fit";
import { Terminal as XTerm } from "@xterm/xterm";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, apiFetch } from "../api/client";
import { Link } from "../app/navigation";
import { secondary } from "./NewJob/StepInputs";

/** A shell in the browser: a terminal created through the proxy on the job's
 * Jupyter server, spoken to over terminado's WebSocket protocol
 * (["stdin", data] in, ["stdout", data] out, ["set_size", rows, cols, ...]). */
export function Terminal({ jobId }: { jobId: string }) {
  const host = useRef<HTMLDivElement>(null);
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<"connecting" | "open" | "closed">("connecting");
  const [error, setError] = useState("");

  useEffect(() => {
    let socket: WebSocket | null = null;
    let cancelled = false;
    const term = new XTerm({ cursorBlink: true, fontFamily: "monospace", fontSize: 14 });
    const fit = new FitAddon();
    term.loadAddon(fit);
    if (host.current) term.open(host.current);
    const send = (msg: unknown[]) => {
      if (socket && socket.readyState === 1) socket.send(JSON.stringify(msg));
    };
    term.onData((data) => send(["stdin", data]));
    term.onResize(({ rows, cols }) => send(["set_size", rows, cols, 0, 0]));
    const refit = () => fit.fit();
    window.addEventListener("resize", refit);

    setStatus("connecting");
    setError("");
    apiFetch<{ name: string }>(`/terminal/${jobId}/api/terminals`, { method: "POST" }).then(
      ({ name }) => {
        if (cancelled) return;
        const scheme = window.location.protocol === "https:" ? "wss" : "ws";
        socket = new WebSocket(
          `${scheme}://${window.location.host}/terminal/${jobId}/terminals/websocket/${name}`);
        socket.onopen = () => {
          setStatus("open");
          fit.fit();
          send(["set_size", term.rows, term.cols, 0, 0]);
          term.focus();
        };
        socket.onmessage = (e) => {
          const [kind, data] = JSON.parse(e.data as string);
          if (kind === "stdout") term.write(data);
        };
        socket.onclose = () => { if (!cancelled) setStatus("closed"); };
      },
      (err) => {
        if (cancelled) return;
        setStatus("closed");
        setError(err instanceof ApiError && err.message ? err.message
          : "Couldn't start a terminal. The session may still be starting.");
      });

    return () => {
      cancelled = true;
      window.removeEventListener("resize", refit);
      if (socket) { socket.onclose = null; socket.close(); }
      term.dispose();
    };
  }, [jobId, attempt]);

  const reconnect = useCallback(() => setAttempt((n) => n + 1), []);
  return (
    <div className="flex h-screen flex-col bg-bg p-2 text-text">
      <header className="mb-2 flex items-center gap-3 text-sm">
        <span className="font-mono">Terminal · job {jobId}</span>
        <span className="text-text-dim">{status === "open" ? "Connected" : status === "closed"
          ? "Disconnected" : "Connecting…"}</span>
        {status === "closed" && (
          <button type="button" className={secondary} onClick={reconnect}>Reconnect</button>
        )}
        <Link href="/services" className="ml-auto text-accent">Services</Link>
      </header>
      {error && <p role="alert" className="mb-2 text-danger">{error}</p>}
      <div ref={host} className="min-h-0 flex-1" />
    </div>
  );
}
