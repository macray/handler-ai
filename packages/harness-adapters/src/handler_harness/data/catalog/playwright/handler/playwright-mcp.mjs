#!/usr/bin/env node
// handler wrapper around Playwright MCP (docs/dev/design/browser.md §6), the addon's MCP server
// (stdio).
//
// - Headed only when the sandbox was given a display (contract A.6: WAYLAND_DISPLAY is set by the
//   sandbox, never by the agent), unless the binding asks for headless. Headless otherwise, so the
//   same addon serves agents without a display.
// - The toolbox's Chromium, an in-memory profile (--isolated): nothing survives the session.
// - The browser's traffic goes through the sandbox's proxy when there is one (filtered network):
//   read from the env the sandbox sets, so the platform never has to know proxy details (B2).
// - A storage state from the binding (cookies of a dedicated account) is written to a private file.
// Arguments are passed through to Playwright MCP.
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PREFIX = "/opt/addons/playwright";
const CLI = join(PREFIX, "lib", "mcp-cli.js"); // Playwright MCP's own entry point (see Containerfile)
const CHROMIUM = "/usr/bin/chromium"; // the toolbox's

const env = process.env;
const dir = mkdtempSync(join(tmpdir(), "playwright-mcp-")); // 0700
const headed = Boolean(env.WAYLAND_DISPLAY) && env.HANDLER_PLAYWRIGHT_HEADLESS !== "1";

// No GPU in a sandbox; /dev/shm is small in containers. Chromium's own sandbox cannot start under
// `strict` confinement: Playwright already passes --no-sandbox (its default).
const chromiumArgs = ["--disable-gpu", "--disable-dev-shm-usage"];
if (headed) chromiumArgs.push("--ozone-platform=wayland");
const config = {
  browser: {
    browserName: "chromium",
    launchOptions: { executablePath: CHROMIUM, headless: !headed, args: chromiumArgs },
  },
};
const configFile = join(dir, "config.json");
writeFileSync(configFile, JSON.stringify(config), { mode: 0o600 });

const args = ["--config", configFile, "--isolated", "--output-dir", join(dir, "output")];
const proxy = env.HTTPS_PROXY || env.https_proxy;
if (proxy) {
  args.push("--proxy-server", proxy);
  const bypass = env.NO_PROXY || env.no_proxy;
  if (bypass) args.push("--proxy-bypass", bypass);
}
if (env.HANDLER_PLAYWRIGHT_STORAGE_STATE) {
  const state = join(dir, "storage-state.json");
  writeFileSync(state, env.HANDLER_PLAYWRIGHT_STORAGE_STATE, { mode: 0o600 });
  args.push("--storage-state", state);
}

const child = spawn(process.execPath, [CLI, ...args, ...process.argv.slice(2)], {
  stdio: "inherit",
});
for (const signal of ["SIGTERM", "SIGINT", "SIGHUP"]) {
  process.on(signal, () => child.kill(signal));
}
child.on("exit", (code, signal) => {
  rmSync(dir, { recursive: true, force: true });
  process.exit(code ?? (signal ? 128 : 1));
});
