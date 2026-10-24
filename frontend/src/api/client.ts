/** The one way the app talks to the web API: same-origin cookies, the CSRF
 * header on every write, errors as ApiError, and a signed-out 401 sent to the
 * sign-in page with a way back. */

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

let csrf = "";

/** Remember the CSRF token from the last sign-in or /api/auth/me reply. */
export function setCsrf(token: string) {
  csrf = token;
}

/** The current CSRF token, for requests made outside apiFetch (tus uploads). */
export const csrfToken = () => csrf;

type Init = RequestInit & { json?: unknown };

const PUBLIC_PATHS = ["/sign-in", "/apply", "/set-password", "/reset-password",
                      "/forgot-password"];

export async function apiFetch<T = unknown>(path: string, init: Init = {}): Promise<T> {
  const { json, ...rest } = init;
  const method = (rest.method ?? "GET").toUpperCase();
  const headers = new Headers(rest.headers);
  if (json !== undefined) headers.set("Content-Type", "application/json");
  if (method !== "GET" && csrf) headers.set("X-CSRF-Token", csrf);
  const res = await fetch(path, {
    ...rest, method, headers, credentials: "same-origin",
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  const data = await res.json().catch(() => ({}));
  if (res.ok) return data as T;
  const err = new ApiError(res.status, data.error ?? "error", data.message ?? "");
  if (res.status === 401 && !PUBLIC_PATHS.includes(window.location.pathname)) {
    const next = window.location.pathname + window.location.search;
    window.history.pushState({}, "", `/sign-in?next=${encodeURIComponent(next)}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }
  throw err;
}
