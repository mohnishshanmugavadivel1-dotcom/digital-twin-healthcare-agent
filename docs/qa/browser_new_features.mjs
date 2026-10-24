// Browser checks for the 2026-10-23 features on the STATIC snapshot: phone swipe cue and no page overflow, FHIR panel,
// presets on the 15-min grid vs an off-grid moment, the low-glucose lower-bound note (SYN-0019 at +3 h), and the static banner,
// personalisation confidence line, What-If low-watch column and FHIR RiskAssessment.
//   BASE_URL=http://127.0.0.1:8080/<sub-path>/ CHROME_PATH=/path/to/chromium node browser_new_features.mjs
// Exits 1 if any check fails.
import puppeteer from "puppeteer-core";
const BASE = process.env.BASE_URL;
const OUT = process.env.OUT ?? "/tmp";
const b = await puppeteer.launch({ executablePath: process.env.CHROME_PATH, headless: true, args: (process.env.CHROME_ARGS ?? "--no-sandbox").split(" ") });
const errs = []; const res = [];
const ok = (name, cond, info = "") => { res.push(cond); console.log(`${cond ? "PASS" : "FAIL"} ${name}${info ? " — " + info : ""}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function page(w, h, mobile) {
  const p = await b.newPage(); await p.setViewport({ width: w, height: h, isMobile: mobile, hasTouch: mobile, deviceScaleFactor: mobile ? 2 : 1 });
  p.on("console", (m) => { if (m.type() === "error") errs.push(m.text()); }); p.on("requestfailed", (r) => errs.push("failed " + r.url()));
  return p;
}
const clickText = (p, sel, text) => p.evaluate((sel, text) => { const el = [...document.querySelectorAll(sel)].find((e) => e.textContent.trim().startsWith(text)); if (!el) return false; el.click(); return true; }, sel, text);
async function simulatePreset(p, presetStart) {
  await p.evaluate((t) => { const s = document.querySelector('select[aria-label^="Indian meal preset"]'); const o = [...s.options].find((x) => x.textContent.startsWith(t));
    const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set; set.call(s, o.value); s.dispatchEvent(new Event("change", { bubbles: true })); }, presetStart);
  await clickText(p, "button", "Simulate meal") || await clickText(p, "button", "Add scenario");
  await sleep(700);
}
// --- phone, SYN-0039 ---
const m = await page(390, 844, true);
await m.goto(BASE + "?patient=SYN-0039", { waitUntil: "networkidle0" }); await sleep(800);
await simulatePreset(m, "Idli");
const cue = await m.evaluate(() => { const c = document.querySelector(".swipe-cue"); return c && c.offsetParent !== null ? c.textContent : null; });
ok("phone: swipe cue visible above the What-If table", !!cue, cue ?? "");
const wrap = await m.evaluate(() => { const w = document.querySelector(".sim-wrap"); return { sw: w.scrollWidth, cw: w.clientWidth, page: document.documentElement.scrollWidth }; });
ok("phone: table scrolls inside its wrapper, page does not widen", wrap.sw > wrap.cw && wrap.page <= 390, JSON.stringify(wrap));
await m.screenshot({ path: `${OUT}/phone-whatif.png` });
await m.evaluate(() => document.querySelector("details.fhir summary").click()); await sleep(800);
const fhir = await m.evaluate(() => { const d = document.querySelector("details.fhir"); return { open: d.open, rows: d.querySelectorAll("tbody tr").length, txt: d.innerText }; });
ok("FHIR panel opens with resource counts and code table", fhir.open && fhir.rows >= 5 && /Patient/.test(fhir.txt) && /99504-3/.test(fhir.txt) && /44054006/.test(fhir.txt), `${fhir.rows} code rows`);
ok("FHIR panel labelled prototype / not compliance / static recorded at start", /not a compliance claim/.test(fhir.txt) && /recorded once at the replay start/.test(fhir.txt));
const dl = await m.evaluate(() => { const a = document.querySelector("details.fhir a[download]"); return a ? [a.getAttribute("download"), a.href.slice(0, 5)] : null; });
ok("FHIR download link is a blob JSON", !!dl && dl[1] === "blob:" && dl[0].endsWith(".fhir.json"), JSON.stringify(dl));
ok("phone: page still fits 390 px with FHIR panel open", await m.evaluate(() => document.documentElement.scrollWidth <= 390));
await m.evaluate(() => document.querySelector("details.fhir").scrollIntoView()); await m.screenshot({ path: `${OUT}/phone-fhir.png` });
// 15-min grid preset (08:10 = 3 x +5 min; not one of the all-amount moments)
await clickText(m, "button", "Clear scenarios"); await sleep(300);
for (let i = 0; i < 3; i++) { await clickText(m, "button", "+5 min"); await sleep(500); }
const clock = await m.evaluate(() => document.body.innerText.match(/\d\d:\d\d local/)?.[0]);
await simulatePreset(m, "Plain dosa");
const row = await m.evaluate(() => ({ rows: document.querySelectorAll(".sim-wrap .sim-table tbody tr").length, err: document.querySelector(".sim-error")?.textContent ?? null, t: document.querySelector(".sim-wrap .sim-table tbody tr")?.innerText.replace(/\s+/g, " ") }));
ok("preset recorded on the 15-min grid (08:10) is served, not an error", clock === "08:10 local" && row.rows === 1 && !row.err && /^25 g/.test(row.t), `${clock}: ${row.t}`);
await clickText(m, "button", "+5 min"); await sleep(500);
await simulatePreset(m, "Plain dosa");
const off = await m.evaluate(() => ({ clock: document.body.innerText.match(/\d\d:\d\d local/)?.[0], err: document.querySelector(".sim-error")?.textContent ?? "", rows: document.querySelectorAll(".sim-wrap .sim-table tbody tr").length }));
ok("off-grid moment (08:15) -> explicit 'not recorded' message, no invented row", off.clock === "08:15 local" && /This moment has none/.test(off.err) && off.rows === 0, `${off.clock}: ${off.err.slice(0, 160)}`);
// --- desktop, SYN-0019 at +3 h: low-glucose watch ---
const d = await page(1440, 1000, false);
await d.goto(BASE + "?patient=SYN-0019", { waitUntil: "networkidle0" }); await sleep(800);
ok("SYN-0019 at start: no low-glucose watch", await d.evaluate(() => !document.querySelector(".lowbound")));
for (let i = 0; i < 3; i++) { await clickText(d, "button", "+1 h"); await sleep(700); }
const lb = await d.evaluate(() => ({ clock: document.body.innerText.match(/\d\d:\d\d local/)?.[0], t: document.querySelector(".lowbound")?.innerText ?? null, hz: [...document.querySelectorAll(".hz .tiny")].map((e) => e.textContent) }));
ok("SYN-0019 +3 h: low-glucose watch shown with exact label and record medications",
   !!lb.t && /forecast lower bound falls below 70 mg\/dL/.test(lb.t) && /not a probability of hypoglycaemia/.test(lb.t) && /Glimepiride \(sulfonylurea\)/.test(lb.t) && /Insulin glargine \(basal insulin\)/.test(lb.t),
   `${lb.clock} intervals ${lb.hz.join(" ")} | ${lb.t?.replace(/\s+/g, " ").slice(0, 260)}`);
await (await d.$(".lowbound")).screenshot({ path: `${OUT}/lowbound.png` });
// --- sprint 2026-10-23 (b): banner, personalisation confidence, What-If low-watch column, FHIR RiskAssessment ---
const ban = await d.evaluate(() => ({ h: document.querySelector(".static-headline")?.innerText ?? "", p: document.querySelector(".static-provenance")?.innerText ?? "" }));
ok("banner: headline plus provenance (precomputed, not live, model + commit)",
   /Interactive Static Demo Snapshot \(GitHub Pages\)/.test(ban.h) && /not a live system/.test(ban.p) && /model gt-/.test(ban.p) && /commit [0-9a-f]{7}/.test(ban.p) && /not ABDM-certified/.test(ban.p),
   ban.p.replace(/\s+/g, " ").slice(0, 200));
const conf = await d.evaluate(() => document.querySelector(".personal-confidence")?.textContent ?? null);
ok("state panel: personalisation confidence line (sampling error, not a probability)", !!conf && /^Confidence: \d+% from \d+ observed meals; ± [\d.]+ sampling error \(meal-to-meal SD [\d.]+\)\.$/.test(conf) && !/probab|posterior/i.test(conf), conf ?? "");
await simulatePreset(d, "Idli");
const lw = await d.evaluate(() => ({ th: document.querySelector(".sim-wrap th.sim-low")?.innerText.replace(/\s+/g, " ") ?? "", td: document.querySelector(".sim-wrap td.sim-low")?.textContent ?? null, title: document.querySelector(".sim-wrap td.sim-low")?.title ?? "" }));
ok("What-If table: Low watch column per scenario (interval edge, not a probability)", /Low watch/i.test(lw.th) && lw.td !== null && /^(–|<70 from \+\d+m( · SU\/insulin)?)$/.test(lw.td) && /(Not a probability|Not a guarantee)/.test(lw.title), `${lw.th} | ${lw.td} | ${lw.title.slice(0, 120)}`);
await d.evaluate(() => document.querySelector("details.fhir summary").click()); await sleep(800);
const ra = await d.evaluate(() => [...document.querySelectorAll(".fhir-risk li")].map((li) => li.textContent));
ok("FHIR panel: RiskAssessment shows probabilityDecimal for the excursion only", ra.length >= 1 && /Hyperglycaemic excursion.*probabilityDecimal 0\.\d{3}/.test(ra[0]) && ra.slice(1).every((t) => /no probability/.test(t)), ra.join(" | ").slice(0, 200));
ok("no console errors / failed requests", errs.length === 0, errs.join(" | "));
console.log(`${res.filter(Boolean).length}/${res.length} passed`);
await b.close();
process.exit(res.every(Boolean) ? 0 : 1);
