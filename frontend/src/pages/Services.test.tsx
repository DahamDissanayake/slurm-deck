import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockFetch } from "../test/fetch";
import { Services } from "./Services";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const job = (job_id: string, kind: string, state = "RUNNING") =>
  ({ job_id, kind, state, name: `${kind}-${job_id}`, user: "amasha", pods: 1,
     time_used: "0:10", time_limit: "8:00:00", time_left_s: 100 });
const up = (kind: string, ready = true) => ({ body: { state: "RUNNING", kind, session: {
  kind, ready, open_url: ready ? `/${kind}/x/` : null } } });

describe("Services", () => {
  it("lists only notebook, TensorBoard and terminal jobs", async () => {
    mockFetch({
      "GET /api/jobs": { body: { jobs: [job("1", "notebook"), job("2", "batch"),
                                         job("3", "tensorboard"), job("4", "smoke"),
                                         job("5", "terminal")] } },
      "GET /api/jobs/1": up("notebook"), "GET /api/jobs/3": up("tensorboard"),
      "GET /api/jobs/5": up("terminal"),
    });
    render(<Services />);
    expect(await screen.findByText("notebook-1")).toBeInTheDocument();
    expect(screen.getByText("tensorboard-3")).toBeInTheDocument();
    expect(screen.getByText("terminal-5")).toBeInTheDocument();
    expect(screen.queryByText("batch-2")).toBeNull();
    expect(screen.queryByText("smoke-4")).toBeNull();
  });

  it("stops a session only after confirmation", async () => {
    const calls = mockFetch({
      "GET /api/jobs": { body: { jobs: [job("1", "notebook")] } },
      "GET /api/jobs/1": up("notebook"), "POST /api/jobs/1/cancel": { body: {} },
    });
    const ask = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    render(<Services />);
    const row = (await screen.findByText("notebook-1")).closest("li") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Stop" }));
    expect(calls.some((c) => c.path.endsWith("/cancel"))).toBe(false);
    fireEvent.click(within(row).getByRole("button", { name: "Stop" }));
    await vi.waitFor(() => expect(calls.some((c) => c.path === "/api/jobs/1/cancel")).toBe(true));
    expect(ask).toHaveBeenCalledTimes(2);
  });

  it("starts TensorBoard on the chosen folder", async () => {
    const spec = { intent: "tensorboard", data_path: "" };
    const calls = mockFetch({
      "GET /api/jobs": { body: { jobs: [] } },
      "GET /api/files/roots": { body: { roots: [{ label: "My files", path: "/shared/users/amasha",
                                                  writable: true }] } },
      "GET /api/files?path=%2Fshared%2Fusers%2Famasha": { body: { entries: [] } },
      "GET /api/jobs/defaults?intent=tensorboard": { body: { spec, qos: {}, terminal_enabled: true } },
      "POST /api/jobs": { status: 201, body: { job_id: "9" } },
    });
    render(<Services />);
    fireEvent.click(await screen.findByRole("button", { name: "Start TensorBoard" }));
    fireEvent.click(await screen.findByRole("button", { name: "Choose" }));
    await vi.waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/api/jobs"))
      .toBe(true));
    const sent = JSON.parse(calls.find((c) => c.method === "POST" && c.path === "/api/jobs")?.body ?? "{}");
    expect(sent).toMatchObject({ intent: "tensorboard", data_path: "/shared/users/amasha" });
  });
});
