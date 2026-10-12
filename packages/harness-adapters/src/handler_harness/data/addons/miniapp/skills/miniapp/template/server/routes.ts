// The backend's routes, all under /api/. GET /api/health must answer 200 once the app is ready:
// handler waits for it after starting the backend, and a deploy fails without it.
// `X-HANDLER-Person` says who uses the app (set by handler, cannot be forged by the page): keep data per
// person when it is personal.
import type { DatabaseSync } from "node:sqlite";

type Note = { id: number; text: string; createdAt: string };

export async function handle(db: DatabaseSync, req: Request): Promise<Response> {
  const url = new URL(req.url);
  const person = req.headers.get("x-handler-person") ?? "owner";
  switch (`${req.method} ${url.pathname}`) {
    case "GET /api/health":
      return Response.json({ ok: true });
    case "GET /api/notes":
      return Response.json(listNotes(db, person));
    case "POST /api/notes": {
      const body = await req.json().catch(() => null);
      const text = typeof body?.text === "string" ? body.text.trim() : "";
      if (!text) return Response.json({ error: "text is required" }, { status: 400 });
      db.prepare("INSERT INTO notes (person, text) VALUES (?, ?)").run(person, text);
      return Response.json(listNotes(db, person), { status: 201 });
    }
  }
  return Response.json({ error: "not found" }, { status: 404 });
}

function listNotes(db: DatabaseSync, person: string): Note[] {
  return db
    .prepare("SELECT id, text, created_at AS createdAt FROM notes WHERE person = ? ORDER BY id DESC")
    .all(person) as Note[];
}
