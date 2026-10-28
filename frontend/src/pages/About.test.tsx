import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import pkg from "../../package.json";
import { About } from "./About";
import { PublicPage } from "./PublicPage";

let me: "in" | "out" = "out";   // a plain function: a spy would flag the 401 as unhandled
vi.mock("../api/auth", () => ({
  getMe: () => (me === "in" ? Promise.resolve({ account: { role: "user" } }) : Promise.reject(new Error("401"))),
}));

describe("About", () => {
  beforeEach(() => { me = "out"; });

  it("renders signed out, with a way to sign in", async () => {
    render(<About />);
    expect(await screen.findByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/sign-in");
    expect(screen.queryByRole("link", { name: "Back to dashboard" })).not.toBeInTheDocument();
  });

  it("offers the dashboard when signed in", async () => {
    me = "in";
    render(<About />);
    expect(await screen.findByRole("link", { name: "Back to dashboard" })).toHaveAttribute("href", "/");
  });

  it("names the people, the repo and the version", async () => {
    render(<About />);
    expect(screen.getByText("Daham Dissanayake")).toBeInTheDocument();
    const sup = screen.getByRole("link", { name: "@indrajithek" });
    expect(sup).toHaveAttribute("href", "https://github.com/indrajithek");
    expect(sup).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
    expect(screen.getByRole("link", { name: "@DahamDissanayake" }))
      .toHaveAttribute("href", "https://github.com/DahamDissanayake");
    expect(screen.getByRole("link", { name: /github.com\/DahamDissanayake\/slurm-deck/ }))
      .toHaveAttribute("href", "https://github.com/DahamDissanayake/slurm-deck/");
    expect(screen.getByText((t) => t.includes(`v${pkg.version}`))).toBeInTheDocument();
    expect(screen.getByText(/IIT research unit/)).toBeInTheDocument();
    expect(screen.getByText(/v1\.4/)).toBeInTheDocument();
    await screen.findByRole("link", { name: "Sign in" });
  });
});

describe("PublicPage footer", () => {
  it("links to About", () => {
    render(<PublicPage title="Sign in">x</PublicPage>);
    expect(screen.getByRole("link", { name: "About" })).toHaveAttribute("href", "/about");
  });
});
