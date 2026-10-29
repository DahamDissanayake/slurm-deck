import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Link, navigate } from "../app/navigation";
import { Files } from "../pages/Files";
import { mockFetch } from "../test/fetch";
import { FilePicker } from "./FilePicker";
import { TextEditor } from "./TextEditor";
import { UploadPanel } from "./UploadPanel";

// A stand-in for tus-js-client that records what would be sent.
const tus = vi.hoisted(() => ({ sent: [] as { name: string; options: { metadata: Record<string, string> } }[] }));
vi.mock("tus-js-client", () => ({
  Upload: class {
    constructor(public file: File, public options: { metadata: Record<string, string> }) {}
    findPreviousUploads() { return Promise.resolve([]); }
    resumeFromPreviousUpload() {}
    start() { tus.sent.push({ name: this.file.name, options: this.options }); }
    abort() {}
  },
}));

beforeEach(() => { tus.sent.length = 0; });
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const HOME = "/shared/users/amasha";
const ROOTS = { body: { roots: [{ label: "My files", path: HOME, writable: true },
                                { label: "Shared datasets", path: "/shared/datasets",
                                  writable: false }] } };
const LISTING = { body: { entries: [
  { name: "data", type: "dir", size: 0, mtime: 1_700_000_000 },
  { name: "train.py", type: "file", size: 120, mtime: 1_700_000_000 },
  { name: "notes.txt", type: "file", size: 2048, mtime: 1_700_100_000 },
  { name: "weights.zip", type: "file", size: 5_000_000, mtime: 1_700_200_000 }] } };
const list = (path: string) => `GET /api/files?path=${encodeURIComponent(path)}`;
const UPLOADS = { "GET /api/uploads?active=1": { body: { uploads: [] } } };
const setup = (extra: Record<string, { status?: number; body?: unknown }> = {}) => {
  navigate(`/files${HOME}`);
  return mockFetch({ "GET /api/files/roots": ROOTS, [list(HOME)]: LISTING, ...UPLOADS, ...extra });
};

describe("UploadPanel", () => {
  it("suggests zipping first for a folder of more than 1 000 files", async () => {
    mockFetch(UPLOADS);
    const many = Array.from({ length: 1001 }, (_, i) => {
      const f = new File(["x"], `f${i}.txt`);
      Object.defineProperty(f, "webkitRelativePath", { value: `pics/f${i}.txt` });
      return f;
    });
    render(<UploadPanel destDir={HOME} incoming={{ files: many, id: 1 }} />);
    expect(await screen.findByText(
      "Zip first — 1 million small files upload far slower than one archive.")).toBeInTheDocument();
    expect(tus.sent).toHaveLength(0);
  });

  it("starts uploading straight away into the folder when files arrive", async () => {
    mockFetch(UPLOADS);
    render(<UploadPanel destDir={HOME} incoming={{ files: [new File(["x"], "a.csv")], id: 1 }} />);
    await vi.waitFor(() => expect(tus.sent).toHaveLength(1));
    expect(tus.sent[0].options.metadata).toMatchObject({ filename: "a.csv", dest_dir: HOME });
    expect(screen.getByRole("region", { name: "Uploads" })).toHaveTextContent("a.csv");
  });
});

