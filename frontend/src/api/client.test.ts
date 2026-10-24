import { afterEach, describe, expect, it, vi } from "vitest";

import { mockFetch } from "../test/fetch";
import { apiFetch, ApiError, setCsrf } from "./client";

afterEach(() => vi.unstubAllGlobals());

describe("apiFetch", () => {
  it("adds the CSRF header on POST only", async () => {
    const calls = mockFetch({ "GET /api/x": { body: { a: 1 } }, "POST /api/x": { body: {} } });
    setCsrf("tok123");
    expect(await apiFetch("/api/x")).toEqual({ a: 1 });
    await apiFetch("/api/x", { method: "POST", json: { b: 2 } });
    expect(calls[0].headers.get("X-CSRF-Token")).toBeNull();
    expect(calls[1].headers.get("X-CSRF-Token")).toBe("tok123");
    expect(calls[1].headers.get("Content-Type")).toBe("application/json");
    expect(calls[1].body).toBe('{"b":2}');
  });

  it("throws ApiError with the server's code and message", async () => {
    mockFetch({ "POST /api/y": { status: 409, body: { error: "exists", message: "Taken." } } });
    const err = (await apiFetch("/api/y", { method: "POST" }).catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect([err.status, err.code, err.message]).toEqual([409, "exists", "Taken."]);
  });

  it("sends a 401 to the sign-in page with next", async () => {
    mockFetch({ "GET /api/jobs": { status: 401, body: { error: "no_session" } } });
    window.history.pushState({}, "", "/jobs/42?tab=log");
    await expect(apiFetch("/api/jobs")).rejects.toBeInstanceOf(ApiError);
    expect(window.location.pathname).toBe("/sign-in");
    expect(new URLSearchParams(window.location.search).get("next")).toBe("/jobs/42?tab=log");
  });
});
