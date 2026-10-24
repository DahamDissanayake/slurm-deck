import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Wordmark } from "./Wordmark";

describe("Wordmark", () => {
  it("renders > SLURM in text colour and DECK in the accent", () => {
    render(<Wordmark />);
    expect(screen.getByText("> SLURM")).toHaveClass("text-text");
    expect(screen.getByText("DECK")).toHaveClass("text-accent");
    expect(screen.getByLabelText("Slurm Deck")).toHaveClass("font-mono");
  });
});
