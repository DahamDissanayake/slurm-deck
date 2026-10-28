import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockFetch } from "../test/fetch";
import { Environments } from "./Environments";

afterEach(() => vi.unstubAllGlobals());

const ENVS = { body: {
  prebuilt: [{ name: "vision", path: "/shared/envs/vision", kind: "prebuilt", ready: true,
               missing: [] }],
  mine: [{ name: "mytorch", path: "/shared/users/a/envs/mytorch", kind: "mine", ready: false,
           missing: ["torch"] }],
  images: [{ name: "pytorch.sif", path: "/shared/images/pytorch.sif", kind: "image",
             ready: true }],
  builds: [{ job_id: "700", kind: "build", name: "mytorch", path: "/x", state: "failed",
             missing: ["torch"] }],
} };

describe("Environments", () => {
  it("lists all three kinds and shows a failed build's missing packages", async () => {
    mockFetch({ "GET /api/envs": ENVS });
    render(<Environments />);
    expect(await screen.findByText("vision")).toBeInTheDocument();
    expect(screen.getByText("pytorch.sif")).toBeInTheDocument();
    expect(screen.getAllByText(/Missing: torch/)).not.toHaveLength(0);
    expect(screen.getByRole("link", { name: "Build log" })).toHaveAttribute("href", "/jobs/700");
  });

  it("starts a build from the dialog", async () => {
    const calls = mockFetch({ "GET /api/envs": ENVS,
                              "POST /api/envs/build": { status: 201, body: { job_id: "701" } } });
    render(<Environments />);
    fireEvent.click(await screen.findByRole("button", { name: "Build environment…" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "nlp" } });
    fireEvent.change(screen.getByLabelText("Packages"), { target: { value: "transformers" } });
    fireEvent.click(screen.getByRole("button", { name: "Start build" }));
    await vi.waitFor(() => expect(calls.some((c) => c.path === "/api/envs/build")).toBe(true));
    const sent = JSON.parse(calls.find((c) => c.path === "/api/envs/build")!.body!);
    expect(sent).toEqual({ kind: "conda", name: "nlp", packages: "transformers" });
  });
});
