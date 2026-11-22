// Test app for an app's jobs (H.1, H.11): /api/write starts a run of its job "write" while it
// answers the owner; /api/run reads it again, /api/runs lists its runs; POST /api/ended is the
// job's `then` (each call kept with who asked, GET /api/ended lists them).
const ended: Record<string, unknown>[] = [];

async function call(method: string, path: string, payload?: unknown): Promise<[number, Record<string, unknown>]> {
  const res = await fetch(`http://handler${path}`, {
    method,
    unix: process.env.HANDLER_APP_API!,
    headers: { "content-type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  return [res.status, (await res.json().catch(() => ({}))) as Record<string, unknown>];
}

export async function handle(req: Request): Promise<Response> {
  const url = new URL(req.url);
  switch (`${req.method} ${url.pathname}`) {
    case "GET /api/health":
      return Response.json({ ok: true });
    case "POST /api/write": {
      const fields = await req.json();
      const start = req.headers.get("x-handler-start") ?? "";
      const [status, run] = await call("POST", "/runs", { job: "write", fields, start });
      return Response.json({ status, run });
    }
    case "GET /api/run": {
      const [, run] = await call("GET", `/runs/${encodeURIComponent(url.searchParams.get("id")!)}`);
      return Response.json(run);
    }
    case "GET /api/runs": {
      const [, runs] = await call("GET", "/runs");
      return Response.json(runs);
    }
    case "POST /api/ended": {
      const person = req.headers.get("x-handler-person");
      ended.push({ body: await req.json(), person, start: req.headers.get("x-handler-start") });
      return Response.json({ ignored: "its body" });
    }
    case "GET /api/ended":
      return Response.json({ ended });
  }
  return new Response("not found", { status: 404 });
}

if (import.meta.main) {
  Bun.serve({ unix: process.env.HANDLER_APP_SOCKET!, fetch: handle });
}
