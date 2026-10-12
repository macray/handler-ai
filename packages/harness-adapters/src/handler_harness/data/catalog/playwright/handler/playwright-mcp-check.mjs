#!/usr/bin/env node
// The addon's rebuild check (contract G.4), run offline: the Playwright installed with Playwright
// MCP can still drive the toolbox's Chromium. A toolbox rebuild re-runs it, so a Chromium release
// that Playwright can no longer drive is caught before agents get it.
import { createRequire } from "node:module";

const require = createRequire("/opt/addons/playwright/node_modules/@playwright/mcp/package.json");
const { chromium } = require("playwright-core"); // the copy Playwright MCP itself uses

const browser = await chromium.launch({
  executablePath: "/usr/bin/chromium",
  headless: true,
  args: ["--disable-gpu", "--disable-dev-shm-usage"],
});
try {
  const page = await browser.newPage();
  await page.setContent("<h1>handler</h1>");
  const text = await page.textContent("h1");
  if (text !== "handler") throw new Error(`unexpected page content: ${text}`);
  console.log(`Playwright drives Chromium ${browser.version()}`);
} finally {
  await browser.close();
}
