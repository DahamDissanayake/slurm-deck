import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Link, navigate } from "../app/navigation";
import { Files } from "../pages/Files";
import { mockFetch } from "../test/fetch";
import { FilePicker } from "./FilePicker";
import { TextEditor } from "./TextEditor";
import { UploadPanel } from "./UploadPanel";

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
  { name: "train.py", type: "file", size: 120, mtime: 1_700_000_000 }] } };
const list = (path: string) => `GET /api/files?path=${encodeURIComponent(path)}`;

describe("UploadPanel", () => {
  it("suggests zipping first for a folder of more than 1 000 files", async () => {
    mockFetch({ "GET /api/uploads?active=1": { body: { uploads: [] } } });
    render(<UploadPanel destDir={HOME} />);
    const many = Array.from({ length: 1001 }, (_, i) => {
      const f = new File(["x"], `f${i}.txt`);
      Object.defineProperty(f, "webkitRelativePath", { value: `pics/f${i}.txt` });
      return f;
    });
    fireEvent.change(screen.getByLabelText("Upload folder"), { target: { files: many } });
    expect(await screen.findByText(
      "Zip first — 1 million small files upload far slower than one archive.")).toBeInTheDocument();
  });
});

describe("Files", () => {
  it("asks before deleting and deletes only when confirmed", async () => {
    const calls = mockFetch({ "GET /api/files/roots": ROOTS, [list(HOME)]: LISTING,
                              "GET /api/uploads?active=1": { body: { uploads: [] } },
                              "POST /api/files/delete": { body: {} } });
    navigate(`/files${HOME}`);
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

  it("hides write actions in a read-only area", async () => {
    mockFetch({ "GET /api/files/roots": ROOTS, [list("/shared/datasets")]: LISTING });
    navigate("/files/shared/datasets");
    render(<Files />);
    fireEvent.click(await screen.findByRole("button", { name: "train.py" }));
    expect(screen.getByText("Read-only")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download" })).toBeInTheDocument();
    for (const name of ["Delete", "Rename", "New folder"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(screen.queryByLabelText("Upload files")).toBeNull();
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
