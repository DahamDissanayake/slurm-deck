import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { QueueJob } from "../api/jobs";
import type { Live } from "../api/live";
import { mockFetch } from "../test/fetch";
import { Jobs } from "./Jobs";

const live = vi.hoisted(() => ({ value: null as unknown as Live }));
vi.mock("../api/live", () => ({ useLive: () => live.value }));

afterEach(() => vi.unstubAllGlobals());

const job = (over: Partial<QueueJob> = {}): QueueJob => ({
  job_id: "512", name: "train_1", state: "RUNNING", user: "amasha", pods: 2,
  time_used: "1:00:00", time_limit: "8:00:00", time_left_s: 25200, ...over,
});
const MINE = job();
const OTHER = job({ job_id: "9", name: undefined, user: "kasun", state: "RUNNING" });
const WAITING = job({ job_id: "10", name: undefined, user: "nimal", state: "PENDING", time_left_s: null });

beforeEach(() => {
  live.value = { connected: true, banners: [], jobs: [MINE],
                 cluster: { node: null, pods_total: 8, pods_used: 3, disk: null, maintenance: null,
                            queue: [MINE, OTHER, WAITING] } };
});

describe("Jobs filter", () => {
  it("is a segmented control, and every row shows a status badge", () => {
    mockFetch({});
    render(<Jobs />);
    const filter = screen.getByRole("radiogroup", { name: "Filter jobs" });
    expect(within(filter).getAllByRole("radio").map((r) => r.textContent))
      .toEqual(["All", "Running", "Pending", "Finished"]);
    expect(within(filter).getByRole("radio", { name: "All" })).toHaveAttribute("aria-checked", "true");
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByText("Running")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Queued")).toBeInTheDocument();
  });

  it("narrows the queue to running or pending jobs", () => {
    mockFetch({});
    render(<Jobs />);
    fireEvent.click(screen.getByRole("radio", { name: "Pending" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText("nimal")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Running" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("limits the list to my jobs with the scope control, with actions on my live jobs", () => {
    mockFetch({});
    render(<Jobs />);
    fireEvent.click(screen.getByRole("radio", { name: "Mine" }));
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(1);
    expect(within(rows[0]).getByRole("link", { name: "Logs" })).toHaveAttribute("href", "/jobs/512");
    expect(within(rows[0]).getByRole("link", { name: "Rerun" })).toHaveAttribute("href", "/new?rerun=512");
    fireEvent.click(within(rows[0]).getByRole("button", { name: "More actions for job 512" }));
    expect(screen.getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["Extend time", "Cancel job"]);
  });

  it("shows no actions on other people's jobs", () => {
    mockFetch({});
    render(<Jobs />);
    const other = screen.getByText("kasun").closest("li") as HTMLElement;
    expect(within(other).queryByRole("link")).toBeNull();
    expect(within(other).queryByRole("button")).toBeNull();
  });

  it("says when nothing matches", () => {
    mockFetch({});
    live.value = { ...live.value, cluster: { ...live.value.cluster!, queue: [] } };
    render(<Jobs />);
    expect(screen.getByText("No jobs here")).toBeInTheDocument();
  });

  it("shows skeleton rows until the queue arrives", () => {
    mockFetch({});
    live.value = { ...live.value, cluster: null };
    render(<Jobs />);
    expect(screen.getByRole("status", { name: "Loading jobs" })).toBeInTheDocument();
  });
});

describe("Jobs finished", () => {
  const finished = (state: string) => ({ body: { jobs: [job({ job_id: "300", state, time_left_s: null })] } });

  it("loads my history for the chosen period and offers Rerun", async () => {
    const calls = mockFetch({ "GET /api/jobs/history?days=30": finished("COMPLETED"),
                              "GET /api/jobs/history?days=7": finished("FAILED") });
    render(<Jobs />);
    fireEvent.click(screen.getByRole("radio", { name: "Finished" }));
    expect(await screen.findByText("Completed")).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: "Whose jobs" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Period"), { target: { value: "7" } });
    expect(await screen.findByText("Failed")).toBeInTheDocument();
    expect(calls.map((c) => c.path)).toContain("/api/jobs/history?days=7");
    expect(screen.getByRole("link", { name: "Rerun" })).toHaveAttribute("href", "/new?rerun=300");
  });

  it("shows an error with Retry instead of an empty list when history fails", async () => {
    const calls = mockFetch({});
    render(<Jobs />);
    fireEvent.click(screen.getByRole("radio", { name: "Finished" }));
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    await vi.waitFor(() => expect(calls.length).toBeGreaterThan(1));
  });
});
