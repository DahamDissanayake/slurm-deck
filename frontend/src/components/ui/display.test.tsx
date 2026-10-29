import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FolderIcon, GpuIcon } from "../icons";
import { Card } from "./Card";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { Meter } from "./Meter";
import { Skeleton } from "./Skeleton";
import { Spinner } from "./Spinner";
import { StatTile } from "./StatTile";

describe("Card", () => {
  it("is a region named by its title, with an icon and an actions slot", () => {
    render(<Card title="Hardware" icon={<GpuIcon />} actions={<button>Refresh</button>}>body</Card>);
    const card = screen.getByRole("region", { name: "Hardware" });
    expect(card.querySelector("svg")).not.toBeNull();
    expect(card).toContainElement(screen.getByRole("button", { name: "Refresh" }));
    expect(card).toHaveTextContent("body");
  });

  it("works without a header", () => {
    render(<Card>only body</Card>);
    expect(screen.queryByRole("heading")).toBeNull();
    expect(screen.getByText("only body")).toBeInTheDocument();
  });
});

describe("Meter", () => {
  it("exposes its value as a meter, as a bar or a ring", () => {
    render(<><Meter label="GPU memory" value={30} max={60} /><Meter kind="ring" label="Time left" value={5} /></>);
    const bar = screen.getByRole("meter", { name: "GPU memory" });
    expect(bar).toHaveAttribute("aria-valuenow", "30");
    expect(bar).toHaveAttribute("aria-valuemax", "60");
    expect(bar.querySelector("[style]")).toHaveStyle({ width: "50%" });
    expect(screen.getByRole("meter", { name: "Time left" }).querySelector("circle")).not.toBeNull();
  });

  it("turns warning then danger as it fills, and clamps", () => {
    const { container } = render(<><Meter label="a" value={50} /><Meter label="b" value={80} /><Meter label="c" value={140} /></>);
    const fills = container.querySelectorAll("[data-fill]");
    expect(fills[0]).toHaveClass("bg-accent");
    expect(fills[1]).toHaveClass("bg-warning");
    expect(fills[2]).toHaveClass("bg-danger");
    expect(fills[2]).toHaveStyle({ width: "100%" });
  });
});

describe("StatTile", () => {
  it("shows icon, value, label and sub-text, with an optional meter", () => {
    render(<StatTile icon={<GpuIcon />} label="GPU utilisation" value="72%" sub="8 GPUs" meter={{ value: 72 }} />);
    const tile = screen.getByRole("group", { name: "GPU utilisation" });
    expect(tile).toHaveTextContent("72%");
    expect(tile).toHaveTextContent("8 GPUs");
    expect(screen.getByRole("meter", { name: "GPU utilisation" })).toHaveAttribute("aria-valuenow", "72");
  });
});

describe("loading", () => {
  it("Spinner is announced, and only animates when motion is allowed", () => {
    render(<Spinner />);
    const s = screen.getByRole("status", { name: "Loading" });
    expect(s.getAttribute("class")).toContain("motion-safe:animate-spin");
    expect(s.getAttribute("class")).not.toMatch(/(^|\s)animate-spin/);
  });

  it("Skeleton draws lines, tiles or rows behind one loading status", () => {
    const { container } = render(<Skeleton variant="row" count={4} label="Loading files" />);
    expect(screen.getByRole("status", { name: "Loading files" })).toBeInTheDocument();
    const bones = container.querySelectorAll("[data-bone]");
    expect(bones).toHaveLength(4);
    expect(bones[0].className).toContain("motion-safe:animate-shimmer");
  });
});

describe("EmptyState and ErrorState", () => {
  it("EmptyState shows an icon, one line and an action", () => {
    render(<EmptyState icon={<FolderIcon />} title="This folder is empty" action={<button>Upload files</button>} />);
    expect(screen.getByRole("heading", { name: "This folder is empty" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload files" })).toBeInTheDocument();
  });

  it("ErrorState says what failed and retries", () => {
    const retry = vi.fn();
    render(<ErrorState title="Couldn't load your files" error={new Error("Network down")} onRetry={retry} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Couldn't load your files");
    expect(alert).toHaveTextContent("Network down");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("ErrorState shows a spinner on Retry while retrying", () => {
    render(<ErrorState title="Failed" onRetry={() => {}} retrying />);
    expect(screen.getByRole("button", { name: "Retry" })).toBeDisabled();
  });
});
