import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockFetch } from "../../test/fetch";
import { NewUser } from "./NewUser";
import { Requests } from "./Requests";
import { UserDetail } from "./UserDetail";

afterEach(() => vi.unstubAllGlobals());

const FOLDER = { exists: true, owner_uid: 2014, bytes: 5_000_000_000,
                 mtime: "2026-03-01T10:00:00+00:00", uid_in_use: false };

describe("NewUser", () => {
  it("keeps Create disabled until the reconnect choice is made when a folder is found", async () => {
    const calls = mockFetch({
      "POST /api/admin/accounts/preview": { body: {
        suggested_username: "nimal", email_valid: true, username_valid: true,
        existing_folder: FOLDER, shell_account: null } },
      "POST /api/admin/accounts": { body: { id: 7 } },
    });
    render(<NewUser />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "nimal@x.org" } });
    fireEvent.blur(screen.getByLabelText("Email"));
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Nimal" } });
    expect(await screen.findByText(/Existing folder found — 5.0 GB/)).toHaveTextContent(
      "owned by UID 2014");
    const create = screen.getByRole("button", { name: "Create account" });
    expect(create).toBeDisabled();
    fireEvent.click(screen.getByLabelText("This is the same person — reconnect"));
    expect(create).toBeEnabled();
    fireEvent.click(create);
    await vi.waitFor(() => expect(calls.some((c) => c.path === "/api/admin/accounts")).toBe(true));
    const sent = JSON.parse(calls.find((c) => c.path === "/api/admin/accounts")!.body!);
    expect(sent).toMatchObject({ username: "nimal", reconnect_folder: true, attach_shell: false });
  });
});

describe("UserDetail delete", () => {
  it("keeps purge disabled until the username is typed", async () => {
    mockFetch({ "GET /api/admin/accounts": { body: { accounts: [
      { id: 5, username: "amasha", email: "amasha@x.org", full_name: "Amasha", role: "user",
        status: "active", linux_kind: "hidden", uid: 20001, created_at: null,
        last_login_at: null }] } } });
    render(<UserDetail id={5} />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete…" }));
    fireEvent.click(screen.getByLabelText("Also delete their files (purge)"));
    const purge = screen.getByRole("button", { name: "Delete account and files" });
    expect(purge).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Type amasha to confirm"), { target: { value: "amash" } });
    expect(purge).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Type amasha to confirm"), { target: { value: "amasha" } });
    expect(purge).toBeEnabled();
  });
});

describe("Requests", () => {
  it("pre-fills the approve dialog with the suggested username", async () => {
    mockFetch({
      "GET /api/admin/applications?status=pending": { body: { applications: [
        { id: 3, email: "kasun@iit.ac.lk", full_name: "Kasun", role_title: "Student",
          organisation: null, contact_number: "077", reason: "LLMs", status: "pending",
          created_at: "2026-10-24T09:00:00+00:00" }] } },
      "POST /api/admin/accounts/preview": { body: {
        suggested_username: "kasun-2", email_valid: true, username_valid: true,
        existing_folder: null, shell_account: null } },
    });
    render(<Requests />);
    fireEvent.click(await screen.findByRole("button", { name: "Approve…" }));
    expect(await screen.findByLabelText("Username")).toHaveValue("kasun-2");
  });
});
