import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockFetch } from "../test/fetch";
import { Environments } from "./Environments";
import { Services } from "./Services";
import { Usage } from "./Usage";

afterEach(() => vi.unstubAllGlobals());

describe("work pages on the kit", () => {
  it("Services shows an empty state and a loading skeleton first", async () => {
    mockFetch({ "GET /api/jobs": { body: { jobs: [] } } });
    render(<Services />);
    expect(screen.getByRole("status", { name: "Loading services" })).toBeInTheDocument();
    expect(await screen.findByText("You have no sessions running")).toBeInTheDocument();
  });

  it("Services shows health as a status badge", async () => {
    mockFetch({
      "GET /api/jobs": { body: { jobs: [{ job_id: "1", kind: "notebook", state: "RUNNING", name: "nb",
        user: "a", pods: 1, time_used: "0:01", time_limit: "1:00:00", time_left_s: 9 }] } },
      "GET /api/jobs/1": { body: { state: "RUNNING", kind: "notebook",
        session: { kind: "notebook", ready: true, open_url: "/n/" } } },
    });
    render(<Services />);
    expect(await screen.findByText("Running")).toBeInTheDocument();
  });

  it("Environments shows an error with Retry, then the lists", async () => {
    mockFetch({ "GET /api/envs": { status: 500, body: {} } });
    render(<Environments />);
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
    mockFetch({ "GET /api/envs": { body: { prebuilt: [], mine: [], images: [], builds: [] } } });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect((await screen.findAllByText("None yet")).length).toBe(3);
  });

  it("Usage shows an error with Retry and stat tiles when loaded", async () => {
    mockFetch({ "GET /api/usage?days=30": { status: 500, body: {} } });
    render(<Usage />);
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
    mockFetch({ "GET /api/usage?days=30": { body: { gpu_hours: 2, cpu_hours: 4, jobs_by_state: { COMPLETED: 1 } } } });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("group", { name: "GPU-hours" })).toBeInTheDocument();
  });
});
