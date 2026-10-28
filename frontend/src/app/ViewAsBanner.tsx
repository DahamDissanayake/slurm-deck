/** Shown on every page while an admin views the app as another user. */
export function ViewAsBanner({ actingAs, onStop }: {
  actingAs: string | null;
  onStop: () => void;
}) {
  if (!actingAs) return null;
  return (
    <div role="status" className="flex items-center justify-center gap-3 bg-danger px-4 py-2 text-sm font-semibold text-bg">
      <span>Viewing as {actingAs} — every action is recorded.</span>
      <button type="button" onClick={onStop} className="underline">Stop viewing</button>
    </div>
  );
}
