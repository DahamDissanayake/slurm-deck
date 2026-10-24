import { useEffect, useState } from "react";

import { ApiError } from "../api/client";
import { files, IMAGE, type PreviewData } from "../api/files";

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

  if (image) return <img src={files.previewUrl(path)} alt={path} className="max-h-96" />;
  if (error) return <p className="text-text-dim">{error}</p>;
  if (!data) return <p className="text-text-dim">Loading…</p>;
  if (data.kind === "table") {
    return (
      <div className="max-h-96 overflow-auto">
        <table className="font-mono text-xs">
          <tbody>
            {data.rows.map((r, i) => (
              <tr key={i}>{r.map((c, j) => <td key={j} className="border border-border px-1">{c}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return (
    <pre className="max-h-96 overflow-auto whitespace-pre-wrap font-mono text-xs">
      {data.text}{data.truncated && "\n…"}
    </pre>
  );
}
