// Backend of the test app: migrations on start, then /api/health, /api/count, /api/whoami.
import { DatabaseSync } from "node:sqlite";

export function open(dir: string): DatabaseSync {
  const db = new DatabaseSync(`${dir}/app.db`);
  const done = (db.prepare("PRAGMA user_version").get() as { user_version: number }).user_version;
  const files = [...Deno.readDirSync(new URL("./migrations/", import.meta.url))]
    .map((e) => e.name).filter((n) => n.endsWith(".sql")).sort();
  files.slice(done).forEach((name, i) => {
    db.exec(Deno.readTextFileSync(new URL(`./migrations/${name}`, import.meta.url)));
    db.exec(`PRAGMA user_version = ${done + i + 1}`);
  });
  return db;
}

export function handler(db: DatabaseSync): (req: Request) => Response {
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
    return new Response("not found", { status: 404 });
  };
}

if (import.meta.main) {
  const db = open(Deno.env.get("HANDLER_APP_DATA")!);
  Deno.serve({ transport: "unix", path: Deno.env.get("HANDLER_APP_SOCKET")! }, handler(db));
}
