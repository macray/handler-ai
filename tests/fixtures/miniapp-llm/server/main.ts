// Test app for secrets and egress (A2): /api/ask calls an OpenAI-compatible model with the key
// from the LLM_KEY secret. config.ts (the model's URL) is written by the test.
import { MODEL_URL, OTHER_URL } from "./config.ts";

async function ask(text: string): Promise<Response> {
  const r = await fetch(MODEL_URL, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${Deno.env.get("LLM_KEY")}` },
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
      await fetch(OTHER_URL);
      return Response.json({ reached: true });
    } catch (e) {
      return Response.json({ reached: false, error: String(e) });
    }
  }
  return new Response("not found", { status: 404 });
}

if (import.meta.main) {
  console.log(`starting with key ${Deno.env.get("LLM_KEY")}`); // must not reach the log as is
  Deno.serve({ transport: "unix", path: Deno.env.get("HANDLER_APP_SOCKET")! }, handle);
}
