/** Join class names, skipping falsy ones. */
export const cx = (...names: (string | false | null | undefined)[]) => names.filter(Boolean).join(" ");

/** The visible keyboard focus ring every kit control shares. */
export const focusRing =
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";
