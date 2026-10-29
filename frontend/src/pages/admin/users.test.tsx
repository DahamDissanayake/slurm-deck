import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockFetch } from "../../test/fetch";
import { AppAccess } from "./AppAccess";
import { Users } from "./Users";

afterEach(() => vi.unstubAllGlobals());

const row = (id: number, username: string, status: string) => ({
  id, username, full_name: username, email: `${username}@x.org`, role: "user", status, last_login_at: null });

describe("Users", () => {
  it("shows a status badge per user and filters with the search box", async () => {
    const calls = mockFetch({
      "GET /api/admin/accounts": { body: { accounts: [row(1, "amy", "active"), row(2, "bob", "suspended")] } },
      "GET /api/admin/accounts?q=bob": { body: { accounts: [row(2, "bob", "suspended")] } },
    });
    render(<Users />);
    expect(await screen.findByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Suspended")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "bob" } });
    await vi.waitFor(() => expect(screen.queryByText("amy")).toBeNull());
    expect(calls.some((c) => c.path.includes("q=bob"))).toBe(true);
  });
});

describe("AppAccess", () => {
  it("shows an empty state when the allow-list is empty", async () => {
    mockFetch({ "GET /api/admin/allowlist": { body: { entries: [] } } });
    render(<AppAccess />);
    expect(await screen.findByText("No allowed domains or emails")).toBeInTheDocument();
  });
});
