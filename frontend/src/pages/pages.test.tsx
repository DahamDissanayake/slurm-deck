import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeToggle } from "../app/ThemeToggle";
import { ViewAsBanner } from "../app/ViewAsBanner";
import { mockFetch } from "../test/fetch";
import { SetPassword } from "./SetPassword";
import { SignIn } from "./SignIn";

beforeEach(() => window.history.pushState({}, "", "/sign-in"));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  delete document.documentElement.dataset.theme;
});

describe("SignIn", () => {
  it("hides Apply for access when apply-open is false", async () => {
    mockFetch({ "GET /api/public/apply-open": { body: { open: false } } });
    render(<SignIn />);
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    await screen.findByText("Forgot password");
    expect(screen.queryByText("Apply for access")).not.toBeInTheDocument();
  });

  it("offers the hosts-file line when the name may not resolve", async () => {
    mockFetch({ "GET /api/public/apply-open": { body: { open: false } },
                "GET /api/public/site": { body: { hostname: "slurmdeck.local", lan_addr: "10.35.4.100" } } });
    render(<SignIn />);
    expect(await screen.findByText("Can't reach slurmdeck.local?")).toBeInTheDocument();
    expect(screen.getByText("10.35.4.100 slurmdeck.local")).toBeInTheDocument();
  });

  it("puts the session hostname on the same hosts-file line", async () => {
    mockFetch({ "GET /api/public/apply-open": { body: { open: false } },
                "GET /api/public/site": { body: { hostname: "slurmdeck.local", lan_addr: "10.35.4.100",
                                                  session_hostname: "sessions.slurmdeck.local" } } });
    render(<SignIn />);
    expect(await screen.findByText("10.35.4.100 slurmdeck.local sessions.slurmdeck.local"))
      .toBeInTheDocument();
  });

  it("shows no hint when the address isn't configured", async () => {
    mockFetch({ "GET /api/public/apply-open": { body: { open: false } },
                "GET /api/public/site": { body: { hostname: "slurmdeck.local", lan_addr: "" } } });
    render(<SignIn />);
    await screen.findByText("Forgot password");
    expect(screen.queryByText(/Can't reach/)).not.toBeInTheDocument();
  });

  it("shows Apply when open, and bad_credentials as plain words", async () => {
    mockFetch({
      "GET /api/public/apply-open": { body: { open: true } },
      "POST /api/auth/login": { status: 401, body: { error: "bad_credentials" } },
    });
    render(<SignIn />);
    expect(await screen.findByText("Apply for access")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@x.org" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "nope" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That email and password don't match.");
  });
});

describe("ThemeToggle", () => {
  it("sets data-theme and survives a throwing localStorage", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: /theme$/ })).toHaveAttribute("title");
    fireEvent.click(screen.getByRole("button"));
    const first = document.documentElement.dataset.theme;
    expect(["light", "dark"]).toContain(first);
    fireEvent.click(screen.getByRole("button"));
    expect(document.documentElement.dataset.theme).not.toBe(first);
  });
});

describe("ViewAsBanner", () => {
  it("renders only while viewing as someone", () => {
    const { rerender } = render(<ViewAsBanner actingAs={null} onStop={() => {}} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    const stop = vi.fn();
    rerender(<ViewAsBanner actingAs="amasha" onStop={stop} />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Viewing as amasha — every action is recorded.");
    fireEvent.click(screen.getByRole("button", { name: "Stop viewing" }));
    expect(stop).toHaveBeenCalled();
  });
});

describe("SetPassword", () => {
  it("reads the token from the fragment, never the query string", async () => {
    window.history.pushState({}, "", "/set-password?token=fromquery#token=fromhash");
    const calls = mockFetch({ "POST /api/auth/password/set": { body: { csrf_token: "c" } } });
    render(<SetPassword />);
    for (const label of ["New password", "Repeat it"]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value: "a long passphrase!" } });
    }
    fireEvent.click(screen.getByRole("button", { name: "Set password" }));
    await vi.waitFor(() => expect(calls).toHaveLength(1));
    expect(JSON.parse(calls[0].body!)).toEqual({ token: "fromhash",
                                                 password: "a long passphrase!" });
  });
});
