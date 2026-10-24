import "./styles/index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { Panel } from "./components/Panel";
import { Wordmark } from "./components/Wordmark";

// The app shell and routes arrive with SLURM-17; until then this is a holding page.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <main className="mx-auto max-w-md p-8">
      <Wordmark className="text-3xl" />
      <Panel className="mt-6" title="Coming soon">
        <p className="text-text-dim">The web platform is being built.</p>
      </Panel>
    </main>
  </StrictMode>,
);
