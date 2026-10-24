import { vi } from "vitest";

export type Reply = { status?: number; body?: unknown };

/** Replace fetch with canned replies keyed by "METHOD /path"; records every call. */
export function mockFetch(replies: Record<string, Reply>) {
  const calls: { method: string; path: string; headers: Headers; body?: string }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const method = (init.method ?? "GET").toUpperCase();
    const path = String(input);
    calls.push({ method, path, headers: new Headers(init.headers), body: init.body as string });
    const reply = replies[`${method} ${path}`] ?? { status: 404, body: { error: "not_found" } };
    return new Response(JSON.stringify(reply.body ?? {}), {
      status: reply.status ?? 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}
