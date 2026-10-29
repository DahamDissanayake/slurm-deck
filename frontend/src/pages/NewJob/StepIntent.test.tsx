import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StepIntent } from "./StepIntent";

describe("StepIntent", () => {
  it("shows each intent as an icon card button", () => {
    const onPick = vi.fn();
    render(<StepIntent terminalEnabled templates={[]} busy={false} onPick={onPick} onTemplate={vi.fn()} />);
    for (const name of ["Notebook", "Script", "Terminal session", "Smoke test"]) {
      const card = screen.getByRole("button", { name: new RegExp(name) });
      expect(card.querySelector("svg")).not.toBeNull();
    }
    fireEvent.click(screen.getByRole("button", { name: /Notebook/ }));
    expect(onPick).toHaveBeenCalledWith("notebook");
  });

  it("hides the terminal card when terminals are off", () => {
    render(<StepIntent terminalEnabled={false} templates={[]} busy={false} onPick={vi.fn()} onTemplate={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Terminal session/ })).toBeNull();
  });
});
