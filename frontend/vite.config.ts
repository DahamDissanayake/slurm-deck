import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  // The API is served by the same origin behind Caddy; in dev, proxy it.
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    // tokens.test.ts reads the stylesheet's text; other CSS stays stubbed out.
    css: { include: [/tokens\.css/] },
  },
});
