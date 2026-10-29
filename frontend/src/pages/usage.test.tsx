import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockFetch } from "../test/fetch";
import { UsageAdmin } from "./admin/UsageAdmin";
import { Usage } from "./Usage";

afterEach(() => vi.unstubAllGlobals());

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
    expect(await screen.findByText("2.0 KB")).toBeInTheDocument();
  });
});
