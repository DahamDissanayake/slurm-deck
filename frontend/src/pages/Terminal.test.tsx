import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockFetch } from "../test/fetch";
import { Terminal } from "./Terminal";

// jsdom can't lay out a terminal, so xterm is replaced by a recorder.
const xterm = vi.hoisted(() => ({
  onResize: null as null | ((size: { rows: number; cols: number }) => void),
  onData: null as null | ((data: string) => void),
  written: [] as string[],
}));
vi.mock("@xterm/xterm", () => ({
  Terminal: class {
    rows = 24;
    cols = 80;
    loadAddon() {}
    open() {}
    focus() {}
    dispose() {}
    write(s: string) { xterm.written.push(s); }
    onData(cb: (data: string) => void) { xterm.onData = cb; }
    onResize(cb: (size: { rows: number; cols: number }) => void) { xterm.onResize = cb; }
  },
}));
vi.mock("@xterm/addon-fit", () => ({
  FitAddon: class {
    fit() { xterm.onResize?.({ rows: 40, cols: 120 }); }
  },
}));

class FakeSocket {
  static all: FakeSocket[] = [];
  sent: unknown[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  readyState = 1;
  constructor(public url: string) { FakeSocket.all.push(this); }
  send(data: string) { this.sent.push(JSON.parse(data)); }
  close() { this.onclose?.(); }
}

beforeEach(() => {
  FakeSocket.all = [];
  xterm.written = [];
  vi.stubGlobal("WebSocket", FakeSocket);
});
afterEach(() => vi.unstubAllGlobals());

async function open() {
  mockFetch({ "POST /terminal/42/api/terminals": { status: 200, body: { name: "7" } } });
  render(<Terminal jobId="42" />);
  await vi.waitFor(() => expect(FakeSocket.all).toHaveLength(1));
  const ws = FakeSocket.all[0];
  act(() => ws.onopen?.());
  return ws;
}

describe("Terminal", () => {
  it("connects through the proxy to the terminal it created", async () => {
    const ws = await open();
    expect(ws.url).toMatch(/^wss?:\/\/[^/]+\/terminal\/42\/terminals\/websocket\/7$/);
  });

  it("sends set_size when the window is resized", async () => {
    const ws = await open();
    ws.sent.length = 0;
    act(() => { window.dispatchEvent(new Event("resize")); });
    expect(ws.sent).toContainEqual(["set_size", 40, 120, 0, 0]);
  });

  it("sends typed input and shows the terminal's output", async () => {
    const ws = await open();
    act(() => xterm.onData?.("ls\r"));
    expect(ws.sent).toContainEqual(["stdin", "ls\r"]);
    act(() => ws.onmessage?.({ data: JSON.stringify(["stdout", "hello"]) }));
    expect(xterm.written).toContain("hello");
  });

  it("offers Reconnect after the connection closes", async () => {
    const ws = await open();
    act(() => ws.close());
    (await screen.findByRole("button", { name: "Reconnect" })).click();
    await vi.waitFor(() => expect(FakeSocket.all).toHaveLength(2));
  });
});
