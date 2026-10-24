import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Panel } from "./Panel";

describe("Panel", () => {
  it("renders its title and children under a double-ruled top border", () => {
    render(<Panel title="Sign in">body text</Panel>);
    const panel = screen.getByRole("region", { name: "Sign in" });
    expect(panel).toHaveClass("border-t-4", "border-double");
    expect(panel).toHaveTextContent("body text");
  });

  it("works without a title", () => {
    render(<Panel>only body</Panel>);
    expect(screen.getByText("only body")).toBeInTheDocument();
  });
});
