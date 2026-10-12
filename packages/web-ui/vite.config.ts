import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vitest/config";

// `vite dev` proxies the daemon (default port 7430), so the UI can be developed with hot reload.
const daemon = process.env.HANDLER_URL ?? "http://127.0.0.1:7430";

export default defineConfig({
  plugins: [tailwindcss(), svelte()],
  resolve: { alias: { $lib: fileURLToPath(new URL("./src/lib", import.meta.url)) } },
  // Served from localhost: one ~600 kB bundle (bits-ui, icons) is fine.
  // Built into the control plane's package: handlerd serves it from there, from a checkout and from the
  // installed wheel alike (packaging/).
  build: {
    outDir: "../control-plane/src/handler_control/web-ui",
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 800,
  },
  server: {
    proxy: { "/v1": { target: daemon, ws: true } },
  },
  test: {
    environment: "happy-dom",
    include: ["tests/**/*.test.ts"],
    // Tests feed hostile HTML to the sanitizer: the DOM emulation must never fetch anything.
    environmentOptions: {
      happyDOM: {
        settings: {
          disableIframePageLoading: true,
          disableJavaScriptFileLoading: true,
          disableCSSFileLoading: true,
          navigation: { disableChildFrameNavigation: true, disableChildPageNavigation: true },
        },
      },
    },
  },
});
