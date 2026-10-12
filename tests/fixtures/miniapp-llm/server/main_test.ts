import { handle } from "./main.ts";

Deno.test("health", async () => {
  const r = await handle(new Request("http://app/api/health"));
  if (r.status !== 200) throw new Error(`health ${r.status}`);
  if (Deno.env.get("LLM_KEY") !== undefined) throw new Error("tests must not get secrets");
});
