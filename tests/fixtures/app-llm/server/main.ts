// Test app for secrets and egress (A2): /api/ask calls an OpenAI-compatible model with the key
// from the LLM_KEY secret. config.ts (the model's URL) is written by the test.
import { MODEL_URL, OTHER_URL } from "./config.ts";

async function ask(text: string): Promise<Response> {
  const r = await fetch(MODEL_URL, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${process.env.LLM_KEY}` },
    body: JSON.stringify({ model: "local", messages: [{ role: "user", content: text }] }),
  });
  const body = await r.json();
  return Response.json({ answer: body.choices[0].message.content });
}

export async function handle(req: Request): Promise<Response> {
  const url = new URL(req.url);
  if (url.pathname === "/api/health") return Response.json({ ok: true });
  if (url.pathname === "/api/ask") return ask((await req.json()).text);
  if (url.pathname === "/api/other") {
    try {
      const r = await fetch(OTHER_URL);
      return Response.json({ reached: r.ok, status: r.status, error: await r.text() });
    } catch (e) {
      return Response.json({ reached: false, error: String(e) });
    }
  }
  return new Response("not found", { status: 404 });
}

if (import.meta.main) {
  console.log(`starting with key ${process.env.LLM_KEY}`); // must not reach the log as is
  Bun.serve({ unix: process.env.HANDLER_APP_SOCKET!, fetch: handle });
}
