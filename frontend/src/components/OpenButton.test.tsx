import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockFetch } from "../test/fetch";
import { OpenButton } from "./OpenButton";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const session = (ready: boolean) => ({ body: { session: {
  kind: "notebook", ready, open_url: ready ? "/notebook/42/lab" : null } } });

describe("OpenButton", () => {
  it("is disabled and says Starting… until the session is ready", async () => {
    mockFetch({ "GET /api/jobs/42": session(false) });
    render(<OpenButton jobId="42" />);
    const button = await screen.findByRole("button", { name: "Starting…" });
    expect(button).toBeDisabled();
  });

  it("opens the session in a new tab once it is ready", async () => {
    mockFetch({ "GET /api/jobs/42": session(true) });
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<OpenButton jobId="42" />);
    const button = await screen.findByRole("button", { name: "Open" });
    await vi.waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    expect(open).toHaveBeenCalledWith("/notebook/42/lab", "_blank", "noopener");
  });
});
