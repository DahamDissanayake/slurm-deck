import { AlertIcon, RefreshIcon } from "../icons";
import { Button } from "./Button";
import { cx } from "./cx";
import { stateIcon } from "./EmptyState";

const message = (error: unknown) =>
  error instanceof Error ? error.message : typeof error === "string" ? error : null;

/** What failed, why if known, and a Retry button. */
export function ErrorState({ title, error, onRetry, retrying = false, className }: {
  title: string; error?: unknown; onRetry?: () => void; retrying?: boolean; className?: string;
}) {
  const detail = message(error);
  return (
    <div role="alert" className={cx("flex flex-col items-center gap-3 px-6 py-12 text-center", className)}>
      <span aria-hidden="true" className={cx(stateIcon, "bg-danger-soft text-danger")}><AlertIcon /></span>
      <h3 className="text-base font-semibold text-text">{title}</h3>
      {detail && <p className="max-w-sm break-words text-md text-text-dim">{detail}</p>}
      {onRetry && (
        <Button variant="secondary" icon={<RefreshIcon />} loading={retrying} onClick={onRetry} className="mt-1">
          Retry
        </Button>
      )}
    </div>
  );
}
