import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockFetch } from "../test/fetch";
import { UsageAdmin } from "./admin/UsageAdmin";
import { ClusterStatus } from "./ClusterStatus";
import { Hardware } from "./Hardware";
import { Usage } from "./Usage";

afterEach(() => vi.unstubAllGlobals());

const NODE = { state: "MIXED", cpu_util: 40, cpu_total: 32, mem_used_mb: 20480, mem_total_mb: 131072,
               gpu_util: 55, gpu_mem_used_mb: 8192, gpu_mem_total_mb: 24576, gpu_temp: 61,
               gpu_power_w: 180, shard_total: 8, shard_alloc: 3, live_stats: true };
const status = (node: object | null) => ({ body: { node, pods_total: 8, pods_used: 3,
                                                    partition_max_s: 86400 } });
const queue = { body: { jobs: [{ state: "RUNNING" }, { state: "RUNNING" }, { state: "PENDING" }] } };

function check(label: string) {
  return screen.getByText(label).closest("li") as HTMLElement;
}

describe("ClusterStatus", () => {
  it("shows Stats fresh as No when the node reports no live stats", async () => {
    mockFetch({ "GET /api/cluster/status": status({ ...NODE, live_stats: false }),
                "GET /api/cluster/queue": queue });
    render(<ClusterStatus />);
    await screen.findByText("Jobs running");
    expect(check("Stats fresh")).toHaveAttribute("data-ok", "false");
    expect(check("GPU node up")).toHaveAttribute("data-ok", "true");
    expect(check("Scheduler reachable")).toHaveAttribute("data-ok", "true");
  });

  it("shows Stats fresh as Yes with live stats, and counts running and waiting jobs", async () => {
    mockFetch({ "GET /api/cluster/status": status(NODE), "GET /api/cluster/queue": queue });
    render(<ClusterStatus />);
    await screen.findByText("Jobs running");
    expect(check("Stats fresh")).toHaveAttribute("data-ok", "true");
    expect(screen.getByText("Jobs running").nextSibling).toHaveTextContent("2");
    expect(screen.getByText("Jobs waiting").nextSibling).toHaveTextContent("1");
    expect(screen.getByText("Pods in use").nextSibling).toHaveTextContent("3 of 8");
  });

});

describe("Hardware", () => {
  it("shows the node's GPU, memory, temperature and power", async () => {
    mockFetch({ "GET /api/cluster/status": status(NODE) });
    render(<Hardware />);
    expect(await screen.findByText("55%")).toBeInTheDocument();
    expect(screen.getByText("8.0 GB of 24.0 GB")).toBeInTheDocument();
    expect(screen.getByText("61 °C")).toBeInTheDocument();
    expect(screen.getByText("180 W")).toBeInTheDocument();
  });

});

describe("Usage", () => {
  it("shows my three numbers and reloads for another period", async () => {
    const calls = mockFetch({
      "GET /api/usage?days=30": { body: { days: 30, pods_total: 8, gpu_hours: 1.5, cpu_hours: 26,
                                          jobs_by_state: { COMPLETED: 2, FAILED: 1 } } },
      "GET /api/usage?days=7": { body: { days: 7, pods_total: 8, gpu_hours: 0.5, cpu_hours: 4,
                                         jobs_by_state: { COMPLETED: 1 } } },
    });
    render(<Usage />);
    expect(await screen.findByText("1.5")).toBeInTheDocument();
    expect(screen.getByText("26.0")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("FAILED: 1")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Period"), { target: { value: "7" } });
    expect(await screen.findByText("0.5")).toBeInTheDocument();
    expect(calls.map((c) => c.path)).toContain("/api/usage?days=7");
  });
});

describe("UsageAdmin", () => {
  it("lists users by GPU-hours, re-sorts by name, and shows disk use of both trees", async () => {
    const totals = (g: number, c: number) => ({ gpu_hours: g, cpu_hours: c,
                                                 jobs_by_state: { COMPLETED: 1 } });
    mockFetch({
      "GET /api/admin/usage?days=30": { body: { days: 30, pods_total: 8, total: totals(3.5, 40),
        users: [{ user: "hassan", ...totals(2, 10) }, { user: "amasha", ...totals(1.5, 30) }] } },
      "GET /api/admin/disk-usage": { body: { total_bytes: 1350, users: [
        { user: "amasha", bytes: 2048, users_bytes: 1024, jobs_bytes: 1024 }] } },
    });
    render(<UsageAdmin />);
    const usageTable = (await screen.findByText("Everyone")).closest("table") as HTMLElement;
    const names = () => within(usageTable).getAllByRole("row").slice(1, -1)
      .map((r) => within(r).getAllByRole("cell")[0].textContent);
    expect(names()).toEqual(["hassan", "amasha"]);
    fireEvent.click(screen.getByRole("button", { name: /^User/ }));
    expect(names()).toEqual(["amasha", "hassan"]);
    const diskRow = (await screen.findByText("2.0 KB")).closest("tr") as HTMLElement;
    expect(within(diskRow).getAllByText("1.0 KB")).toHaveLength(2);
  });
});
