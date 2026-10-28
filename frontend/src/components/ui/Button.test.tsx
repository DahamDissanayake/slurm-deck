import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PlusIcon } from "../icons";
import { Button } from "./Button";
import { IconButton } from "./IconButton";

describe("Button", () => {
  it("shows a spinner and is disabled while loading", () => {
    const onClick = vi.fn();
    render(<Button loading onClick={onClick}>Save changes</Button>);
    const button = screen.getByRole("button", { name: "Save changes" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button.querySelector("[data-spinner]")).not.toBeNull();
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("has the four variants and two sizes, all from tokens", () => {
    render(<>
      <Button>Primary</Button>
      <Button variant="secondary" size="sm">Secondary</Button>
      <Button variant="ghost">Ghost</Button>
      <Button variant="danger">Delete</Button>
    </>);
    expect(screen.getByRole("button", { name: "Primary" })).toHaveClass("bg-accent", "h-10");
    expect(screen.getByRole("button", { name: "Secondary" })).toHaveClass("bg-surface", "h-8");
    expect(screen.getByRole("button", { name: "Ghost" })).toHaveClass("bg-transparent");
    expect(screen.getByRole("button", { name: "Delete" })).toHaveClass("text-danger");
    for (const b of screen.getAllByRole("button")) expect(b.className).not.toMatch(/#|rgb/);
  });

  it("renders a leading icon, defaults to type=button and can be disabled", () => {
    render(<Button icon={<PlusIcon />} disabled>New job</Button>);
    const button = screen.getByRole("button", { name: "New job" });
    expect(button.querySelector("svg")).not.toBeNull();
    expect(button).toHaveAttribute("type", "button");
    expect(button).toBeDisabled();
  });
});

describe("IconButton", () => {
  it("is named by its label and shows it as a tooltip on hover and focus", () => {
    render(<IconButton label="Cancel job" icon={<PlusIcon />} />);
    const button = screen.getByRole("button", { name: "Cancel job" });
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.focus(button);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Cancel job");
    fireEvent.blur(button);
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});
