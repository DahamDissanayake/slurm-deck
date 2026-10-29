import { type ButtonHTMLAttributes, forwardRef, type ReactNode } from "react";

import { cx, focusRing } from "./cx";
import { Spinner } from "./Spinner";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "border-transparent bg-accent text-accent-fg shadow-sm hover:bg-accent-strong",
  secondary: "border-border bg-surface text-text shadow-sm hover:border-border-strong hover:bg-surface-2",
  ghost: "border-transparent bg-transparent text-text-dim hover:bg-surface-2 hover:text-text",
  danger: "border-transparent bg-danger-soft text-danger hover:border-danger",
};
const SIZES: Record<ButtonSize, string> = { sm: "h-8 gap-1.5 px-3 text-sm", md: "h-10 gap-2 px-4 text-md" };
const ICON_SIZES: Record<ButtonSize, string> = { sm: "h-8 w-8", md: "h-10 w-10" };

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Leading icon; replaced by the spinner while loading. */
  icon?: ReactNode;
  loading?: boolean;
  /** Fully rounded, for toolbars. */
  pill?: boolean;
  /** Square, icon only: use IconButton, which adds the label and tooltip. */
  square?: boolean;
};

export const buttonClass = ({ variant = "primary", size = "md", pill = false, square = false }:
  Pick<ButtonProps, "variant" | "size" | "pill" | "square">) => cx(
  "inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap border font-medium",
  "transition-colors duration-fast ease-out disabled:cursor-not-allowed disabled:opacity-50",
  focusRing, VARIANTS[variant], square ? ICON_SIZES[size] : SIZES[size], pill || square ? "rounded-full" : "rounded-md",
);

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant, size, icon, loading = false, pill, square, disabled, type = "button", className, children, ...rest }, ref,
) {
  return (
    <button ref={ref} type={type} disabled={disabled || loading} aria-busy={loading || undefined}
            className={cx(buttonClass({ variant, size, pill, square }), className)} {...rest}>
      {loading ? <Spinner label={null} /> : icon && <span aria-hidden="true" className="contents [&>svg]:h-4 [&>svg]:w-4">{icon}</span>}
      {children}
    </button>
  );
});
