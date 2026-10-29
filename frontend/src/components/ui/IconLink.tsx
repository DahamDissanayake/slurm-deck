import type { ReactNode } from "react";

import { Link } from "../../app/navigation";
import { buttonClass, type ButtonSize, type ButtonVariant } from "./Button";
import { cx } from "./cx";
import { Tooltip } from "./Tooltip";

/** An icon-only link: `label` is its accessible name and its tooltip. */
export function IconLink({ href, label, icon, variant = "ghost", size = "md", tooltipSide, className }: {
  href: string; label: string; icon: ReactNode; variant?: ButtonVariant; size?: ButtonSize;
  tooltipSide?: "top" | "bottom"; className?: string;
}) {
  return (
    <Tooltip content={label} describe={false} side={tooltipSide}>
      <Link href={href} aria-label={label}
            className={cx(buttonClass({ variant, size, square: true }), "[&>svg]:h-4 [&>svg]:w-4", className)}>
        {icon}
      </Link>
    </Tooltip>
  );
}
