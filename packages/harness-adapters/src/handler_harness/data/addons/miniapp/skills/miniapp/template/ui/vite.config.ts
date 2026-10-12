import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [svelte()],
  // dev: the backend runs with `deno task dev` in server/
  server: { host: "127.0.0.1", port: 5173, proxy: { "/api": "http://127.0.0.1:8787" } },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // One script, one stylesheet, images and fonts inside them: on a phone, handler sends the app as
    // a single page (no file can be fetched there). Keep it that way: no dynamic import().
    assetsInlineLimit: 100_000_000,
    cssCodeSplit: false,
    rollupOptions: { output: { inlineDynamicImports: true } },
  },
});
