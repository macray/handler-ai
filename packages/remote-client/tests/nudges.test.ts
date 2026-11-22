// A nudge's form drawn on the phone from its action's schema, and how often it alerts (H.17).
import { describe, expect, it } from "vitest";
import { endedWords, fieldsOf, fieldValues, formValues, less, more, SETTINGS, withSetting } from "../src/lib/nudges";
import type { InboxMessage } from "../src/lib/remote.gen";

const daily = {
  type: "object",
  required: ["done"],
  properties: {
    done: { type: "string", title: "What you did", "x-handler": "long-text" },
    hours: { type: "number" },
    mood: { type: "string", enum: ["good", "meh", "bad"] },
    billable: { type: "boolean" },
    tags: { type: "array", items: { type: "string" } },
    extra: { type: "object" },
    project_name: { type: "string" },
  },
};

describe("the form", () => {
  it("draws each property as its input, the schema's title as its label", () => {
    const fields = fieldsOf(daily);
    expect(fields.map((f) => [f.key, f.kind, f.title, f.required])).toEqual([
      ["done", "long-text", "What you did", true],
      ["hours", "number", "Hours", false],
      ["mood", "choice", "Mood", false],
      ["billable", "boolean", "Billable", false],
      ["tags", "list", "Tags", false],
      ["extra", "json", "Extra", false],
      ["project_name", "text", "Project name", false],
    ]);
    expect(fields[2]!.choices).toEqual(["good", "meh", "bad"]);
  });

  it("has nothing to draw without a schema", () => {
    expect(fieldsOf(null)).toEqual([]);
    expect(fieldsOf({ type: "object" })).toEqual([]);
  });

  it("shows what the app filled in, as the inputs hold it", () => {
    const fields = fieldsOf(daily);
    const shown = formValues(fields, { done: "Reviewed PRs", hours: 3.5, tags: ["a", "b"], extra: { x: 1 }, billable: true, unknown: 1 });
    expect(shown).toEqual({ done: "Reviewed PRs", hours: "3.5", tags: "a\nb", extra: '{"x":1}', billable: true });
  });

  it("sends the inputs as the action's fields, empty optional ones left out", () => {
    const fields = fieldsOf(daily);
    const sent = fieldValues(fields, { done: "Reviewed\nPRs", hours: "3.5", mood: "", tags: "a\n\n b \n", extra: '{"x":1}', billable: false });
    expect(sent).toEqual({ done: "Reviewed\nPRs", hours: 3.5, tags: ["a", "b"], extra: { x: 1 } });
  });

  it("round-trips what the app filled in", () => {
    const fields = fieldsOf(daily);
    const filled = { done: "Wrote the docs", hours: 2, mood: "good", billable: true, tags: ["docs"], extra: { a: [1] }, project_name: "handler" };
    expect(fieldValues(fields, formValues(fields, filled))).toEqual(filled);
  });

  it("refuses a required field left empty, a number or JSON that is not one", () => {
    const fields = fieldsOf(daily);
    expect(() => fieldValues(fields, { done: "  " })).toThrow("What you did: needed");
    expect(() => fieldValues(fields, { done: "x", hours: "two" })).toThrow("Hours: not a number");
    expect(() => fieldValues(fields, { done: "x", extra: "{" })).toThrow("Extra: not JSON");
  });

  it("sends a required checkbox even unticked", () => {
    const fields = fieldsOf({ type: "object", required: ["ok"], properties: { ok: { type: "boolean" } } });
    expect(fieldValues(fields, {})).toEqual({ ok: false });
  });
});

describe("how often it alerts", () => {
  it("steps from the app's to silent, stopping at each end", () => {
    expect(SETTINGS).toEqual(["default", "once", "silent"]);
    expect(less("default")).toBe("once");
    expect(less("once")).toBe("silent");
    expect(less("silent")).toBeNull();
    expect(more("silent")).toBe("once");
    expect(more("once")).toBe("default");
    expect(more("default")).toBeNull();
  });

  it("changed, is every open nudge of that app and name's, the others untouched", () => {
    const at = "2026-11-12T18:00:00Z";
    const of = (id: string, app: string, name: string, state: "open" | "done" = "open"): InboxMessage => ({
      id, source: "app", name: app, app, person: "owner", title: "t", at, kind: "nudge", nudge: { name, state, setting: "default" },
    });
    const inbox = [of("1", "worktracker", "daily-log"), of("2", "worktracker", "daily-log"), of("3", "worktracker", "daily-log", "done"), of("4", "worktracker", "weekly"), of("5", "coach", "daily-log")];
    const after = withSetting(inbox, "worktracker", "daily-log", "once");
    expect(after.map((m) => m.nudge?.setting)).toEqual(["once", "once", "default", "default", "default"]);
    expect(inbox[0]!.nudge?.setting).toBe("default");
  });
});

describe("an ended nudge", () => {
  it("says its state in words, an expired one what the app said happens", () => {
    expect(endedWords({ name: "n", state: "open" })).toBeNull();
    expect(endedWords({ name: "n" })).toBeNull();
    expect(endedWords({ name: "n", state: "done" })).toBe("Done");
    expect(endedWords({ name: "n", state: "dismissed" })).toBe("Dismissed");
    expect(endedWords({ name: "n", state: "expired" })).toBe("Expired");
    expect(endedWords({ name: "n", state: "expired", ifIgnored: "The day is logged as empty." })).toBe("Expired: The day is logged as empty.");
  });
});
