import { test } from "bun:test";
import { handle } from "./main.ts";

test("health", async () => {
  if ((await handle(new Request("http://app/api/health"))).status !== 200) throw new Error("health");
});
