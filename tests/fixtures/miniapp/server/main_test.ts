import { handler, open } from "./main.ts";

Deno.test("counts", async () => {
  const db = open(Deno.env.get("HANDLER_APP_DATA")!);
  const h = handler(db);
  h(new Request("http://app/api/count", { method: "POST" }));
  const body = await h(new Request("http://app/api/count")).json();
  if (body.n !== 1) throw new Error(`expected 1, got ${body.n}`);
});
