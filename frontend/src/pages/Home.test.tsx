import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { QueueJob } from "../api/jobs";
import type { Live } from "../api/live";
import { mockFetch } from "../test/fetch";
import { Home } from "./Home";

const live = vi.hoisted(() => ({ value: null as unknown as Live }));
vi.mock("../api/live", () => ({ useLive: () => live.value }));

afterEach(() => vi.unstubAllGlobals());

const NODE = { state: "MIXED", cpu_util: 40, cpu_total: 32, mem_used_mb: 20480, mem_total_mb: 131072,
               gpu_util: 55, gpu_mem_used_mb: 8192, gpu_mem_total_mb: 24576, gpu_temp: 61,
               gpu_power_w: 180, shard_total: 8, shard_alloc: 3, live_stats: true };
const status = (node: object | null) => ({ body: { node, pods_total: 8, pods_used: 3 } });

const job = (over: Partial<QueueJob> = {}): QueueJob => ({
  job_id: "512", name: "train_1", state: "RUNNING", user: "amasha", pods: 2,
  time_used: "1:00:00", time_limit: "8:00:00", time_left_s: 25200, ...over,
});

beforeEach(() => {
  live.value = {
    connected: true, jobs: [job()], banners: [],
    cluster: { node: NODE, pods_total: 8, pods_used: 3, disk: null, maintenance: null,
               queue: [job(), job({ job_id: "9", user: "kasun", name: undefined }),
                       job({ job_id: "10", user: "nimal", state: "PENDING", time_left_s: null })] },
  };
});

const tile = (name: string) => screen.getByRole("group", { name });

describe("Home stat tiles", () => {
  it("renders GPU, CPU, RAM and pods tiles from live data", () => {
    mockFetch({ "GET /api/cluster/status": status(NODE) });
    render(<Home />);
    expect(tile("GPU utilisation")).toHaveTextContent("55%");
    expect(tile("GPU memory")).toHaveTextContent("8.0 GB");
    expect(tile("GPU memory")).toHaveTextContent("of 24.0 GB");
    expect(tile("CPU load")).toHaveTextContent("40%");
    expect(tile("RAM")).toHaveTextContent("20.0 GB");
    expect(tile("Pods free")).toHaveTextContent("5");
    expect(tile("Pods free")).toHaveTextContent("of 8");
    expect(tile("In the queue")).toHaveTextContent("1");
  });

  it("shows skeletons until the cluster reports, and dashes without live stats", () => {
    mockFetch({ "GET /api/cluster/status": status(NODE) });
    live.value = { ...live.value, cluster: null };
    const { unmount } = render(<Home />);
    expect(screen.getByRole("status", { name: "Loading the cluster" })).toBeInTheDocument();
    unmount();

    live.value = { ...live.value, cluster: { ...live.value.cluster!, node: { ...NODE, live_stats: false } } };
    render(<Home />);
    expect(tile("GPU utilisation")).toHaveTextContent("—");
    expect(tile("Pods free")).toHaveTextContent("5");
  });
});

describe("Home hardware and cluster cards", () => {
  it("shows meters, temperature and power from the cluster status", async () => {
    mockFetch({ "GET /api/cluster/status": status(NODE) });
    render(<Home />);
    const card = screen.getByRole("region", { name: "Hardware" });
    expect(await within(card).findByText("61 °C")).toBeInTheDocument();
    expect(within(card).getByText("180 W")).toBeInTheDocument();
    expect(within(card).getByRole("meter", { name: "GPU memory" })).toHaveAttribute("aria-valuenow", "8192");
  });

  it("shows an error with Retry when the status can't be loaded, and reloads on Retry", async () => {
    const calls = mockFetch({});
    render(<Home />);
    const card = screen.getByRole("region", { name: "Hardware" });
    fireEvent.click(await within(card).findByRole("button", { name: "Retry" }));
    await vi.waitFor(() => expect(calls.filter((c) => c.path === "/api/cluster/status").length).toBeGreaterThan(1));
  });

  it("lists health checks as badges and who is running", async () => {
    mockFetch({ "GET /api/cluster/status": status({ ...NODE, live_stats: false }) });
    render(<Home />);
    const cluster = screen.getByRole("region", { name: "Cluster" });
    const row = async (label: string) => (await within(cluster).findByText(label)).closest("li") as HTMLElement;
    expect(await row("Scheduler")).toHaveTextContent("Ready");
    expect(await row("Live stats")).toHaveTextContent("Stale");
    expect(within(cluster).getByText("amasha")).toBeInTheDocument();
    expect(within(cluster).getByText("kasun")).toBeInTheDocument();
    expect(within(cluster).queryByText("nimal")).not.toBeInTheDocument();
    expect(within(cluster).getByRole("meter", { name: "Time left for job 512" })).toBeInTheDocument();
  });
});

describe("Home my jobs", () => {
  it("shows each job with a status badge and icon actions", () => {
    mockFetch({ "GET /api/cluster/status": status(NODE) });
    render(<Home />);
    const jobs = screen.getByRole("region", { name: "My jobs" });
    expect(within(jobs).getByText("Running")).toBeInTheDocument();
    expect(within(jobs).getByRole("link", { name: "Logs" })).toHaveAttribute("href", "/jobs/512");
    expect(within(jobs).getByRole("button", { name: "Extend time" })).toBeInTheDocument();
    expect(within(jobs).getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(within(jobs).getByRole("link", { name: "Rerun" })).toHaveAttribute("href", "/new?rerun=512");
  });

  it("offers to start a job when there are none, and skeletons while loading", () => {
    mockFetch({ "GET /api/cluster/status": status(NODE) });
    live.value = { ...live.value, jobs: [] };
    const { unmount } = render(<Home />);
    expect(screen.getByText("No jobs yet")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "My jobs" })).getByRole("link", { name: "Start a job" }))
      .toHaveAttribute("href", "/new");
    unmount();
    live.value = { ...live.value, jobs: null };
    render(<Home />);
    expect(screen.getByRole("status", { name: "Loading your jobs" })).toBeInTheDocument();
  });

  it("shows expiry warnings and maintenance as notices", () => {
    mockFetch({ "GET /api/cluster/status": status(NODE) });
    live.value = { ...live.value, banners: [{ job_id: "512", minutes_left: 10 }],
                   cluster: { ...live.value.cluster!, maintenance: "Disk swap tonight" } };
    render(<Home />);
    expect(screen.getByRole("alert")).toHaveTextContent("Job 512 ends in 10 minutes");
    expect(screen.getByText("Disk swap tonight")).toBeInTheDocument();
  });

  it("has quick actions", () => {
    mockFetch({ "GET /api/cluster/status": status(NODE) });
    render(<Home />);
    const quick = screen.getByRole("navigation", { name: "Quick actions" });
    expect(within(quick).getByRole("link", { name: "New job" })).toHaveAttribute("href", "/new");
    expect(within(quick).getByRole("link", { name: "Upload files" })).toHaveAttribute("href", "/files");
    expect(within(quick).getByRole("link", { name: "Notebooks and services" })).toHaveAttribute("href", "/services");
  });
});
