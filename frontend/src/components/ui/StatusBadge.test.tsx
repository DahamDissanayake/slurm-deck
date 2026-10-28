import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { JOB_STATES, SERVICE_STATES, StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it.each([...JOB_STATES, ...SERVICE_STATES])("renders an icon and a text label for %s", (state) => {
    const { container } = render(<StatusBadge state={state} />);
    const badge = container.firstElementChild as HTMLElement;
    expect(badge.querySelector("svg")).not.toBeNull();
    expect(badge.textContent?.trim()).not.toBe("");
  });

  it("covers every Slurm job state and systemd service state", () => {
    for (const s of ["PENDING", "RUNNING", "COMPLETED", "FAILED", "TIMEOUT", "CANCELLED",
      "OUT_OF_MEMORY", "NODE_FAIL", "PREEMPTED", "SUSPENDED"]) expect(JOB_STATES).toContain(s);
    for (const s of ["active", "inactive", "failed", "activating"]) expect(SERVICE_STATES).toContain(s);
  });

  it("uses plain words and reads Slurm's 'CANCELLED by 1000' as cancelled", () => {
    render(<><StatusBadge state="PENDING" /><StatusBadge state="CANCELLED by 1000" /></>);
    expect(screen.getByText("Queued")).toBeInTheDocument();
    expect(screen.getByText("Cancelled")).toBeInTheDocument();
  });

  it("pulses only while running, and only when motion is allowed", () => {
    const { container } = render(<StatusBadge state="RUNNING" />);
    const dot = container.querySelector("[data-pulse]");
    expect(dot?.getAttribute("class")).toContain("motion-safe:animate-pulse-soft");
    render(<StatusBadge state="COMPLETED" />);
    expect(document.querySelectorAll("[data-pulse]")).toHaveLength(1);
  });

  it("falls back to the raw state for one it does not know", () => {
    render(<StatusBadge state="WEIRD_STATE" />);
    expect(screen.getByText("Weird state")).toBeInTheDocument();
  });
});
