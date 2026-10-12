// Entry point. handler runs `deno run server/main.ts` in a sandbox with:
//   HANDLER_APP_DATA  the app's data folder (read-write, kept across versions)
//   HANDLER_APP_SOCKET  the Unix socket to serve on (handler forwards /api/… of the app's address here)
// Without HANDLER_APP_SOCKET (`deno task dev`), it serves on 127.0.0.1:8787 for the UI's dev server.
import { openDb } from "./db.ts";
import { handle } from "./routes.ts";

const data = Deno.env.get("HANDLER_APP_DATA") ?? ".data";
Deno.mkdirSync(data, { recursive: true });
const db = openDb(`${data}/app.db`);
const socket = Deno.env.get("HANDLER_APP_SOCKET");
const serve = (req: Request) => handle(db, req);

if (socket) {
  Deno.serve({ transport: "unix", path: socket }, serve);
} else {
  Deno.serve({ hostname: "127.0.0.1", port: 8787 }, serve);
}
