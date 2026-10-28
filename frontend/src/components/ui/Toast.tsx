import { createContext, type ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";

import { AlertIcon, CheckIcon, InfoIcon, XIcon } from "../icons";
import { cx } from "./cx";
import { IconButton } from "./IconButton";

export type ToastTone = "ok" | "danger" | "info";
export type ToastInput = { tone?: ToastTone; message: string; duration?: number };
type Toast = ToastInput & { id: number };

const ICONS: Record<ToastTone, [ReactNode, string]> = {
  ok: [<CheckIcon key="ok" />, "bg-ok-soft text-ok"],
  danger: [<AlertIcon key="danger" />, "bg-danger-soft text-danger"],
  info: [<InfoIcon key="info" />, "bg-info-soft text-info"],
};

const ToastContext = createContext<(toast: ToastInput) => void>(() => {});

/** Show the result of an action: `const toast = useToast(); toast({ tone: "ok", message: "Job cancelled" })`. */
export const useToast = () => useContext(ToastContext);

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  const tone = toast.tone ?? "info";
  useEffect(() => {
    const t = setTimeout(() => onDismiss(toast.id), toast.duration ?? 5000);
    return () => clearTimeout(t);
  }, [toast.id, toast.duration, onDismiss]);
  return (
    <div role={tone === "danger" ? "alert" : "status"}
         className="flex items-center gap-3 rounded-md border border-border bg-surface p-3 shadow-lg motion-safe:animate-toast-in">
      <span aria-hidden="true" className={cx("inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
        "[&>svg]:h-4 [&>svg]:w-4", ICONS[tone][1])}>{ICONS[tone][0]}</span>
      <p className="min-w-0 flex-1 text-md text-text">{toast.message}</p>
      <IconButton label="Dismiss" icon={<XIcon />} size="sm" onClick={() => onDismiss(toast.id)} />
    </div>
  );
}

/** Holds the toasts, bottom right, each dismissed after a few seconds or on close. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(0);
  const dismiss = useCallback((id: number) => setToasts((ts) => ts.filter((t) => t.id !== id)), []);
  const push = useCallback((t: ToastInput) => setToasts((ts) => [...ts, { ...t, id: ++next.current }]), []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <section aria-label="Notifications"
               className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2 [&>*]:pointer-events-auto">
        {toasts.map((t) => <ToastItem key={t.id} toast={t} onDismiss={dismiss} />)}
      </section>
    </ToastContext.Provider>
  );
}
