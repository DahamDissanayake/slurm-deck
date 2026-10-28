import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { QueueJob } from "../api/jobs";
import { backoff } from "../api/live";
import { mockFetch } from "../test/fetch";
import { ExtendDialog } from "./ExtendDialog";
import { JobCard } from "./JobCard";
import { PodBlocks } from "./PodBlocks";

afterEach(() => vi.unstubAllGlobals());

const JOB: QueueJob = { job_id: "512", name: "train_1", state: "RUNNING", user: "amasha",
                        pods: 2, time_used: "1:00:00", time_limit: "8:00:00",
                        time_left_s: 25200 };

describe("ExtendDialog", () => {
  it("shows the server's over-cap refusal verbatim", async () => {
    const msg = "This would take the job to 12 h; the limit is 8 h.";
    mockFetch({ "POST /api/jobs/512/extend": { status: 422, body: { error: "over_cap",
                                                                       message: msg } } });
    render(<ExtendDialog jobId="512" onClose={() => {}} onDone={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "+4 h" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(msg);
  });

  it("sends the chosen hours", async () => {
    const calls = mockFetch({ "POST /api/jobs/512/extend": { body: { new_limit_s: 36000 } } });
    const done = vi.fn();
    render(<ExtendDialog jobId="512" onClose={() => {}} onDone={done} />);
    fireEvent.click(screen.getByRole("button", { name: "+2 h" }));
    await vi.waitFor(() => expect(done).toHaveBeenCalled());
    expect(JSON.parse(calls[0].body!)).toEqual({ hours: 2 });
  });
});

describe("JobCard", () => {
  it("offers Extend and Cancel for a running job", () => {
    render(<JobCard job={JOB} />);
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Extend…" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("hides Extend and Cancel once the job has ended", () => {
    render(<JobCard job={{ ...JOB, state: "COMPLETED" }} />);
    expect(screen.getByText("Ended")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Extend…" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
    expect(screen.getByRole("link", { name: "Rerun" })).toBeInTheDocument();
  });
});

describe("PodBlocks", () => {
  it("draws one block per pod and labels the count", () => {
    render(<PodBlocks used={3} total={8} />);
    expect(screen.getByRole("img", { name: "3 of 8 pods in use" }).children).toHaveLength(8);
  });
});

describe("live reconnect backoff", () => {
  it("doubles from 1 s and caps at 30 s", () => {
    expect([0, 1, 2, 3, 4, 5, 6, 20].map(backoff))
      .toEqual([1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000]);
  });
});
