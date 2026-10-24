import { test } from "bun:test";
import { handle } from "./main.ts";

test("health", async () => {
  const r = await handle(new Request("http://app/api/health"));
  if (r.status !== 200) throw new Error(`health ${r.status}`);
  if (process.env.LLM_KEY !== undefined) throw new Error("tests must not get secrets");
});
