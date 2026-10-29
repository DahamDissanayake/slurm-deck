import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Notice } from "./Notice";
import { Tabs } from "./Tabs";

const TABS = [{ value: "a", label: "Overview" }, { value: "b", label: "Logs" }, { value: "c", label: "Script" }];

describe("Tabs", () => {
  it("is a tablist with the chosen tab selected, linked to its panel", () => {
    render(<Tabs label="Job sections" tabs={TABS} value="b" onChange={() => {}}>panel body</Tabs>);
    expect(screen.getByRole("tablist", { name: "Job sections" })).toBeInTheDocument();
    const logs = screen.getByRole("tab", { name: "Logs" });
    expect(logs).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", logs.id);
    expect(logs).toHaveAttribute("aria-controls", screen.getByRole("tabpanel").id);
  });

  it("changes on click and moves with the arrow keys, Home and End", () => {
    const onChange = vi.fn();
    render(<Tabs label="Job sections" tabs={TABS} value="a" onChange={onChange}>x</Tabs>);
    fireEvent.click(screen.getByRole("tab", { name: "Script" }));
    expect(onChange).toHaveBeenLastCalledWith("c");
    fireEvent.keyDown(screen.getByRole("tab", { name: "Overview" }), { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith("b");
    fireEvent.keyDown(screen.getByRole("tab", { name: "Overview" }), { key: "ArrowLeft" });
    expect(onChange).toHaveBeenLastCalledWith("c");
    fireEvent.keyDown(screen.getByRole("tab", { name: "Overview" }), { key: "End" });
    expect(onChange).toHaveBeenLastCalledWith("c");
    fireEvent.keyDown(screen.getByRole("tab", { name: "Script" }), { key: "Home" });
    expect(onChange).toHaveBeenLastCalledWith("a");
  });
});

describe("Notice", () => {
  it("says it with an icon and text, as a status or an alert", () => {
    const { rerender } = render(<Notice>Disk swap tonight</Notice>);
    expect(screen.getByRole("status")).toHaveTextContent("Disk swap tonight");
    expect(screen.getByRole("status").querySelector("svg")).not.toBeNull();
    rerender(<Notice tone="danger" alert>Job failed</Notice>);
    expect(screen.getByRole("alert")).toHaveTextContent("Job failed");
  });
});
