import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LogViewer } from "./LogViewer";

afterEach(() => vi.unstubAllGlobals());

function serveLog(text: string, size = text.length) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    calls.push(String(input));
    return new Response(text, { headers: { "X-SD-Size": String(size) } });
  }));
  return calls;
}

describe("LogViewer", () => {
  it("renders log text literally, never as HTML", async () => {
    serveLog("start\n<b>x</b>\n<img src=x onerror=alert(1)>\n");
    const { container } = render(<LogViewer jobId="512" running={false} />);
    expect(await screen.findByText(/<b>x<\/b>/)).toBeInTheDocument();
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("shows only the last 1 MB of a larger log and says so", async () => {
    const calls = serveLog("tail", 3 * 1024 * 1024);
    render(<LogViewer jobId="512" running={false} />);
    expect(await screen.findByText(/Showing the last 1 MB/)).toBeInTheDocument();
    await vi.waitFor(() => expect(calls.some((c) => c.includes(`offset=${2 * 1024 * 1024}`)))
      .toBe(true));
  });

  it("filters lines with the search box", async () => {
    serveLog("epoch 1 loss 0.9\nepoch 2 loss 0.5\nsaving\n");
    render(<LogViewer jobId="512" running={false} />);
    await screen.findByText(/saving/);
    fireEvent.change(screen.getByLabelText("Search the log"), { target: { value: "epoch 2" } });
    expect(screen.queryByText(/saving/)).toBeNull();
    expect(screen.getByText(/epoch 2 loss/)).toBeInTheDocument();
  });
});
