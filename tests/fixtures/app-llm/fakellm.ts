// A fake OpenAI-compatible model server (run in a container on the podman network).
Bun.serve({
  hostname: "0.0.0.0",
  port: 8000,
  async fetch(req) {
    const body = (await req.json()) as { messages: { content: string }[] };
    const content = `echo:${body.messages.at(-1)!.content} auth:${req.headers.get("authorization")}`;
    return Response.json({ choices: [{ message: { role: "assistant", content } }] });
  },
});
