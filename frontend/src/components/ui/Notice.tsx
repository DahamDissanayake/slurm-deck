import type { ReactNode } from "react";

import { AlertIcon, InfoIcon } from "../icons";
import { cx } from "./cx";

const TONES = { warning: "bg-warning-soft text-warning", danger: "bg-danger-soft text-danger", info: "bg-info-soft text-info" };

/** A message in a page, with an icon so it is never colour alone. `alert`
 * interrupts a screen reader; without it the notice is a polite status. */
export function Notice({ tone = "warning", alert = false, children, className, ...rest }: {
  tone?: keyof typeof TONES; alert?: boolean; children: ReactNode; className?: string; role?: string;
}) {
  return (
    <p role={rest.role ?? (alert ? "alert" : "status")}
       className={cx("flex items-start gap-2.5 rounded-md px-4 py-3 text-md", TONES[tone], className)}>
      <span aria-hidden="true" className="mt-0.5 inline-flex shrink-0 [&>svg]:h-4 [&>svg]:w-4">
        {tone === "info" ? <InfoIcon /> : <AlertIcon />}
      </span>
      <span className="min-w-0">{children}</span>
    </p>
  );
}
