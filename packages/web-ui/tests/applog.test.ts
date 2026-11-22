// An app's failure shown with its log (AppFailure): the end of the log that tells why, from the
// failed step's mark, not the whole log nor only what came after it.
import { describe, expect, it } from "vitest";
import { logTail } from "../src/lib/apps";

const LOG = [
  "[2026-11-17 08:00:00] == deploy 0.6.0 (#2)",
  "[2026-11-17 08:00:01] running the backend's tests",
  "[2026-11-17 08:00:03] deployed 0.6.0 (#2)",
  "[2026-11-17 08:00:04] starting 0.6.0 (#2)",
  "[2026-11-18 17:18:50] == deploy 0.9.0 (#3)",
  "[2026-11-18 17:18:51] running the backend's tests",
  "EROFS: read-only file system, mkdir '/opt/app/server/.data'",
  " 5 pass",
  " 23 fail",
  "[2026-11-18 17:19:00] deploy failed: the tests failed (exit 1); see the log",
  "[2026-11-18 17:19:11] starting 0.6.0 (#2)",
].join("\n");

describe("the end of an app's log", () => {
  it("a deploy that failed: from its mark, its tests' output in it, what followed too", () => {
    const tail = logTail(LOG, "deploy").split("\n");
    expect(tail[0]).toBe("[2026-11-18 17:18:50] == deploy 0.9.0 (#3)");
    expect(tail).toContain(" 23 fail");
    expect(tail.at(-1)).toBe("[2026-11-18 17:19:11] starting 0.6.0 (#2)");
    expect(tail).not.toContain("[2026-11-17 08:00:03] deployed 0.6.0 (#2)");
  });

  it("a backend that stopped: from its last start", () => {
    const log = `${LOG}\nTypeError: x is not a function\n[2026-11-18 17:20:00] backend exited (1)`;
    expect(logTail(log, "start").split("\n")).toEqual([
      "[2026-11-18 17:19:11] starting 0.6.0 (#2)",
      "TypeError: x is not a function",
      "[2026-11-18 17:20:00] backend exited (1)",
    ]);
  });

  it("no mark: its last lines; a long step: its last lines only", () => {
    const lines = Array.from({ length: 100 }, (_, i) => `line ${i}`);
    expect(logTail(lines.join("\n")).split("\n")).toEqual(lines.slice(-40));
    const long = ["[x] == deploy 1.0.0 (#1)", ...Array.from({ length: 500 }, (_, i) => `out ${i}`)];
    expect(logTail(long.join("\n")).split("\n").length).toBe(300);
    expect(logTail("")).toBe("");
  });
});
