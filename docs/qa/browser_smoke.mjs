// Browser smoke test for the GlucoTwin dashboard (live app or static snapshot). QA tool, not run in CI:
// it needs puppeteer-core and a Chromium binary, which are NOT project dependencies.
//   mkdir -p /tmp/shot && cd /tmp/shot && npm i puppeteer-core@24 && cp <repo>/docs/qa/browser_smoke.mjs .
//   CHROME_PATH=/path/to/chromium CHROME_ARGS="--no-sandbox" OUT=/tmp/shot \
//     BASE_URL=http://127.0.0.1:8080/<sub-path>/ node browser_smoke.mjs              # static build (dist-static)
//   MODE=live BASE_URL=http://127.0.0.1:4173/ node browser_smoke.mjs                 # make serve + npm run preview
// Exit code 0 only when every check passes; each check prints PASS/FAIL.
import puppeteer from "puppeteer-core";
const BASE = process.env.BASE_URL;
const OUT = process.env.OUT ?? "/tmp/shot";
const LIVE = process.env.MODE === "live";
const P = LIVE ? "live" : "static";
const browser = await puppeteer.launch({ executablePath: process.env.CHROME_PATH, args: process.env.CHROME_ARGS.split(" "), headless: true });
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 1100 });
const problems = [];
page.on("console", (m) => { if (m.type() === "error") problems.push("console: " + m.text()); });
page.on("pageerror", (e) => problems.push("pageerror: " + e.message));
page.on("response", (r) => { if (r.status() >= 400) problems.push(`HTTP ${r.status()} ${r.url()}`); });
page.on("requestfailed", (r) => problems.push(`failed ${r.url()} ${r.failure()?.errorText}`));
const results = [];
const ok = (name, cond, detail = "") => { results.push(`${cond ? "PASS" : "FAIL"} ${name}${detail ? " — " + detail : ""}`); };
const text = (sel) => page.$eval(sel, (e) => e.textContent ?? "");
const waitText = (sel, s, timeout = 15000) => page.waitForFunction((sel, s) => [...document.querySelectorAll(sel)].some((e) => e.textContent.includes(s)), { timeout }, sel, s);
async function setGrams(g) { const i = await page.$('input[aria-label="Hypothetical meal carbs in grams"]'); await i.click({ clickCount: 3 }); await i.type(String(g)); }
async function clickButton(label) { const [b] = await page.$$(`xpath/.//button[contains(., "${label}")]`); await b.click(); }
const rows = () => page.$$eval(".sim-table tbody tr", (rs) => rs.map((r) => r.textContent));

// 1. landing page
await page.goto(BASE, { waitUntil: "networkidle0" });
if (LIVE) { await page.waitForSelector(".pt", { timeout: 15000 }); ok("live build has no static banner", (await page.$(".static-banner")) === null);
  ok("live API lists 12 held-out patients", (await page.$$(".pt")).length === 12); }
else { await page.waitForSelector(".static-banner", { timeout: 15000 });
const banner = await text(".static-banner");
ok("banner states snapshot / not live / not computed", /Static recorded snapshot, not a live system/.test(banner) && /Nothing is computed in your browser/.test(banner), banner.slice(0, 160));
ok("banner shows model version + both scenarios", /gt-0\.1\.0/.test(banner) && /early warning/i.test(banner) && /weakness|missed/i.test(banner)); }
await page.screenshot({ path: `${OUT}/${P}-1-landing.png` });

