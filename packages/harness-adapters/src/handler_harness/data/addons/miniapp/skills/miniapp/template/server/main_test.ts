// Run by `deno task test`, and by handler before every deploy (the deploy fails if a test fails).
// Tests get no network and may only write in HANDLER_APP_DATA: use an in-memory database.
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

Deno.test("health answers once migrated", async () => {
  const res = await call(openDb(":memory:"), "GET", "/api/health");
  if (res.status !== 200) throw new Error(`health: ${res.status}`);
});

Deno.test("adds and lists notes", async () => {
  const db = openDb(":memory:");
  const created = await call(db, "POST", "/api/notes", { text: "buy milk" });
  if (created.status !== 201) throw new Error(`create: ${created.status}`);
  const notes = await (await call(db, "GET", "/api/notes")).json();
  if (notes.length !== 1 || notes[0].text !== "buy milk") throw new Error(JSON.stringify(notes));
});

Deno.test("refuses an empty note", async () => {
  const res = await call(openDb(":memory:"), "POST", "/api/notes", { text: " " });
  if (res.status !== 400) throw new Error(`empty: ${res.status}`);
});
