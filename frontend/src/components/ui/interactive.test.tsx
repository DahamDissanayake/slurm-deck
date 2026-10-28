import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Button } from "./Button";
import { Menu } from "./Menu";
import { SegmentedControl } from "./SegmentedControl";
import { ToastProvider, useToast } from "./Toast";
import { Tooltip } from "./Tooltip";

describe("Tooltip", () => {
  it("describes its child on hover and hides on Escape", () => {
    render(<Tooltip content="Opens in a new tab"><button>Open</button></Tooltip>);
    const button = screen.getByRole("button", { name: "Open" });
    fireEvent.mouseEnter(button.parentElement!);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Opens in a new tab");
    expect(button.parentElement).toHaveAttribute("aria-describedby", screen.getByRole("tooltip").id);
    fireEvent.keyDown(button, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});

describe("Menu", () => {
  const setup = () => {
    const logs = vi.fn();
    const cancel = vi.fn();
    render(<Menu label="Job actions" items={[
      { label: "Logs", onSelect: logs },
      { label: "Extend", onSelect: () => {}, disabled: true },
      { label: "Cancel job", onSelect: cancel, danger: true },
    ]} />);
    return { logs, cancel, trigger: screen.getByRole("button", { name: "Job actions" }) };
  };

  it("opens from an accessible trigger and runs the chosen item", () => {
    const { trigger, cancel } = setup();
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByRole("menuitem")).toHaveLength(3);
    fireEvent.click(screen.getByRole("menuitem", { name: "Cancel job" }));
    expect(cancel).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("moves with the arrow keys past disabled items and closes on Escape", () => {
    const { trigger, logs } = setup();
    fireEvent.click(trigger);
    const menu = screen.getByRole("menu");
    expect(screen.getByRole("menuitem", { name: "Logs" })).toHaveFocus();
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(screen.getByRole("menuitem", { name: "Cancel job" })).toHaveFocus();
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(screen.getByRole("menuitem", { name: "Logs" })).toHaveFocus();
    fireEvent.keyDown(menu, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(trigger).toHaveFocus();
    expect(logs).not.toHaveBeenCalled();
  });

  it("closes on a click outside", () => {
    const { trigger } = setup();
    fireEvent.click(trigger);
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu")).toBeNull();
  });
});

describe("SegmentedControl", () => {
  function Filter() {
    const [v, setV] = useState("all");
    return <SegmentedControl label="Show jobs" value={v} onChange={setV}
      options={[{ value: "all", label: "All" }, { value: "running", label: "Running" }, { value: "done", label: "Finished" }]} />;
  }

  it("is a radio group with one checked option and arrow-key movement", () => {
    render(<Filter />);
    expect(screen.getByRole("radiogroup", { name: "Show jobs" })).toBeInTheDocument();
    const all = screen.getByRole("radio", { name: "All" });
    expect(all).toHaveAttribute("aria-checked", "true");
    expect(all).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("radio", { name: "Running" })).toHaveAttribute("tabindex", "-1");
    fireEvent.click(screen.getByRole("radio", { name: "Finished" }));
    expect(screen.getByRole("radio", { name: "Finished" })).toHaveAttribute("aria-checked", "true");
    fireEvent.keyDown(screen.getByRole("radio", { name: "Finished" }), { key: "ArrowRight" });
    expect(screen.getByRole("radio", { name: "All" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "All" })).toHaveFocus();
  });
});

describe("Toast", () => {
  afterEach(() => vi.useRealTimers());

  function Saver() {
    const toast = useToast();
    return <Button onClick={() => toast({ tone: "ok", message: "Job cancelled" })}>Cancel job</Button>;
  }

  it("announces an action result, then dismisses itself or on close", () => {
    vi.useFakeTimers();
    render(<ToastProvider><Saver /></ToastProvider>);
    const region = screen.getByRole("region", { name: "Notifications" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel job" }));
    expect(screen.getByRole("status")).toHaveTextContent("Job cancelled");
    act(() => { vi.advanceTimersByTime(6000); });
    expect(region).not.toHaveTextContent("Job cancelled");

    fireEvent.click(screen.getByRole("button", { name: "Cancel job" }));
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(region).not.toHaveTextContent("Job cancelled");
  });

  it("errors are announced assertively", () => {
    function Failer() {
      const toast = useToast();
      return <Button onClick={() => toast({ tone: "danger", message: "Couldn't cancel the job" })}>Go</Button>;
    }
    render(<ToastProvider><Failer /></ToastProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Go" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't cancel the job");
  });
});
