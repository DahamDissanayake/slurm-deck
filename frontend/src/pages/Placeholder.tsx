import { Panel } from "../components/Panel";

/** A page that later phases build. */
export function Placeholder({ title }: { title: string }) {
  return (
    <Panel title={title}>
      <p className="text-text-dim">This page is coming soon.</p>
    </Panel>
  );
}
