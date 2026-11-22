import tailwindcss from "@tailwindcss/vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

/** The built page paints its skeleton (index.html) before the app's files arrive: Vite puts its
 *  stylesheet and module script in <head>, where the stylesheet holds the first paint; they go
 *  to the end of <body> instead, stylesheet first (the script still runs once it is there). */
function paintFirst(): Plugin {
  return {
    name: "paint-first",
    apply: "build",
    transformIndexHtml: {
      order: "post",
      handler(html) {
        const moved: string[] = [];
        const take = (re: RegExp) =>
          (html = html.replace(re, (tag) => {
            moved.push(tag.trim());
            return "";
          }));
        take(/\s*<link rel="stylesheet"[^>]*>/g);
        take(/\s*<link rel="modulepreload"[^>]*>/g);
        take(/\s*<script type="module"[^>]*><\/script>/g);
        return html.replace("</body>", `    ${moved.join("\n    ")}\n  </body>`);
      },
    },
  };
}

/** The service worker (public/sw.js) keeps the client's files for opening offline: the build
 *  writes into it their list (the page as `/`) and a version from their contents, so a new build
 *  is a new worker with a cache of its own. Written before precompress makes its `.br`/`.gz`. */
function offlineShell(): Plugin {
  let outDir = "";
  return {
    name: "offline-shell",
    apply: "build",
    configResolved(config) {
      outDir = resolve(config.root, config.build.outDir);
    },
    closeBundle() {
      const all = (dir: string): string[] =>
        readdirSync(dir).flatMap((name) => (statSync(join(dir, name)).isDirectory() ? all(join(dir, name)) : [join(dir, name)]));
      const paths = all(outDir)
        .map((path) => `/${relative(outDir, path)}`)
        .filter((path) => path !== "/sw.js" && !/\.(br|gz)$/.test(path))
        .sort();
      const hash = createHash("sha256");
      for (const path of paths) hash.update(path).update(readFileSync(join(outDir, path)));
      const files = paths.map((path) => (path === "/index.html" ? "/" : path));
      const sw = join(outDir, "sw.js");
      const empty = 'const BUILD = { version: "dev", files: [] };';
      const source = readFileSync(sw, "utf8");
      if (!source.includes(empty)) throw new Error("public/sw.js: its BUILD line is not where the build writes it");
      const build = { version: hash.digest("hex").slice(0, 16), files };
      writeFileSync(sw, source.replace(empty, `const BUILD = ${JSON.stringify(build)};`));
    },
  };
}

// `vite dev` proxies a gateway (HANDLER_GATEWAY_URL, default 127.0.0.1:7431): the client calls its
// own origin, as when the gateway serves it.
const gateway = process.env.HANDLER_GATEWAY_URL ?? "http://127.0.0.1:7431";

export default defineConfig({
  plugins: [tailwindcss(), svelte(), paintFirst(), offlineShell()],
  // Under vitest, Svelte's browser build: the tests mount components in happy-dom.
  ...(process.env.VITEST ? { resolve: { conditions: ["browser"] } } : {}),
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
  server: { proxy: { "/v1": { target: gateway } } },
  test: {
    environment: "happy-dom",
    // A test page names the client's module script without running it (update.test.ts): happy-dom
    // does not load scripts, and must not report that as an error.
    environmentOptions: { happyDOM: { settings: { handleDisabledFileLoadingAsSuccess: true } } },
    include: ["tests/**/*.test.ts"],
  },
});
