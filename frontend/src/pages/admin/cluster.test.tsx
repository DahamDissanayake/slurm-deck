import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockFetch } from "../../test/fetch";
import { Cluster } from "./Cluster";
import { JobsAdmin } from "./JobsAdmin";
import { SharedAssets } from "./SharedAssets";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const QOS = { name: "normal", max_wall_s: 28800, max_pods_per_user: 4, max_gpus_per_user: 10,
              priority: 10 };
const PODS = { pods_total: 3, pods: [{ pod: 0, job_id: "101", user: "amasha" },
                                      { pod: 1, job_id: null, user: null },
                                      { pod: 2, job_id: null, user: null }],
               fits: [{ n: 1, ok: true, message: "" },
                      { n: 2, ok: false, message: "2 pods leave no memory for a pod." }] };
const cluster = (extra = {}) => mockFetch({
  "GET /api/admin/qos": { body: { qos: [QOS] } },
  "POST /api/admin/node/jobs": { body: { jobs: [{ job_id: "101", user: "amasha", name: "t", state: "RUNNING" }] } },
  "GET /api/admin/pods": { body: PODS },
  "GET /api/admin/service-status": { body: { login: { slurmctld: "active", mariadb: "failed" },
                                              gpu: { slurmd: "active" }, gpu_error: "" } },
  ...extra,
});

describe("Cluster", () => {
  it("changes one QOS limit and sends only that field", async () => {
    const calls = cluster({ "POST /api/admin/qos": { body: {} } });
    render(<Cluster />);
    const box = await screen.findByLabelText("normal max_pods_per_user");
    fireEvent.change(box, { target: { value: "6" } });
    fireEvent.click(within(box.closest("tr") as HTMLElement).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(calls.filter((c) => c.path === "/api/admin/qos"
      && c.method === "POST")).toHaveLength(1));
    const sent = JSON.parse(calls.find((c) => c.method === "POST" && c.path === "/api/admin/qos")?.body ?? "{}");
    expect(sent).toEqual({ name: "normal", field: "max_pods_per_user", value: 6 });
  });

  it("will not drain without a reason, and asks before cancelling jobs", async () => {
    const calls = cluster({ "POST /api/admin/node/drain": { body: { cancelled: ["101"] } } });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<Cluster />);
    const drain = await screen.findByRole("button", { name: "Drain" });
    expect(drain).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "driver update" } });
    fireEvent.click(screen.getByLabelText(/Cancel running jobs/));
    fireEvent.click(drain);
    await vi.waitFor(() => expect(calls.some((c) => c.path === "/api/admin/node/drain")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.path === "/api/admin/node/drain")?.body ?? "{}"))
      .toEqual({ reason: "driver update", cancel_running: true });
  });

  it("shows the pod grid and shows a refused resize in the server's words", async () => {
    cluster({ "POST /api/admin/pods/resize": {
      status: 409, body: { error: "queue_busy", message: "2 job(s) are still active." } } });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<Cluster />);
    const grid = await screen.findByLabelText("Pod grid");
    await vi.waitFor(() => expect(within(grid).getAllByTitle(/./)).toHaveLength(3));
    expect(within(grid).getByTitle("Job 101 (amasha)")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Resize" }));
    expect(await screen.findByText("2 job(s) are still active.")).toBeInTheDocument();
  });

  it("marks a service that is down", async () => {
    cluster();
    render(<Cluster />);
    expect(await screen.findByText(/mariadb: failed/)).toBeInTheDocument();
  });
});

describe("SharedAssets", () => {
  it("shows the refusal when the name is taken, then publishes with Replace", async () => {
    const taken = { status: 409, body: { error: "exists", message: "A file with that name already exists there." } };
    const calls = mockFetch({ "POST /api/admin/shared/publish": taken });
    render(<SharedAssets />);
    fireEvent.change(screen.getAllByRole("textbox")[0], { target: { value: "/shared/users/amasha/llama" } });
    fireEvent.change(screen.getAllByRole("textbox")[1], { target: { value: "llama" } });
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    expect(await screen.findByText("A file with that name already exists there.")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/Replace it/));
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    await vi.waitFor(() => expect(calls.filter((c) => c.method === "POST")).toHaveLength(2));
    expect(JSON.parse(calls[1].body ?? "{}")).toMatchObject({ area: "models", name: "llama", replace: true });
  });
});

describe("JobsAdmin", () => {
  it("lists everyone's jobs with names and cancels one after asking", async () => {
    const job = (id: string, user: string) => ({ job_id: id, user, name: `job-${id}`, state: "RUNNING",
                                                 pods: 1, time_used: "0:10", time_limit: "8:00:00" });
    const calls = mockFetch({
      "GET /api/cluster/queue": { body: { jobs: [job("1", "amasha"), job("2", "hassan")] } },
      "POST /api/jobs/2/cancel": { body: {} },
    });
    const ask = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<JobsAdmin />);
    const row = (await screen.findByText("job-2")).closest("tr") as HTMLElement;
    expect(screen.getByText("job-1")).toBeInTheDocument();
    fireEvent.click(within(row).getByRole("button", { name: "Cancel" }));
    await vi.waitFor(() => expect(calls.some((c) => c.path === "/api/jobs/2/cancel")).toBe(true));
    expect(ask).toHaveBeenCalledTimes(1);
  });
});
