// What the backend may ask handler (the template's copy): notifications, the host files it was given.
export function files(): string[] {
  return JSON.parse(Deno.env.get("HANDLER_APP_FILES") ?? "[]");
}

/** Tell a person (the owner by default): on the computer and, content-free, on their phones. */
export async function notify(title: string, opts: { body?: string; person?: string } = {}): Promise<void> {
  const path = Deno.env.get("HANDLER_APP_API");
  if (!path) throw new Error("add `notify = true` to [needs] in app.toml");
  const body = new TextEncoder().encode(JSON.stringify({ title, ...opts }));
  const conn = await Deno.connect({ transport: "unix", path });
  try {
    const head = `POST /notify HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: ${body.length}\r\n\r\n`;
    await conn.write(new TextEncoder().encode(head));
    await conn.write(body);
    const answer = await new Response(conn.readable).text();
    const status = Number(answer.split(" ", 2)[1]);
    if (status !== 200) throw new Error(`notify: ${answer.split("\r\n\r\n")[1] ?? status}`);
  } finally {
    try {
      conn.close();
    } catch {
      /* closed by the answer */
    }
  }
}
