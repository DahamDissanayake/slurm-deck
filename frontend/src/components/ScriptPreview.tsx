/** The generated sbatch script, read-only and shown as plain text. */
export function ScriptPreview({ script }: { script: string }) {
  return (
    <pre aria-label="Script preview"
         className="max-h-96 overflow-auto rounded-sm border border-border bg-bg p-3 font-mono text-xs">
      {script || "The script appears here once the inputs are complete."}
    </pre>
  );
}
