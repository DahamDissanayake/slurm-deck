import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockFetch } from "../test/fetch";
import { ForgotPassword } from "./ForgotPassword";
import { SignIn } from "./SignIn";

afterEach(() => vi.unstubAllGlobals());

describe("public pages", () => {
  it("sign-in uses the kit Button and shows its loading state while signing in", async () => {
    mockFetch({
      "GET /api/public/apply-open": { body: { open: false } },
      "POST /api/auth/login": { status: 401, body: { error: "bad_credentials" } },
    });
    render(<SignIn />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@x.org" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "nope" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(screen.getByRole("button", { name: /Sign in/ })).toHaveAttribute("aria-busy", "true");
    expect(await screen.findByRole("alert")).toHaveTextContent("don't match");
    expect(screen.getByRole("button", { name: "Sign in" })).not.toHaveAttribute("aria-busy");
  });

  it("forgot-password shows the inline success message", async () => {
    mockFetch({ "POST /api/auth/forgot": { body: {} } });
    render(<ForgotPassword />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@x.org" } });
    fireEvent.click(screen.getByRole("button", { name: "Send reset link" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("reset link is on its way");
  });
});
