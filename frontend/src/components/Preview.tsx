import { useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { files, IMAGE, type PreviewData } from "../api/files";
import { Skeleton } from "./ui/Skeleton";

/** An image, the first rows of a CSV/TSV, or the start of a text file. */
export function Preview({ path }: { path: string }) {
  const image = IMAGE.test(path);
  const [data, setData] = useState<PreviewData | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setData(null);
    setError("");
    if (image) return;
    files.preview(path).then(setData, (e) =>
      setError(e instanceof ApiError && e.message ? e.message : "There's no preview for this file."));
  }, [path, image]);

  if (image) return <img src={files.previewUrl(path)} alt={path} className="max-h-96 max-w-full rounded-md" />;
  if (error) return <p className="text-md text-text-dim">{error}</p>;
  if (!data) return <Skeleton count={4} label="Loading the preview" />;
  if (data.kind === "table") {
    return (
      <div className="max-h-96 overflow-auto rounded-md border border-border">
        <table className="font-mono text-xs">
          <tbody>
            {data.rows.map((r, i) => (
              <tr key={i}>{r.map((c, j) => <td key={j} className="border border-border px-1.5 py-0.5">{c}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return (
    <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-bg p-3 font-mono text-xs">
      {data.text}{data.truncated && "\n…"}
    </pre>
  );
}
