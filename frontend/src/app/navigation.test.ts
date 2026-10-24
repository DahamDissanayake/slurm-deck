import { describe, expect, it } from "vitest";

import { match } from "./navigation";

describe("match", () => {
  it.each([
    ["/", "/", {}],
    ["/jobs", "/jobs", {}],
    ["/jobs/:id", "/jobs/512", { id: "512" }],
    ["/files/*", "/files/users/amasha/donn%C3%A9es%2050%25.csv",
     { "*": "users/amasha/données 50%.csv" }],
    ["/jobs/:id", "/jobs", null],
    ["/jobs", "/jobs/512", null],
    ["/admin/*", "/administrator", null],
  ])("%s against %s", (pattern, path, want) => {
    expect(match(pattern, path)).toEqual(want);
  });
});
