import type { ReactNode } from "react";

export const iconButton =
  "inline-flex h-8 w-8 items-center justify-center rounded-sm border border-border text-text-dim " +
  "hover:border-accent hover:text-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";

function Icon({ className = "h-5 w-5", children }: { className?: string; children: ReactNode }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={className}>
      {children}
    </svg>
  );
}

type Props = { className?: string };

export const SunIcon = (p: Props) => (
  <Icon {...p}><circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></Icon>
);
export const MoonIcon = (p: Props) => (
  <Icon {...p}><path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" /></Icon>
);
export const KeyIcon = (p: Props) => (
  <Icon {...p}><circle cx="8" cy="15" r="4" /><path d="M11 12l9-9M16 7l3 3" /></Icon>
);
export const SignOutIcon = (p: Props) => (
  <Icon {...p}><path d="M10 4H5v16h5M15 8l4 4-4 4M19 12H9" /></Icon>
);
