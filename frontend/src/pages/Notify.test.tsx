import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Notify } from "./Notify";

vi.mock("../api/newjob", () => ({
  newjob: { notify: () => Promise.resolve({ wanted_pods: null }), setNotify: vi.fn(), stopNotify: vi.fn() },
}));

describe("Notify", () => {
  beforeEach(() => vi.clearAllMocks());

  it("aligns the pods box and the button on one line", async () => {
    render(<Notify />);
    const box = await screen.findByLabelText("Pods wanted");
    const button = screen.getByRole("button", { name: "Notify me" });
    expect(box.className).toContain("h-10");
    expect(button.className).toContain("h-10");
    expect(box.className).not.toContain("mb-3");
    expect(box.closest("div")?.className).toContain("items-end");
  });
});
