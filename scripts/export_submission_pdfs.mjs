// Export the submission PDFs (architecture diagram + presentation) from their HTML/SVG sources.
//
// Usage (needs Node 18+ and any Chrome/Chromium):
//   npm install --no-save puppeteer-core            # in any scratch folder, or use `npx -p puppeteer-core`
//   CHROME_PATH=/path/to/chrome node scripts/export_submission_pdfs.mjs [repoRoot]
//
// Sources: docs/submission/src/{architecture.html,presentation.html,architecture.svg}
// Outputs: docs/submission/GlucoTwin_Architecture.pdf, docs/submission/GlucoTwin_Presentation.pdf
import path from "node:path";
import { pathToFileURL } from "node:url";
import puppeteer from "puppeteer-core";

const root = path.resolve(process.argv[2] || ".");
const exe = process.env.CHROME_PATH;
if (!exe) throw new Error("Set CHROME_PATH to a Chrome/Chromium executable");
const extraArgs = (process.env.CHROME_ARGS || "").split(" ").filter(Boolean);
const browser = await puppeteer.launch({ executablePath: exe, headless: true, args: ["--no-sandbox", ...extraArgs] });
const jobs = [
  ["architecture.html", "GlucoTwin_Architecture.pdf", { width: "1600px", height: "900px" }],
  ["presentation.html", "GlucoTwin_Presentation.pdf", { width: "1280px", height: "720px" }],
];
for (const [src, out, size] of jobs) {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("requestfailed", (r) => errors.push(`failed: ${r.url()}`));
  await page.goto(pathToFileURL(path.join(root, "docs/submission/src", src)).href, { waitUntil: "networkidle0" });
  await page.pdf({ path: path.join(root, "docs/submission", out), printBackground: true, ...size, pageRanges: "" });
  console.log(`${out}: ${errors.length ? "ERRORS " + JSON.stringify(errors) : "ok"}`);
  await page.close();
}
await browser.close();
