import { useSession } from "../api/sessions";
import { ExternalIcon } from "./icons";
import { Button } from "./ui/Button";

/** Opens a notebook, TensorBoard or terminal in a new tab. Disabled, and
 * saying "Starting…", until the session is ready. */
export function OpenButton({ jobId }: { jobId: string }) {
  const session = useSession(jobId);
  const url = session?.ready ? session.open_url : null;
  return (
    <Button variant="secondary" size="sm" pill icon={<ExternalIcon />} disabled={!url}
            onClick={() => url && window.open(url, "_blank", "noopener")}>
      {url ? "Open" : "Starting…"}
    </Button>
  );
}
