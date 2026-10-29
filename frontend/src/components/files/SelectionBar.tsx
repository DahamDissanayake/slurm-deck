import { XIcon } from "../icons";
import { Button } from "../ui/Button";
import { IconButton } from "../ui/IconButton";
import type { FileAction, FileHandlers } from "./actions";

/** What is selected, and what can be done to all of it. */
export function SelectionBar({ count, actions, handlers, onClear }: {
  count: number; actions: FileAction[]; handlers: FileHandlers; onClear: () => void;
}) {
  return (
    <div role="toolbar" aria-label="Selection"
         className="mb-3 flex flex-wrap items-center gap-2 rounded-lg bg-accent-soft px-3 py-2">
      <IconButton label="Clear selection" icon={<XIcon />} size="sm" tooltipSide="bottom" onClick={onClear} />
      <span className="mr-2 text-md font-medium text-text">{count} selected</span>
      {actions.map((a) => (
        <Button key={a.id} variant={a.danger ? "danger" : "secondary"} size="sm" pill icon={a.icon}
                onClick={handlers[a.id]}>
          {a.label}
        </Button>
      ))}
    </div>
  );
}
