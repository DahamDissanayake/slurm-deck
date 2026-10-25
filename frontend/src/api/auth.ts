import { apiFetch, setCsrf } from "./client";

export type Account = {
  id: number;
  email: string;
  full_name: string;
  username: string;
  role: "user" | "admin";
  status: string;
  linux_kind: string;
};

export type Me = { account: Account; acting_as: Account | null; csrf_token: string };

export async function getMe(): Promise<Me> {
  const me = await apiFetch<Me>("/api/auth/me");
  setCsrf(me.csrf_token);
  return me;
}

export async function signIn(email: string, password: string) {
  const out = await apiFetch<{ csrf_token: string }>("/api/auth/login",
                                                     { method: "POST", json: { email, password } });
  setCsrf(out.csrf_token);
}

export async function signOut() {
  await apiFetch("/api/auth/logout", { method: "POST" });
  setCsrf("");
}

export async function setPassword(token: string, password: string) {
  const out = await apiFetch<{ csrf_token: string }>("/api/auth/password/set",
                                                     { method: "POST", json: { token, password } });
  setCsrf(out.csrf_token);
}

export const forgotPassword = (email: string) =>
  apiFetch("/api/auth/password/forgot", { method: "POST", json: { email } });

export const applyOpen = () =>
  apiFetch<{ open: boolean }>("/api/public/apply-open").then((r) => r.open);

export const siteInfo = () =>
  apiFetch<{ hostname: string; lan_addr: string }>("/api/public/site");

export type Application = {
  email: string;
  full_name: string;
  role_title: string;
  organisation: string;
  contact_number: string;
  reason: string;
  website: string;
};

export const apply = (form: Application) =>
  apiFetch<{ message: string }>("/api/public/applications", { method: "POST", json: form });

export const stopViewing = () => apiFetch("/api/admin/view-as", { method: "DELETE" });
