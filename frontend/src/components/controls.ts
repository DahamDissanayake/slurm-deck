const box = "rounded-sm border border-border bg-surface-2 px-3 text-text";
const btn = "inline-flex items-center justify-center rounded-sm border px-4 disabled:opacity-50";

export const input = `h-10 ${box}`;
export const select = `h-10 ${box}`;
export const textarea = `min-h-20 py-2 ${box}`;
export const primary = `h-10 ${btn} border-accent bg-accent font-semibold text-bg`;
export const secondary = `h-10 ${btn} border-border text-text hover:border-accent`;
export const danger = `h-10 ${btn} border-danger text-danger hover:bg-danger/10`;
export const small = `h-8 ${btn} border-border px-3 text-sm text-text hover:border-accent`;
export const smallDanger = `h-8 ${btn} border-danger px-3 text-sm text-danger hover:bg-danger/10`;
export const full = "w-full";
export const inputRow = "flex flex-wrap items-end gap-2";

export const PRESETS = { input, select, textarea, primary, secondary, danger, small, smallDanger };
