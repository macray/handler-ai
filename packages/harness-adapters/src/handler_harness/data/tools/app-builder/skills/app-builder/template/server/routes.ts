// The backend's routes, all under /api/. GET /api/health must answer 200 once the app is ready:
// handler waits for it after starting the backend, and a deploy fails without it.
// `X-HANDLER-Person` says who uses the app (set by handler, cannot be forged by the page): keep data per
// person when it is personal.
import type { Database } from "bun:sqlite";
import type { ActionResult, JobEnded } from "./handler.ts";

type Note = { id: number; text: string; createdAt: string };

export async function handle(db: Database, req: Request): Promise<Response> {
  const url = new URL(req.url);
  const person = req.headers.get("x-handler-person") ?? "owner";
  switch (`${req.method} ${url.pathname}`) {
    case "GET /api/health":
      return Response.json({ ok: true });
    case "GET /api/notes":
      return Response.json(listNotes(db, person));
    case "POST /api/notes": {
      const body = (await req.json().catch(() => null)) as { text?: unknown } | null;
      const text = typeof body?.text === "string" ? body.text.trim() : "";
      if (!text) return Response.json({ error: "text is required" }, { status: 400 });
      addNote(db, person, text);
      return Response.json(listNotes(db, person), { status: 201 });
    }
    // the action `add` (app.toml): its fields, already checked against its form, as the owner
    case "POST /api/actions/add": {
      const text = ((await req.json()) as { text: string }).text.trim();
      if (!text) return Response.json({ status: "failed", summary: "The note is empty." } satisfies ActionResult);
      addNote(db, person, text);
      return Response.json({ status: "ok", summary: `Noted: ${text}` } satisfies ActionResult);
    }
    // the job `draft`'s `then`: called once when one of its runs ended; it saves the note the
    // job gave back (the job writes nothing itself)
    case "POST /api/drafts/ended": {
      const ended = (await req.json()) as JobEnded<{ note?: unknown }>;
      const note = typeof ended.result?.note === "string" ? ended.result.note.trim() : "";
      if (ended.state === "succeeded" && note) addNote(db, person, note);
      return Response.json({ ok: true });
    }
  }
  return Response.json({ error: "not found" }, { status: 404 });
}

function addNote(db: Database, person: string, text: string): void {
  db.query("INSERT INTO notes (person, text) VALUES (?, ?)").run(person, text);
}

function listNotes(db: Database, person: string): Note[] {
  return db
    .query("SELECT id, text, created_at AS createdAt FROM notes WHERE person = ? ORDER BY id DESC")
    .all(person) as Note[];
}
