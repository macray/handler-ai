// Backend of the test app: migrations on start, then /api/health, /api/count, /api/whoami, and
// the action /api/actions/count (H.12: it answers how it went in a sentence).
import { Database } from "bun:sqlite";
import { readdirSync, readFileSync } from "node:fs";

export function open(dir: string): Database {
  const db = new Database(`${dir}/app.db`);
  const done = (db.prepare("PRAGMA user_version").get() as { user_version: number }).user_version;
  const files = readdirSync(`${import.meta.dir}/migrations`).filter((n) => n.endsWith(".sql")).sort();
  files.slice(done).forEach((name, i) => {
    db.run(readFileSync(`${import.meta.dir}/migrations/${name}`, "utf8"));
    db.run(`PRAGMA user_version = ${done + i + 1}`);
  });
  return db;
}

export function handler(db: Database): (req: Request) => Response {
  return (req) => {
    const url = new URL(req.url);
    if (url.pathname === "/api/health") return Response.json({ ok: true });
    if (url.pathname === "/api/whoami") {
      return Response.json({ person: req.headers.get("x-handler-person"), cookie: req.headers.get("cookie") });
    }
    if (url.pathname === "/api/count") {
      if (req.method === "POST") db.prepare("UPDATE counter SET n = n + 1").run();
      return Response.json(db.prepare("SELECT n FROM counter").get());
    }
    if (url.pathname === "/api/actions/count" && req.method === "POST") {
      db.prepare("UPDATE counter SET n = n + 1").run();
      const { n } = db.prepare("SELECT n FROM counter").get() as { n: number };
      return Response.json({ status: "ok", summary: `Counted: ${n}.` });
    }
    return new Response("not found", { status: 404 });
  };
}

if (import.meta.main) {
  const db = open(process.env.HANDLER_APP_DATA!);
  Bun.serve({ unix: process.env.HANDLER_APP_SOCKET!, fetch: handler(db) });
}
