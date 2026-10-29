import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockFetch } from "../test/fetch";
import { JobDetail } from "./JobDetail";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const INFO = { owner: "amasha", state: "RUNNING", time_limit_s: 28800, run_time_s: 3600, node: "gpu01",
               exit_code: "0:0", work_dir: "/shared/users/amasha", kind: "batch",
               folder: "/shared/users/amasha/jobs/512", script: "#!/bin/bash\necho hi", explanation: null,
               session: null };
const serve = (text: string) => vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
  const path = String(input);
  if (path.includes("/log")) return new Response(text, { headers: { "X-SD-Size": String(text.length) } });
  return new Response(JSON.stringify(INFO), { headers: { "Content-Type": "application/json" } });
}));

describe("JobDetail", () => {
  it("has a header with the state and icon actions, and tabs for Overview, Logs and Script", async () => {
    serve("line one");
    render(<JobDetail id="512" />);
    expect(await screen.findByRole("heading", { name: "Job 512" })).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Extend time" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel job" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Rerun" })).toHaveAttribute("href", "/new?rerun=512");
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Overview", "Logs", "Script"]);
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("gpu01")).toBeInTheDocument();
    expect(screen.getByText("/shared/users/amasha/jobs/512")).toBeInTheDocument();
  });

  it("shows the log and the script on their own tabs", async () => {
    serve("epoch 1 done");
    render(<JobDetail id="512" />);
    fireEvent.click(await screen.findByRole("tab", { name: "Logs" }));
    expect(await screen.findByText(/epoch 1 done/)).toBeInTheDocument();
    expect(screen.getByRole("radiogroup", { name: "Log stream" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute("download", "job-512.out.log");
    fireEvent.click(screen.getByRole("tab", { name: "Script" }));
    expect(screen.getByText(/echo hi/)).toBeInTheDocument();
  });

  it("hides the Script tab when there is no script, and the live actions once ended", async () => {
    mockFetch({ "GET /api/jobs/9": { body: { ...INFO, state: "FAILED", script: null,
                                              explanation: "It ran out of memory." } } });
    render(<JobDetail id="9" />);
    expect(await screen.findByText("Failed")).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Script" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancel job" })).toBeNull();
    expect(screen.getByRole("note")).toHaveTextContent("It ran out of memory.");
  });

  it("shows skeletons while loading and an error with Retry when the job can't be loaded", async () => {
    const calls = mockFetch({});
    render(<JobDetail id="404" />);
    expect(screen.getByRole("status", { name: "Loading the job" })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    await vi.waitFor(() => expect(calls.length).toBeGreaterThan(1));
  });
});
