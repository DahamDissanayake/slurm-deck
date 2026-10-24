/** The product wordmark, as on the TUI splash: `> SLURM` then `DECK` in the accent. */
export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span aria-label="Slurm Deck" className={`font-mono font-bold tracking-wide ${className}`}>
      <span className="text-text">{"> SLURM"}</span> <span className="text-accent">DECK</span>
    </span>
  );
}
