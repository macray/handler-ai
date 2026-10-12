import tailwindcss from "@tailwindcss/vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vitest/config";

// `vite dev` proxies a gateway (HANDLER_GATEWAY_URL, default 127.0.0.1:7431): the client calls its
// own origin, as when the gateway serves it.
const gateway = process.env.HANDLER_GATEWAY_URL ?? "http://127.0.0.1:7431";

export default defineConfig({
  plugins: [tailwindcss(), svelte()],
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
  server: { proxy: { "/v1": { target: gateway } } },
  test: { environment: "happy-dom", include: ["tests/**/*.test.ts"] },
});
