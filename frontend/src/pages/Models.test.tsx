import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockFetch } from "../test/fetch";
import { Models } from "./Models";

afterEach(() => vi.unstubAllGlobals());

const base = {
  "GET /api/models": { body: { shared: [{ name: "llama", type: "dir", bytes: 2048 }], mine: [] } },
  "GET /api/models/downloads": { body: { downloads: [] } },
};

describe("Models", () => {
  it("lists shared models with their sizes", async () => {
    mockFetch(base);
    render(<Models />);
    expect(await screen.findByText("llama")).toBeInTheDocument();
    expect(screen.getByText("2.0 KB")).toBeInTheDocument();
  });

  it("masks the token, says it is not saved, sends it once and clears it", async () => {
    const calls = mockFetch({ ...base, "POST /api/models/download": { status: 201, body: { job_id: "9" } } });
    render(<Models />);
    const token = await screen.findByLabelText(/HuggingFace token/);
    expect(token).toHaveAttribute("type", "password");
    expect(screen.getByText(/isn't saved/)).toBeInTheDocument();
    expect(screen.queryByText(/save for next time/i)).toBeNull();
    fireEvent.change(screen.getByLabelText("Repository"), { target: { value: "org/model" } });
    fireEvent.change(token, { target: { value: "hf_abc" } });
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    expect(await screen.findByText("Started job 9.")).toBeInTheDocument();
    expect(JSON.parse(calls.find((c) => c.method === "POST")?.body ?? "{}"))
      .toEqual({ repo_id: "org/model", revision: null, token: "hf_abc" });
    expect(token).toHaveValue("");
  });

  it("shows the server's words for a repository that isn't valid", async () => {
    mockFetch({ ...base, "POST /api/models/download": { status: 422, body: {
      error: "bad_repo", message: "Use the form owner/name, like meta-llama/Llama-3.1-8B." } } });
    render(<Models />);
    fireEvent.change(await screen.findByLabelText("Repository"), { target: { value: "nonsense" } });
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    expect(await screen.findByText(/Use the form owner\/name/)).toBeInTheDocument();
  });

  it("shows why a download failed", async () => {
    mockFetch({ ...base, "GET /api/models/downloads": { body: { downloads: [{
      job_id: "5", repo_id: "org/gated", state: "failed", bytes: null,
      message: "HuggingFace refused the token for this repository." }] } } });
    render(<Models />);
    expect(await screen.findByText("HuggingFace refused the token for this repository."))
      .toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });
});
