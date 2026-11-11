// Entry point. handler runs `bun run server/main.ts` in a sandbox with:
//   HANDLER_APP_DATA  the app's data folder (read-write, kept across versions)
//   HANDLER_APP_SOCKET  the Unix socket to serve on (handler forwards /api/… of the app's address here)
// Without HANDLER_APP_SOCKET (`bun run dev`), it serves on 127.0.0.1:8787 for the UI's dev server.
import { mkdirSync } from "node:fs";
import { openDb } from "./db.ts";
import { handle } from "./routes.ts";

const data = process.env.HANDLER_APP_DATA ?? ".data";
mkdirSync(data, { recursive: true });
const db = openDb(`${data}/app.db`);
const socket = process.env.HANDLER_APP_SOCKET;
const fetch = (req: Request) => handle(db, req);

if (socket) {
  Bun.serve({ unix: socket, fetch });
} else {
  Bun.serve({ hostname: "127.0.0.1", port: 8787, fetch });
}
