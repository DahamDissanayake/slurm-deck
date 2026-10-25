import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockFetch } from "../../test/fetch";
import { Monitoring } from "./Monitoring";
import { Settings } from "./Settings";

afterEach(() => vi.unstubAllGlobals());

const SETTINGS = { default_time_limit: "08:00:00", extension_cap_hours: 24, submit_rate_per_hour: 20,
                   mail_enabled: true, maintenance_banner: null, terminal_jobs_enabled: true,
                   disk_alert_percent: 90, cluster_location: null };
const reply = (over = {}) => ({ body: { settings: { ...SETTINGS, ...over }, partition_max_s: 86400 } });

describe("Settings", () => {
  it("flags a cap above the partition maximum before saving and blocks Save", async () => {
    mockFetch({ "GET /api/admin/settings": reply() });
    render(<Settings />);
    const cap = await screen.findByLabelText(/Longest a job may be extended/);
    fireEvent.change(cap, { target: { value: "25" } });
    expect(await screen.findByText("Use a whole number from 1 to 24.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.change(cap, { target: { value: "12" } });
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("sends only what changed, and shows the server's refusal", async () => {
    const calls = mockFetch({
      "GET /api/admin/settings": reply(),
      "PUT /api/admin/settings": { status: 422, body: { error: "bad_setting", message: "Use a whole number from 50 to 99." } },
    });
    render(<Settings />);
    fireEvent.change(await screen.findByLabelText(/shared disk is this full/), { target: { value: "85" } });
    fireEvent.click(screen.getByLabelText("Send email"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Use a whole number from 50 to 99.");
    expect(JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}"))
      .toEqual({ disk_alert_percent: 85, mail_enabled: false });
  });
});

describe("Monitoring", () => {
  const events = (n: number, more: boolean) => ({ body: { page: 1, has_more: more, events: Array.from(
    { length: n }, (_, i) => ({ id: i, ts: "2026-10-25T10:00:00+00:00", actor: "amasha", acting_admin: null,
                                action: "job.cancel", target: String(i), result: "ok", source: "web" })) } });

  it("pages the audit trail on the server and filters by action", async () => {
    const calls = mockFetch({
      "GET /api/admin/audit?page=1&page_size=25": events(2, true),
      "GET /api/admin/audit?page=2&page_size=25": events(1, false),
      "GET /api/admin/audit?action=job&page=1&page_size=25": events(1, false),
    });
    render(<Monitoring />);
    expect((await screen.findAllByText("job.cancel"))).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Page 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    fireEvent.change(screen.getByLabelText(/Action starts with/), { target: { value: "job" } });
    await vi.waitFor(() => expect(calls.some((c) => c.path.includes("action=job"))).toBe(true));
  });

  it("shows why a mail failed", async () => {
    mockFetch({
      "GET /api/admin/audit?page=1&page_size=25": events(0, false),
      "GET /api/admin/mail-log?page=1&page_size=25": { body: { page: 1, has_more: false, mail: [
        { id: 1, to: "a@x.org", subject: "Hello", kind: "k", status: "failed",
          created_at: "2026-10-25T10:00:00+00:00", error: "smtp refused" }] } },
    });
    render(<Monitoring />);
    fireEvent.click(screen.getByRole("tab", { name: "Mail log" }));
    expect(await screen.findByText("smtp refused")).toBeInTheDocument();
  });
});
