import { describe, expect, it } from "vitest";
import { byState, DEFAULT_PREFS, dropped, gridShape, onStage, ordered, pillOf, readPrefs, spans, waitingSince } from "../src/lib/running.svelte";

describe("Running's grid", () => {
  it("fits everything shown: 2 × 2 up to 4, 3 × 2 up to 6, 3 × 3 up to 9", () => {
    expect(gridShape(1)).toEqual({ cols: 1, rows: 1 });
    expect(gridShape(2)).toEqual({ cols: 2, rows: 1 });
    expect(gridShape(3)).toEqual({ cols: 2, rows: 2 });
    expect(gridShape(4)).toEqual({ cols: 2, rows: 2 });
    expect(gridShape(5)).toEqual({ cols: 3, rows: 2 });
    expect(gridShape(6)).toEqual({ cols: 3, rows: 2 });
    expect(gridShape(7)).toEqual({ cols: 3, rows: 3 });
    expect(gridShape(9)).toEqual({ cols: 3, rows: 3 });
  });

  it("scrolls beyond 9: three columns, more rows", () => {
    expect(gridShape(10)).toEqual({ cols: 3, rows: 4 });
    expect(gridShape(13)).toEqual({ cols: 3, rows: 5 });
  });

  it("widens the last row's panes rather than leave a hole", () => {
    expect(spans(3, 2)).toEqual([3, 3, 6]);
    expect(spans(4, 2)).toEqual([3, 3, 3, 3]);
    expect(spans(5, 3)).toEqual([2, 2, 2, 3, 3]);
    expect(spans(7, 3)).toEqual([2, 2, 2, 2, 2, 2, 6]);
    expect(spans(1, 1)).toEqual([6]);
  });
});

describe("Running's order", () => {
  const items = ["a", "b", "c", "d"].map((key) => ({ key }));

  it("puts the panes dragged first, as dragged, then the others as they came", () => {
    expect(ordered(items, ["c", "a"]).map((x) => x.key)).toEqual(["c", "a", "b", "d"]);
    expect(ordered(items, ["gone", "b"]).map((x) => x.key)).toEqual(["b", "a", "c", "d"]);
    expect(ordered(items, []).map((x) => x.key)).toEqual(["a", "b", "c", "d"]);
  });

  it("drops a pane in the place of the one it is dropped on", () => {
    expect(dropped(["a", "b", "c", "d"], "a", "c")).toEqual(["b", "c", "a", "d"]);
    expect(dropped(["a", "b", "c", "d"], "d", "a")).toEqual(["d", "a", "b", "c"]);
    expect(dropped(["a", "b"], "a", "a")).toEqual(["a", "b"]);
    expect(dropped(["a", "b"], "x", "a")).toEqual(["a", "b"]);
  });
});

describe("Running's order by state", () => {
  const tile = (key: string, needsYou = false) => ({ key, needsYou });
  const keys = (xs: { key: string }[]) => xs.map((x) => x.key);

  it("puts those that need you first, the latest to ask first, then the others as dragged", () => {
    const items = [tile("a"), tile("b", true), tile("c"), tile("d", true)];
    expect(keys(byState(items, [], { b: 1, d: 2 }))).toEqual(["d", "b", "a", "c"]);
    expect(keys(byState(items, ["c"], { b: 2, d: 1 }))).toEqual(["b", "d", "c", "a"]);
  });

  it("moves a tile only when its state changes", () => {
    let since: Record<string, number> = {};
    let n = 0;
    const next = () => ++n;
    const look = (items: ReturnType<typeof tile>[]) => {
      since = waitingSince(since, keys(items.filter((x) => x.needsYou)), next);
      return keys(byState(items, [], since));
    };
    expect(look([tile("a"), tile("b"), tile("c")])).toEqual(["a", "b", "c"]);
    expect(look([tile("a"), tile("b", true), tile("c")])).toEqual(["b", "a", "c"]); // b asks
    expect(look([tile("a"), tile("b", true), tile("c")])).toEqual(["b", "a", "c"]); // again: nothing moves
    expect(look([tile("a"), tile("b", true), tile("c", true)])).toEqual(["c", "b", "a"]); // c asks after b
    expect(look([tile("a"), tile("b", true), tile("c", true)])).toEqual(["c", "b", "a"]);
    expect(look([tile("a"), tile("b"), tile("c", true)])).toEqual(["c", "a", "b"]); // b answered: back in its place
    expect(look([tile("a"), tile("b", true), tile("c", true)])).toEqual(["b", "c", "a"]); // b asks again: the latest
  });

  it("forgets when a session stopped needing you, and never repeats a mark", () => {
    let n = 0;
    expect(waitingSince({ a: 1, b: 2 }, ["b", "c"], () => (n += 10))).toEqual({ b: 2, c: 10 });
  });

  it("shows four states, whatever the finer one", () => {
    expect(pillOf("needs-you")).toBe("needs-you");
    expect(pillOf("working")).toBe("working");
    expect(pillOf("starting")).toBe("working");
    expect(pillOf("idle")).toBe("idle");
    expect(pillOf("replied")).toBe("idle");
    expect(pillOf("elsewhere")).toBe("idle");
    expect(pillOf("stopped")).toBe("stopped");
    expect(pillOf("failed")).toBe("stopped");
  });
});

describe("Running's stage", () => {
  const s = (key: string, project: string | null, needsYou = false) => ({ key, project, needsYou });
  const all = [s("a", "p1"), s("b", "p1", true), s("c", "p2"), s("d", null)];

  it("shows every session not hidden; a chip only filters", () => {
    expect(onStage(all, undefined, ["c"]).shown.map((x) => x.key)).toEqual(["a", "b", "d"]);
    expect(onStage(all, "p1", ["c"]).shown.map((x) => x.key)).toEqual(["a", "b"]);
    expect(onStage(all, "p1", ["c"]).hidden).toEqual([]); // hidden is one setting: the chip says those of its project
    expect(onStage(all, "", []).shown.map((x) => x.key)).toEqual(["d"]); // outside projects
  });

  it("brings back a hidden session while it needs you", () => {
    const stage = onStage(all, undefined, ["a", "b"]);
    expect(stage.shown.map((x) => x.key)).toEqual(["b", "c", "d"]);
    expect(stage.hidden.map((x) => x.key)).toEqual(["a", "b"]);
    expect([...stage.back]).toEqual(["b"]);
  });
});

describe("Running's remembered state", () => {
  it("reads what was kept, and the defaults from nothing or anything else", () => {
    expect(readPrefs(null)).toEqual(DEFAULT_PREFS);
    expect(readPrefs("not json")).toEqual(DEFAULT_PREFS);
    expect(readPrefs('{"layout":"diagonal","hidden":[1,"a"],"folded":"yes"}')).toEqual({ ...DEFAULT_PREFS, hidden: ["a"] });
    const kept = { hidden: ["a"], order: ["b", "a"], layout: "columns", folded: true };
    expect(readPrefs(JSON.stringify(kept))).toEqual(kept);
  });
});
