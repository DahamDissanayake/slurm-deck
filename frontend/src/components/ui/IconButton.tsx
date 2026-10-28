import { forwardRef, type ReactNode } from "react";

import { Button, type ButtonProps } from "./Button";
import { Tooltip } from "./Tooltip";

/** An icon-only button: `label` is its accessible name and its tooltip. */
export const IconButton = forwardRef<HTMLButtonElement, Omit<ButtonProps, "children" | "icon" | "square"> & {
  label: string; icon: ReactNode; tooltipSide?: "top" | "bottom";
}>(function IconButton({ label, icon, variant = "ghost", tooltipSide, ...rest }, ref) {
  return (
    <Tooltip content={label} describe={false} side={tooltipSide}>
      <Button ref={ref} aria-label={label} variant={variant} square icon={icon} {...rest} />
    </Tooltip>
  );
});
