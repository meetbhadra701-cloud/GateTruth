import { createServer } from "node:http";
import { mkdir, readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const root = path.resolve(process.env.SILICONBENCH_TOUR_BUILD || "site/build-tour");
const screenshotRoot = process.env.SILICONBENCH_TOUR_SCREENSHOTS;

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function contentType(filename) {
  if (filename.endsWith(".html")) return "text/html; charset=utf-8";
  if (filename.endsWith(".json")) return "application/json; charset=utf-8";
  return "application/octet-stream";
}

const server = createServer(async (request, response) => {
  try {
    const pathname = new URL(request.url, "http://localhost").pathname;
    const relative = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
    const target = path.resolve(root, relative);
    assert(target.startsWith(root), "request escaped build root");
    const body = await readFile(target);
    response.writeHead(200, { "content-type": contentType(target) });
    response.end(body);
  } catch (_error) {
    response.writeHead(404);
    response.end("not found");
  }
});

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const address = server.address();
const url = `http://127.0.0.1:${address.port}/`;
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const browser = await chromium.launch({
  headless: true,
  ...(executablePath ? { executablePath } : {}),
});

async function freshContext(viewport) {
  return browser.newContext({ viewport });
}

async function assertInsideViewport(page, viewport) {
  const box = await page.locator(".sb-tour-tooltip").boundingBox();
  assert(box, "tour tooltip is not visible");
  assert(box.x >= 0, `tooltip overflows left: ${JSON.stringify(box)}`);
  assert(box.y >= 0, `tooltip overflows top: ${JSON.stringify(box)}`);
  assert(box.x + box.width <= viewport.width, `tooltip overflows right: ${JSON.stringify(box)}`);
  assert(box.y + box.height <= viewport.height, `tooltip overflows bottom: ${JSON.stringify(box)}`);
}

try {
  {
    const context = await freshContext({ width: 1440, height: 900 });
    const page = await context.newPage();
    await page.goto(url);
    await page.locator(".sb-tour-tooltip").waitFor({ state: "visible" });
    assert(await page.locator(".sb-tour-step").textContent() === "Step 1 of 6", "fresh profile did not start six-step tour");
    await page.locator(".sb-tour-skip").click();
    assert(await page.evaluate(() => localStorage.getItem("has_seen_tour")) === "true", "Skip did not persist the tour key");
    await page.reload();
    assert(await page.locator(".sb-tour-tooltip").isHidden(), "tour appeared on second load");
    await context.close();
    console.log("PASS fresh profile, persisted Skip, second-load gate");
  }

  {
    const context = await freshContext({ width: 1440, height: 900 });
    const page = await context.newPage();
    await page.goto(url);
    await page.locator(".sb-tour-tooltip").waitFor({ state: "visible" });
    await page.keyboard.press("Escape");
    assert(await page.locator(".sb-tour-tooltip").isHidden(), "Escape did not close the tour");
    assert(await page.evaluate(() => localStorage.getItem("has_seen_tour")) === "true", "Escape did not persist the tour key");
    await context.close();
    console.log("PASS Escape close");
  }

  for (const viewport of [{ width: 360, height: 740 }, { width: 1440, height: 900 }]) {
    const context = await freshContext(viewport);
    const page = await context.newPage();
    await page.goto(url);
    await page.locator(".sb-tour-tooltip").waitFor({ state: "visible" });
    if (screenshotRoot) {
      await mkdir(screenshotRoot, { recursive: true });
      await page.screenshot({
        path: path.join(screenshotRoot, `tour-${viewport.width}x${viewport.height}.png`),
        fullPage: true,
      });
    }
    for (let step = 0; step < 6; step += 1) {
      await assertInsideViewport(page, viewport);
      const activeInside = await page.evaluate(() => document.querySelector(".sb-tour-tooltip").contains(document.activeElement));
      assert(activeInside, `focus escaped tooltip at ${viewport.width}px step ${step + 1}`);
      await page.locator(".sb-tour-next").click();
      if (step < 5) await page.locator(".sb-tour-tooltip").waitFor({ state: "visible" });
    }
    assert(await page.locator(".sb-tour-tooltip").isHidden(), "Done did not close the tour");
    await context.close();
    console.log(`PASS viewport ${viewport.width}x${viewport.height}, six steps in bounds`);
  }
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}

console.log("4 Playwright onboarding checks passed");
