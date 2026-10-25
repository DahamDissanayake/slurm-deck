import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockFetch } from "../../test/fetch";
import { Settings } from "./Settings";

afterEach(() => vi.unstubAllGlobals());

const SETTINGS = { default_time_limit: "08:00:00", extension_cap_hours: 24, submit_rate_per_hour: 20,
                   mail_enabled: true, maintenance_banner: null, terminal_jobs_enabled: true,
                   disk_alert_percent: 90, cluster_location: null };
const reply = { body: { settings: SETTINGS, partition_max_s: 86400 } };

describe("Settings", () => {
  it("flags a cap above the partition maximum before saving and blocks Save", async () => {
    mockFetch({ "GET /api/admin/settings": reply });
    render(<Settings />);
    const cap = await screen.findByLabelText(/Longest a job may be extended/);
    fireEvent.change(cap, { target: { value: "25" } });
    expect(await screen.findByText("Use a whole number from 1 to 24.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.change(cap, { target: { value: "12" } });
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("sends only what changed, and shows the server's refusal", async () => {
    const refusal = { status: 422, body: { error: "bad_setting", message: "Use a whole number from 50 to 99." } };
    const calls = mockFetch({ "GET /api/admin/settings": reply, "PUT /api/admin/settings": refusal });
    render(<Settings />);
    fireEvent.change(await screen.findByLabelText(/shared disk is this full/), { target: { value: "85" } });
    fireEvent.click(screen.getByLabelText("Send email"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Use a whole number from 50 to 99.");
    expect(JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}"))
      .toEqual({ disk_alert_percent: 85, mail_enabled: false });
  });
});
