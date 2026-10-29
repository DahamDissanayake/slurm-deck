/** A small router on the History API: enough for this app's routes
 * (`:param` segments and a trailing `*`) without adding a dependency. */
import { type AnchorHTMLAttributes, useEffect, useSyncExternalStore } from "react";

function subscribe(onChange: () => void) {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
}

const snapshot = () => window.location.pathname + window.location.search + window.location.hash;

/** The current location; components re-render when it changes. */
export function useLocation() {
  useSyncExternalStore(subscribe, snapshot);
  return window.location;
}

export function navigate(to: string) {
  window.history.pushState({}, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

/** Sends the visitor to `to` in place of this page, so Back doesn't return here. */
export function Redirect({ to }: { to: string }) {
  useEffect(() => {
    window.history.replaceState({}, "", to);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, [to]);
  return null;
}

/** Params for a pattern like `/jobs/:id` or `/files/*`, or null when it doesn't match. */
export function match(pattern: string, path: string): Record<string, string> | null {
  const want = pattern.split("/").filter(Boolean);
  const got = path.split("/").filter(Boolean);
  const params: Record<string, string> = {};
  for (let i = 0; i < want.length; i++) {
    if (want[i] === "*") {
      params["*"] = got.slice(i).map(decodeURIComponent).join("/");
      return params;
    }
    if (i >= got.length) return null;
    if (want[i].startsWith(":")) params[want[i].slice(1)] = decodeURIComponent(got[i]);
    else if (want[i] !== got[i]) return null;
  }
  return got.length === want.length ? params : null;
}

/** An <a> that navigates in-app (ordinary clicks only). */
export function Link({ href, onClick, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & {
  href: string;
}) {
  return (
    <a
      href={href}
      onClick={(e) => {
        onClick?.(e);
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
        e.preventDefault();
        navigate(href);
      }}
      {...rest}
    />
  );
}
