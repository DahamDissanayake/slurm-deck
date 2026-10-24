import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LaunchSpec } from "../../api/newjob";
import { mockFetch } from "../../test/fetch";
import { Notify } from "../Notify";
import { NewJob } from "./index";
import { StepReview } from "./StepReview";

afterEach(() => vi.unstubAllGlobals());

const SPEC: LaunchSpec = {
  intent: "batch", script: "/shared/users/amasha/train.py", env_kind: "prebuilt",
  conda_env: "", venv_path: "", container_image: "", gpu_shards: 1, cpus: 8, mem_gb: 14,
  time_limit: "08:00:00", data_path: "", model_path: "", args: "", array: "",
  dependency: "", mail: true, requirements: "", packages: "", port: 8888,
};
const QOS = { max_wall_s: 8 * 3600, max_pods_per_user: 4 };
const STATUS = { body: { pods_total: 4, pods_used: 2, node: null } };

function defaults(terminal = true) {
  return { body: { spec: SPEC, qos: QOS, terminal_enabled: terminal } };
}

describe("StepReview", () => {
  it("keeps Submit disabled while the preview reports a problem", async () => {
    const problem = "The script must be under /shared/users/amasha.";
    mockFetch({
      "GET /api/cluster/status": STATUS,
      "POST /api/jobs/preview": { body: { script: "#!/bin/bash", problems: [problem],
                                          warnings: [] } },
    });
    render(<StepReview spec={SPEC} qos={QOS} onChange={() => {}} onBack={() => {}} />);
    expect(await screen.findByText(problem)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit job" })).toBeDisabled();
  });

  it("shows the QoS problem when the time limit is over the maximum", async () => {
    mockFetch({
      "GET /api/cluster/status": STATUS,
      "POST /api/jobs/preview": { body: { script: "", problems: [], warnings: [] } },
    });
    render(<StepReview spec={{ ...SPEC, time_limit: "12:00:00" }} qos={QOS}
                       onChange={() => {}} onBack={() => {}} />);
    expect(await screen.findByText("Requested 12:00:00 exceeds the QOS wall-time limit of 8h."))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit job" })).toBeDisabled();
  });

  it("shows pod availability", async () => {
    mockFetch({
      "GET /api/cluster/status": STATUS,
      "POST /api/jobs/preview": { body: { script: "", problems: [], warnings: [] } },
    });
    render(<StepReview spec={SPEC} qos={QOS} onChange={() => {}} onBack={() => {}} />);
    expect(await screen.findByText("2 of 4 free")).toBeInTheDocument();
  });
});

describe("NewJob", () => {
  it("hides the Terminal intent when terminal jobs are turned off", async () => {
    mockFetch({ "GET /api/jobs/defaults?intent=batch": defaults(false),
                "GET /api/templates": { body: { presets: [], templates: [] } } });
    render(<NewJob />);
    expect(await screen.findByRole("button", { name: /Script/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Terminal/ })).toBeNull();
  });

  it("shows the Terminal intent when it is enabled", async () => {
    mockFetch({ "GET /api/jobs/defaults?intent=batch": defaults(true),
                "GET /api/templates": { body: { presets: [], templates: [] } } });
    render(<NewJob />);
    expect(await screen.findByRole("button", { name: /Terminal/ })).toBeInTheDocument();
  });

  it("fills args and pods from a template", async () => {
    mockFetch({
      "GET /api/jobs/defaults?intent=batch": defaults(),
      "GET /api/templates": { body: { presets: [], templates: [
        { id: 4, name: "llama", spec: { ...SPEC, args: "--epochs 9", gpu_shards: 3 } }] } },
      "GET /api/cluster/status": STATUS,
      "POST /api/jobs/preview": { body: { script: "", problems: [], warnings: [] } },
    });
    render(<NewJob />);
    fireEvent.change(await screen.findByLabelText("Start from a template"),
                     { target: { value: "4" } });
    expect(await screen.findByLabelText("Arguments")).toHaveValue("--epochs 9");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByLabelText("Pods")).toHaveTextContent("3");
  });
});

describe("Notify", () => {
  it("shows the current subscription and removes it", async () => {
    const calls = mockFetch({ "GET /api/notify": { body: { wanted_pods: 2 } },
                              "DELETE /api/notify": { body: {} } });
    render(<Notify />);
    expect(await screen.findByText(/when 2 pods are free/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    await vi.waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });
});
