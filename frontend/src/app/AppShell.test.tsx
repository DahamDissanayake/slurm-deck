import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AppShell } from "./AppShell";

vi.mock("../api/auth", () => ({
  getMe: () => Promise.resolve({ account: { role: "user", full_name: "Amasha Perera" }, acting_as: null }),
  signOut: () => Promise.resolve(),
  stopViewing: () => Promise.resolve(),
}));

describe("AppShell top bar", () => {
  it("shows the name as text and the other actions as named icons", async () => {
    render(<AppShell>body</AppShell>);
    expect(await screen.findByText("Amasha Perera")).toBeInTheDocument();
    const about = screen.getByRole("link", { name: "About" });
    expect(about).toHaveAttribute("href", "/about");
    const pw = screen.getByRole("link", { name: "Change password" });
    expect(pw).toHaveAttribute("href", "/account/password");
    expect(pw).toHaveAttribute("title", "Change password");
    const out = screen.getByRole("button", { name: "Sign out" });
    expect(out).toHaveAttribute("title", "Sign out");
    expect(out.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("button", { name: /theme$/ }).querySelector("svg")).not.toBeNull();
  });
});
