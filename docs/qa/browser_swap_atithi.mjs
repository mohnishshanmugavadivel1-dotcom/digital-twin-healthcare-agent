// Browser checks for the automated meal-swap finder and the Atithi (patient) companion summary on the STATIC snapshot.
//   BASE_URL=http://127.0.0.1:8080/<sub-path>/ CHROME_PATH=/path/to/chromium node browser_swap_atithi.mjs
// Exits 1 if any check fails.
import puppeteer from "puppeteer-core";
const BASE = process.env.BASE_URL;
const OUT = process.env.OUT ?? "/tmp";
const b = await puppeteer.launch({ executablePath: process.env.CHROME_PATH, headless: true, args: (process.env.CHROME_ARGS ?? "--no-sandbox").split(" ") });
const errs = []; const res = [];
const ok = (name, cond, info = "") => { res.push(cond); console.log(`${cond ? "PASS" : "FAIL"} ${name}${info ? " — " + info : ""}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const LABEL = "Deterministic Twin Scenario Search (ranked by Personalised Twin Curve inside training support; educational simulation, not a clinical prescription).";
async function page(w, h, mobile) {
  const p = await b.newPage(); await p.setViewport({ width: w, height: h, isMobile: mobile, hasTouch: mobile, deviceScaleFactor: mobile ? 2 : 1 });
  p.on("console", (m) => { if (m.type() === "error") errs.push(m.text()); }); p.on("requestfailed", (r) => errs.push("failed " + r.url()));
  return p;
}
const clickText = (p, sel, text) => p.evaluate((sel, text) => { const el = [...document.querySelectorAll(sel)].find((e) => e.textContent.trim().startsWith(text)); if (!el) return false; el.click(); return true; }, sel, text);
async function simulatePreset(p, id) {
  await p.evaluate((id) => { const s = document.querySelector('select[aria-label^="Indian meal preset"]');
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(s, id); s.dispatchEvent(new Event("change", { bubbles: true })); }, id);
  await clickText(p, "button", "Simulate meal") || await clickText(p, "button", "Add scenario");
  await sleep(900);
}

for (const [label, w, h, mobile] of [["desktop", 1366, 900, false], ["phone", 390, 844, true]]) {
  const p = await page(w, h, mobile);
  await p.goto(BASE + "?patient=SYN-0039", { waitUntil: "networkidle0" }); await sleep(900);
  const at0 = await p.evaluate(() => document.querySelector(".atithi")?.innerText ?? "");
  ok(`${label}: Atithi card verified before any scenario, doctor section has no numbers`,
    /Verified: 100% of numbers/i.test(at0) && /your care team can use the twin's What-If comparison/i.test(at0), at0.split("\n").slice(0, 2).join(" | "));
  await simulatePreset(p, "rajma-chawal");
  await p.waitForSelector(".swap-table", { timeout: 15000 }).catch(() => {});
  const sw = await p.evaluate(() => { const c = document.querySelector(".swap-finder"); if (!c) return null;
    return { txt: c.innerText, rows: [...c.querySelectorAll(".swap-table tbody tr")].map((r) => [...r.querySelectorAll("td")].map((td) => td.textContent.trim())) }; });
  ok(`${label}: swap finder ran automatically for the 68 g meal with the required label`,
    !!sw && sw.txt.includes(LABEL) && /Search ran automatically: large meal \(68 g/.test(sw.txt), sw ? sw.txt.slice(0, 90) : "");
  // 07:55 snapshot, sensitivity 1.698: 32 g -> +54.8, 35 g -> +60.0 (twin curve, linear in grams)
  ok(`${label}: top 3 = Khaman dhokla 32 g (+54.8), Idli 35 g (+60.0), Rava upma 35 g (+60.0); low watch not triggered`,
    !!sw && sw.rows.length === 3 && /^Khaman dhokla/.test(sw.rows[0][1]) && sw.rows[0][3] === "+54.8" && /^Idli/.test(sw.rows[1][1]) && /^Rava upma/.test(sw.rows[2][1])
      && sw.rows.every((r) => r[5] === "not triggered"), sw ? JSON.stringify(sw.rows.map((r) => [r[1].slice(0, 14), r[2], r[3], r[4]])) : "");
  ok(`${label}: explains that the order equals carb grams and GI is context only; no insulin/medication advice`,
    !!sw && /same as ranking by grams/i.test(sw.txt) && /GI badges are context only/i.test(sw.txt) && /not about insulin or medicines/i.test(sw.txt));
  const at = await p.evaluate(() => document.querySelector(".atithi")?.innerText ?? "");
  ok(`${label}: Atithi card verified with the scenario, walk comparison and top swap`,
    /Verified: 100% of numbers/i.test(at) && /Rajma chawal \(about 68 g of carbohydrate\)/.test(at) && /about 2500 steps/.test(at) && /Khaman dhokla \(about 32 g\)/.test(at)
      && /does not change any medicine or treatment/i.test(at), (at.match(/Verified[^\n]*/) ?? [""])[0]);
  await clickText(p, ".swap-table button", "Load");
  await sleep(300);
  ok(`${label}: "Load" puts the option into the What-If input`, (await p.$eval('input[aria-label="Hypothetical meal carbs in grams"]', (e) => e.value)) === "32");
  ok(`${label}: page does not overflow horizontally`, await p.evaluate((w) => document.documentElement.scrollWidth <= w, w));
  await p.evaluate(() => document.querySelector(".swap-finder").scrollIntoView()); await sleep(200);
  await p.screenshot({ path: `${OUT}/swap-${label}.png` });
}
ok("no console errors or failed requests", errs.length === 0, errs.slice(0, 3).join(" | "));
await b.close();
process.exit(res.every(Boolean) ? 0 : 1);
