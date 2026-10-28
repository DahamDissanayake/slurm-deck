import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Live } from "../api/live";
import { AppShell } from "./AppShell";

const auth = vi.hoisted(() => ({
  me: { account: { role: "user", full_name: "Amasha Perera" }, acting_as: null as null | { username: string } },
  signOut: vi.fn(() => Promise.resolve()),
  stopViewing: vi.fn(() => Promise.resolve()),
}));
vi.mock("../api/auth", () => ({
  getMe: () => Promise.resolve(auth.me),
  signOut: auth.signOut,
  stopViewing: auth.stopViewing,
}));

const live = vi.hoisted(() => ({
  value: { connected: true, cluster: null, jobs: null, banners: [] } as Live,
}));
vi.mock("../api/live", () => ({ useLive: () => live.value }));

const USER_NAV = ["Dashboard", "New job", "Jobs", "Files", "Environments", "Models", "Services", "Usage", "Notify"];

const cluster = (over: Partial<NonNullable<Live["cluster"]>> = {}) => ({
  node: null, pods_total: 8, pods_used: 3, queue: [], disk: null, maintenance: null, ...over,
});

async function shell() {
  const view = render(<AppShell>body</AppShell>);
  await screen.findByText("body");
  return view;
}

beforeEach(() => {
  window.localStorage.clear();
  window.history.pushState({}, "", "/");
  auth.me = { account: { role: "user", full_name: "Amasha Perera" }, acting_as: null };
  live.value = { connected: true, cluster: cluster(), jobs: null, banners: [] };
});
afterEach(() => vi.clearAllMocks());

describe("icon rail", () => {
  it("shows every nav item as an icon link with an accessible name", async () => {
    await shell();
    const rail = screen.getByRole("navigation", { name: "Main" });
    const links = within(rail).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual(USER_NAV);
    for (const link of links) expect(link.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(within(rail).queryByRole("link", { name: "Admin" })).not.toBeInTheDocument();
  });

  it("adds Admin for admins", async () => {
    auth.me = { account: { role: "admin", full_name: "Root Admin" }, acting_as: null };
    await shell();
    const rail = screen.getByRole("navigation", { name: "Main" });
    expect(within(rail).getByRole("link", { name: "Admin" })).toHaveAttribute("href", "/admin");
  });

  it("marks the current page", async () => {
    window.history.pushState({}, "", "/jobs/42");
    await shell();
    const rail = screen.getByRole("navigation", { name: "Main" });
    expect(within(rail).getByRole("link", { name: "Jobs" })).toHaveAttribute("aria-current", "page");
    expect(within(rail).getByRole("link", { name: "Dashboard" })).not.toHaveAttribute("aria-current");
  });

  it("shows a tooltip with the label while collapsed", async () => {
    await shell();
    const files = within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: "Files" });
    fireEvent.mouseEnter(files.parentElement!);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Files");
  });

  it("expands to labels and remembers the choice across reloads", async () => {
    const first = await shell();
    const expand = screen.getByRole("button", { name: "Expand sidebar" });
    expect(expand).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(expand);
    expect(screen.getByRole("button", { name: "Collapse sidebar" })).toHaveAttribute("aria-expanded", "true");
    first.unmount();

    await shell();
    expect(screen.getByRole("button", { name: "Collapse sidebar" })).toBeInTheDocument();
    const files = within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: "Files" });
    fireEvent.mouseEnter(files.parentElement!);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("still works when storage is blocked", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    await shell();
    fireEvent.click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(screen.getByRole("button", { name: "Collapse sidebar" })).toBeInTheDocument();
    vi.restoreAllMocks();
  });
});

describe("mobile drawer", () => {
  it("opens from the menu button, and closes on Escape or after navigating", async () => {
    await shell();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    const drawer = screen.getByRole("dialog", { name: "Menu" });
    const nav = within(drawer).getByRole("navigation", { name: "Main menu" });
    expect(within(nav).getAllByRole("link").map((l) => l.textContent)).toEqual(USER_NAV);
    expect(within(nav).getByRole("link", { name: "Dashboard" })).toHaveFocus();
    fireEvent.keyDown(drawer, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    fireEvent.click(within(screen.getByRole("navigation", { name: "Main menu" })).getByRole("link", { name: "Files" }));
    expect(window.location.pathname).toBe("/files");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("top bar", () => {
  it("shows the page title, and breadcrumbs below the top level", async () => {
    await shell();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Dashboard");
    expect(screen.queryByRole("navigation", { name: "Breadcrumb" })).not.toBeInTheDocument();

    act(() => { window.history.pushState({}, "", "/files/data/run%201"); window.dispatchEvent(new PopStateEvent("popstate")); });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Files");
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Files" })).toHaveAttribute("href", "/files");
    expect(within(crumbs).getByRole("link", { name: "data" })).toHaveAttribute("href", "/files/data");
    expect(within(crumbs).getByText("run 1")).toHaveAttribute("aria-current", "page");
  });

  it("names the account and usage pages", async () => {
    window.history.pushState({}, "", "/account/password");
    await shell();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Change password");
  });

  it("shows cluster health as a chip", async () => {
    const view = await shell();
    expect(screen.getByTestId("cluster-chip")).toHaveTextContent("5 of 8 pods free");
    live.value = { ...live.value, cluster: cluster({ maintenance: "Disk swap" }) };
    view.rerender(<AppShell>body</AppShell>);
    expect(screen.getByTestId("cluster-chip")).toHaveTextContent("Maintenance");
    live.value = { ...live.value, connected: false };
    view.rerender(<AppShell>body</AppShell>);
    expect(screen.getByTestId("cluster-chip")).toHaveTextContent("Offline");
  });

  it("has the theme toggle as a named icon button", async () => {
    await shell();
    const theme = screen.getByRole("button", { name: /theme$/ });
    expect(theme.querySelector("svg")).not.toBeNull();
  });

  it("puts View-as in an inline pill with Stop, not a strip", async () => {
    auth.me = { ...auth.me, acting_as: { username: "kasun" } };
    await shell();
    const pill = screen.getByRole("status");
    expect(pill).toHaveTextContent("Viewing as kasun");
    expect(screen.getByRole("banner")).toContainElement(pill);
    fireEvent.click(within(pill).getByRole("button", { name: "Stop viewing as kasun" }));
    expect(auth.stopViewing).toHaveBeenCalled();
  });
});

describe("user menu", () => {
  it("opens from the initials and offers change password, About and sign out", async () => {
    await shell();
    const trigger = screen.getByRole("button", { name: "Account: Amasha Perera" });
    expect(trigger).toHaveTextContent("AP");
    fireEvent.click(trigger);
    const menu = screen.getByRole("menu");
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent))
      .toEqual(["Change password", "About", "Sign out"]);
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Change password" }));
    expect(window.location.pathname).toBe("/account/password");

    fireEvent.click(screen.getByRole("button", { name: "Account: Amasha Perera" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "About" }));
    expect(window.location.pathname).toBe("/about");
  });

  it("signs out and goes to the sign-in page", async () => {
    await shell();
    fireEvent.click(screen.getByRole("button", { name: "Account: Amasha Perera" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    expect(auth.signOut).toHaveBeenCalled();
    await vi.waitFor(() => expect(window.location.pathname).toBe("/sign-in"));
  });
});