describe("Files workspace", () => {
  it("lists the places and the folders of the current place", async () => {
    setup();
    render(<Files />);
    const places = await screen.findByRole("navigation", { name: "Places" });
    expect(within(places).getByRole("link", { name: /My files/ })).toHaveAttribute("aria-current", "page");
    expect(within(places).getByRole("link", { name: /Shared datasets/ })).toBeInTheDocument();
    const tree = screen.getByRole("navigation", { name: "Folders" });
    expect(await within(tree).findByRole("link", { name: "data" })).toHaveAttribute("href", `/files${HOME}/data`);
  });

  it("shows skeleton rows while a folder loads", async () => {
    setup();
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => String(input).includes("/roots")
      ? Promise.resolve(new Response(JSON.stringify(ROOTS.body), { headers: { "Content-Type": "application/json" } }))
      : new Promise(() => {})));
    render(<Files />);
    await screen.findByRole("navigation", { name: "Places" });
    expect(screen.getByRole("status", { name: "Loading files" })).toBeInTheDocument();
  });

  it("shows an error with Retry that reloads, instead of a bare failure message", async () => {
    let tries = 0;
    setup();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
      if (path.includes("/roots")) return json(ROOTS.body);
      if (path.startsWith("/api/files?path=") && path.includes("amasha") && !path.includes("data")) {
        return ++tries === 1 ? json({ error: "io", message: "The disk is busy." }, 500) : json(LISTING.body);
      }
      return json({ uploads: [] });
    }));
    render(<Files />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The disk is busy.");
    fireEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("button", { name: "train.py" })).toBeInTheDocument();
  });

  it("says when a folder is empty", async () => {
    setup({ [list(HOME)]: { body: { entries: [] } } });
    render(<Files />);
    expect(await screen.findByText("This folder is empty")).toBeInTheDocument();
  });

  it("switches between a list and a grid, and filters by name", async () => {
    setup();
    render(<Files />);
    expect(await screen.findByRole("table", { name: "Files" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Grid" }));
    expect(screen.getByRole("list", { name: "Files" })).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    fireEvent.change(screen.getByRole("searchbox", { name: "Filter files" }), { target: { value: "notes" } });
    expect(screen.queryByRole("button", { name: "train.py" })).toBeNull();
    expect(screen.getByRole("button", { name: "notes.txt" })).toBeInTheDocument();
  });

  it("sorts by size from the sort menu", async () => {
    setup();
    render(<Files />);
    await screen.findByRole("button", { name: "train.py" });
    fireEvent.click(screen.getByRole("button", { name: "Sort files" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Size/ }));
    const names = within(screen.getByRole("table", { name: "Files" })).getAllByRole("button")
      .map((b) => b.textContent).filter((t) => /\./.test(t ?? "") && !/^Select/.test(t ?? ""));
    expect(names).toEqual(["train.py", "notes.txt", "weights.zip"]);
  });

  it("shows the selection bar with the count when two files are selected", async () => {
    setup();
    render(<Files />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select train.py" }));
    expect(screen.getByRole("toolbar", { name: "Selection" })).toHaveTextContent("1 selected");
    fireEvent.click(screen.getByRole("checkbox", { name: "Select notes.txt" }));
    const bar = screen.getByRole("toolbar", { name: "Selection" });
    expect(bar).toHaveTextContent("2 selected");
    expect(within(bar).getByRole("button", { name: "Download" })).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: "Move" })).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: "Delete" })).toBeInTheDocument();
    expect(within(bar).queryByRole("button", { name: "Rename" })).toBeNull();
    fireEvent.click(within(bar).getByRole("button", { name: "Clear selection" }));
    expect(screen.queryByRole("toolbar", { name: "Selection" })).toBeNull();
  });

  it("offers Extract when the selection is archives", async () => {
    setup();
    render(<Files />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select weights.zip" }));
    expect(within(screen.getByRole("toolbar", { name: "Selection" })).getByRole("button", { name: "Extract" }))
      .toBeInTheDocument();
  });

  it("shows details and a preview for the selected file", async () => {
    setup({ [`GET /api/files/preview?path=${encodeURIComponent(`${HOME}/train.py`)}`]:
              { body: { kind: "text", text: "print('hi')", truncated: false } } });
    render(<Files />);
    fireEvent.click(await screen.findByRole("button", { name: "train.py" }));
    const details = screen.getByRole("complementary", { name: "Details" });
    expect(details).toHaveTextContent("train.py");
    expect(details).toHaveTextContent("120 B");
    expect(await within(details).findByText(/print\('hi'\)/)).toBeInTheDocument();
  });

  it("opens a context menu on right-click with this row's actions", async () => {
    setup();
    render(<Files />);
    fireEvent.contextMenu(await screen.findByRole("button", { name: "train.py" }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent))
      .toEqual(["Download", "Edit", "Rename", "Move", "Delete"]);
    fireEvent.keyDown(menu, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("uploads dropped files into the current folder", async () => {
    setup();
    render(<Files />);
    const area = await screen.findByRole("region", { name: "Files" });
    const file = new File(["x"], "dropped.csv");
    fireEvent.dragEnter(area, { dataTransfer: { types: ["Files"], files: [file] } });
    expect(screen.getByText("Drop to upload")).toBeInTheDocument();
    fireEvent.drop(area, { dataTransfer: { types: ["Files"], files: [file] } });
    await vi.waitFor(() => expect(tus.sent).toHaveLength(1));
    expect(tus.sent[0].options.metadata).toMatchObject({ filename: "dropped.csv", dest_dir: HOME });
    expect(screen.getByRole("region", { name: "Uploads" })).toHaveTextContent("dropped.csv");
  });

  it("asks before deleting and deletes only when confirmed", async () => {
    const calls = setup({ "POST /api/files/delete": { body: {} } });
    render(<Files />);
    fireEvent.click(await screen.findByRole("button", { name: "train.py" }));
    const ask = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(ask).toHaveBeenCalledTimes(1);
    expect(calls.some((c) => c.path === "/api/files/delete")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await vi.waitFor(() => expect(calls.find((c) => c.path === "/api/files/delete")?.body)
      .toBe(JSON.stringify({ path: `${HOME}/train.py`, recursive: false })));
  });

  it("deletes every selected item after one confirmation", async () => {
    const calls = setup({ "POST /api/files/delete": { body: {} } });
    render(<Files />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Select train.py" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select notes.txt" }));
    const ask = vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await vi.waitFor(() => expect(calls.filter((c) => c.path === "/api/files/delete")).toHaveLength(2));
    expect(ask).toHaveBeenCalledTimes(1);
  });

  it("hides write actions in a read-only area", async () => {
    mockFetch({ "GET /api/files/roots": ROOTS, [list("/shared/datasets")]: LISTING, ...UPLOADS });
    navigate("/files/shared/datasets");
    render(<Files />);
    fireEvent.click(await screen.findByRole("button", { name: "train.py" }));
    expect(screen.getByText("Read-only")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download" })).toBeInTheDocument();
    for (const name of ["Delete", "Rename", "New folder"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(screen.queryByLabelText("Upload files")).toBeNull();
    fireEvent.contextMenu(screen.getByRole("button", { name: "train.py" }));
    expect(within(screen.getByRole("menu")).getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["Download"]);
  });
});

describe("FilePicker", () => {
  it("returns the absolute /shared path of the chosen file", async () => {
    mockFetch({ "GET /api/files/roots": ROOTS, [list(HOME)]: LISTING });
    const onPick = vi.fn();
    render(<FilePicker mode="file" onPick={onPick} onClose={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "train.py" }));
    fireEvent.click(screen.getByRole("button", { name: "Choose" }));
    expect(onPick).toHaveBeenCalledWith(`${HOME}/train.py`);
  });
});

describe("TextEditor", () => {
  it("warns before leaving with unsaved changes", async () => {
    mockFetch({ [`GET /api/files/text?path=${encodeURIComponent(`${HOME}/a.py`)}`]:
                  { body: { text: "print(1)" } } });
    render(<><Link href="/jobs">Jobs</Link><TextEditor path={`${HOME}/a.py`} onClose={() => {}} /></>);
    fireEvent.change(await screen.findByDisplayValue("print(1)"), { target: { value: "print(2)" } });
    const ask = vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.click(screen.getByRole("link", { name: "Jobs" }));
    expect(ask).toHaveBeenCalledWith("You have unsaved changes. Leave without saving?");
    expect(window.location.pathname).not.toBe("/jobs");
  });
});
