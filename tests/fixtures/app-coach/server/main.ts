// Test app for A5 (a coach, in miniature): an automation's call reads today's line from a host
// file and notifies; /api/checkin is a queued route (run later when the phone sends it while handler is off);
// /api/ask runs the agent given for its need "coach" (H.11), /api/cron/ask tries to from an automation's call.
import { readFile } from "node:fs/promises";
import { files, getRun, notify, runAgent } from "./handler.ts";

const checkins: string[] = [];

export async function handle(req: Request): Promise<Response> {
  const url = new URL(req.url);
  switch (`${req.method} ${url.pathname}`) {
    case "GET /api/health":
      return Response.json({ ok: true });
    case "POST /api/cron/morning": {
      const agenda = (await readFile(files().agenda, "utf8")).split("\n")[0];
      await notify("Today", { body: agenda });
      return Response.json({ automation: req.headers.get("x-handler-automation") });
    }
    case "POST /api/checkin": {
      const { text } = await req.json();
      checkins.push(`${req.headers.get("x-handler-person")}:${text}:${req.headers.get("idempotency-key") ?? ""}`);
      return Response.json({ ok: true });
    }
    case "GET /api/checkins":
      return Response.json(checkins);
    case "POST /api/ask":
    case "POST /api/cron/ask":
      try {
        const { request } = await req.json().catch(() => ({ request: "what now?" }));
        return Response.json({ ok: true, run: await runAgent(req, "coach", { fake: "valid", answer: { status: "attention", summary: request } }) });
      } catch (e) {
        return Response.json({ ok: false, error: String(e) });
      }
    case "GET /api/run":
      return Response.json(await getRun(url.searchParams.get("id")!));
    case "POST /api/tell-alice":
      try {
        await notify("hello", { person: "alice" });
        return Response.json({ ok: true });
      } catch (e) {
        return Response.json({ ok: false, error: String(e) });
      }
  }
  return new Response("not found", { status: 404 });
}

if (import.meta.main) {
  Bun.serve({ unix: process.env.HANDLER_APP_SOCKET!, fetch: handle });
}
