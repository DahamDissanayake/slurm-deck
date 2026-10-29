import { EyeIcon } from "../components/icons";
import { Button } from "../components/ui/Button";

/** A slim pill in the top bar while an admin views the app as another user. */
export function ViewAsPill({ actingAs, onStop }: {
  actingAs: string | null;
  onStop: () => void;
}) {
  if (!actingAs) return null;
  return (
    <div role="status" title="Every action is recorded."
         className="flex min-w-0 items-center gap-1.5 rounded-full bg-danger-soft py-0.5 pl-3 pr-0.5 text-sm font-medium text-danger">
      <EyeIcon className="h-4 w-4 shrink-0" />
      <span className="truncate">Viewing as {actingAs}</span>
      <span className="sr-only">. Every action is recorded.</span>
      <Button variant="danger" size="sm" pill aria-label={`Stop viewing as ${actingAs}`} onClick={onStop}>
        Stop
      </Button>
    </div>
  );
}
