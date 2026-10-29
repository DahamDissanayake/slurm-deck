import { focusRing } from "./ui/cx";

const box = `rounded-md border border-border bg-surface px-3 text-md text-text placeholder:text-text-dim hover:border-border-strong ${focusRing}`;
const btn = `inline-flex items-center justify-center rounded-md border px-4 font-medium transition-colors duration-fast disabled:cursor-not-allowed disabled:opacity-50 ${focusRing}`;

export const input = `h-10 ${box}`;
export const select = `h-10 ${box}`;
export const textarea = `min-h-20 py-2 ${box}`;
export const primary = `h-10 ${btn} border-transparent bg-accent text-accent-fg shadow-sm hover:bg-accent-strong`;
export const secondary = `h-10 ${btn} border-border bg-surface text-text shadow-sm hover:border-border-strong hover:bg-surface-2`;
export const danger = `h-10 ${btn} border-transparent bg-danger-soft text-danger hover:border-danger`;
export const small = `h-8 ${btn} border-border bg-surface px-3 text-sm text-text hover:border-border-strong hover:bg-surface-2`;
export const smallDanger = `h-8 ${btn} border-transparent bg-danger-soft px-3 text-sm text-danger hover:border-danger`;
export const full = "w-full";
export const inputRow = "flex flex-wrap items-end gap-2";

export const PRESETS = { input, select, textarea, primary, secondary, danger, small, smallDanger };
