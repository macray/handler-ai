// Run by `bun test`, and by handler before every deploy (the deploy fails if a test fails).
// Tests get no network and may only write in HANDLER_APP_DATA: use an in-memory database.
import { expect, test } from "bun:test";
import { openDb } from "./db.ts";
import { handle } from "./routes.ts";

const call = (db: ReturnType<typeof openDb>, method: string, path: string, body?: unknown) =>
  handle(
    db,
    new Request(`http://app${path}`, {
      method,
      headers: { "x-handler-person": "owner" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  );

test("health answers once migrated", async () => {
  const res = await call(openDb(":memory:"), "GET", "/api/health");
  expect(res.status).toBe(200);
});

test("adds and lists notes", async () => {
  const db = openDb(":memory:");
  const created = await call(db, "POST", "/api/notes", { text: "buy milk" });
  expect(created.status).toBe(201);
  const notes = (await (await call(db, "GET", "/api/notes")).json()) as { text: string }[];
  expect(notes).toHaveLength(1);
  expect(notes[0].text).toBe("buy milk");
});

test("refuses an empty note", async () => {
  const res = await call(openDb(":memory:"), "POST", "/api/notes", { text: " " });
  expect(res.status).toBe(400);
});

test("the action add answers in a sentence", async () => {
  const db = openDb(":memory:");
  const res = await call(db, "POST", "/api/actions/add", { text: "call the bank" });
  expect(await res.json()).toEqual({ status: "ok", summary: "Noted: call the bank" });
  const empty = await call(db, "POST", "/api/actions/add", { text: " " });
  expect(((await empty.json()) as { status: string }).status).toBe("failed");
});

test("the job draft's then saves the note it gave back, and nothing when it failed", async () => {
  const db = openDb(":memory:");
  const ended = (state: string, result: unknown) =>
    call(db, "POST", "/api/drafts/ended", { runId: "r_1", job: "draft", state, fields: { request: "kettle" }, result });
  expect((await ended("succeeded", { status: "ok", summary: "On the kettle.", note: "Descale it monthly" })).status).toBe(200);
  expect((await ended("failed", null)).status).toBe(200);
  const notes = (await (await call(db, "GET", "/api/notes")).json()) as { text: string }[];
  expect(notes.map((n) => n.text)).toEqual(["Descale it monthly"]);
});