// 2. early-warning scenario at 07:55
await page.goto(BASE + "?patient=SYN-0039&start=151.833", { waitUntil: "networkidle0" });
await waitText(".clock", "07:55");
ok("SYN-0039 replay starts 07:55 local", (await text(".clock")).includes("07:55"), await text(".clock"));
const body = await page.$eval("body", (b) => b.innerText);
ok("personalisation equation visible", /observed mean ≈/.test(body) || (await page.$(".personal-rule")) !== null);
ok("risk 22% shown at 07:55", /22\s?%/.test(body));
await page.select('select[aria-label^="Indian meal preset"]', "idli2");
await clickButton("Simulate meal");
await page.waitForSelector(".sim-table tbody tr");
let r = await rows();
ok("preset what-if recorded and labelled", r[0].includes("35 g") && r[0].includes("Idli"), r[0].slice(0, 90));
await setGrams(120); await clickButton("Add scenario"); await page.waitForFunction(() => document.querySelectorAll(".sim-table tbody tr").length === 2);
await setGrams(300); await clickButton("Add scenario"); await page.waitForFunction(() => document.querySelectorAll(".sim-table tbody tr").length === 3);
r = await rows();
ok("120 g within support (no chip), risk 99.9%", !r[1].includes("outside training support") && /99\.9\s?%|>99|100/.test(r[1]), r[1]);
const chip = await page.$eval(".sim-table tbody tr:nth-child(3) .sim-support", (e) => [e.textContent, e.title]).catch(() => null);
ok("300 g flagged 'outside training support' with API reason", chip && chip[0] === "outside training support" && /more carbs in the last 30 min/.test(chip[1]), chip?.[1]);
await page.screenshot({ path: `${OUT}/${P}-2-whatif-0755.png`, fullPage: true });
await setGrams(77); await clickButton("Add scenario");
if (LIVE) { await page.waitForFunction(() => document.querySelectorAll(".sim-table tbody tr").length === 4);
  ok("live: any amount (77 g) is computed", (await rows())[3].includes("77 g")); }
else { await waitText(".sim-error", "no recorded what-if for 77 g");
ok("unrecorded amount -> explicit message, no invented row", (await rows()).length === 3, await text(".sim-error")); }

// 3. step 1 h -> 08:55, the 140 g breakfast was logged at 08:53
await clickButton("+1 h");
await waitText(".clock", "08:55");
ok("+1 h -> 08:55 and scenarios cleared", (await page.$$(".sim-table tbody tr")).length === 0);
await setGrams(90); await clickButton("Simulate meal"); await page.waitForSelector(".sim-table tbody tr");
r = await rows();
ok("90 g right after the logged breakfast flagged", r[0].includes("outside training support"), r[0]);
await page.screenshot({ path: `${OUT}/${P}-3-0855.png`, fullPage: true });

// 4. second scenario to the end
await page.goto(BASE + "?patient=SYN-0019&start=253.667", { waitUntil: "networkidle0" });
await page.waitForSelector(".clock");
const c0 = await text(".clock");
for (let i = 0; i < 6; i++) { await clickButton("+1 h"); await new Promise((s) => setTimeout(s, 400)); }
const c1 = await text(".clock");
if (LIVE) ok("SYN-0019 live replay advanced 6 h (13:45 -> 19:45)", c0.includes("13:45") && c1.includes("19:45"), `${c0} -> ${c1}`);
else { const playDisabled = await page.$$eval("xpath/.//button[contains(., 'Play')]", (bs) => bs[0].disabled);
ok("SYN-0019 replays 6 h to the recorded end (Play disabled)", playDisabled && c1.includes("19:45"), `${c0} -> ${c1}`); }
await page.screenshot({ path: `${OUT}/${P}-4-syn0019-end.png`, fullPage: true });

// 5. evaluation view
const [ev] = await page.$$(`xpath/.//button[contains(., "Model evaluation")]`);
if (ev) { await ev.click(); await new Promise((s) => setTimeout(s, 800));
  const evText = await page.$eval("body", (b) => b.innerText);
  ok("evaluation view renders committed metrics", /10\.4/.test(evText) && /0\.884|0\.88/.test(evText));
  await page.screenshot({ path: `${OUT}/${P}-5-evaluation.png`, fullPage: true }); }
else ok("evaluation view reachable", false, "no Evaluation button found");

ok("no console errors / failed requests", problems.length === 0, problems.join(" | "));
console.log(results.join("\n"));
await browser.close();
process.exit(results.some((x) => x.startsWith("FAIL")) ? 1 : 0);
