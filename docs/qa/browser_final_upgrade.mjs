// Browser checks for the final-upgrade features on the STATIC snapshot: region-grouped Indian presets with GI badges,
// the research twin-curve columns and walk toggle beside unchanged tree deltas, the AGP card, the fact-grounded
// handover note (patient view and FHIR panel), and no page overflow on a phone.
//   BASE_URL=http://127.0.0.1:8080/<sub-path>/ CHROME_PATH=/path/to/chromium node browser_final_upgrade.mjs
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

for (const [label, w, h, mobile] of [["desktop", 1366, 900, false], ["phone", 390, 844, true]]) {
  const p = await page(w, h, mobile);
  await p.goto(BASE + "?patient=SYN-0039", { waitUntil: "networkidle0" }); await sleep(900);
  const sel = await p.evaluate(() => { const s = document.querySelector('select[aria-label^="Indian meal preset"]');
    return { groups: [...s.querySelectorAll("optgroup")].map((g) => `${g.label}:${g.children.length}`), n: s.querySelectorAll("optgroup option").length,
             gi: [...s.querySelectorAll("optgroup option")].every((o) => / GI/.test(o.textContent)), team: [...s.options].filter((o) => /team est\./.test(o.textContent)).length }; });
  ok(`${label}: 24 presets in 5 region groups, every option with a GI band, 13 marked team estimate`,
    sel.n === 24 && sel.groups.join() === "South:10,North:5,West:5,East:2,Snacks & beverages:2" && sel.gi && sel.team === 13, JSON.stringify(sel));
  await simulatePreset(p, "Idli");
  const badge = await p.evaluate(() => { const g = document.querySelector(".gi-badge"); return g ? [g.textContent, g.title] : null; });
  ok(`${label}: GI badge shown for the chosen preset, with its source note`, !!badge && /GI/.test(badge[0]) && /indicative/i.test(badge[1]), JSON.stringify(badge));
  const row = await p.evaluate(() => { const r = document.querySelector(".sim-table tbody tr"); return [...r.querySelectorAll("td")].map((c) => c.textContent.trim()); });
  const head = await p.evaluate(() => document.querySelector(".sim-table thead").innerText);
  // 35 g at 07:55: research curve Δ+60/+120 = +42.5/+60.0 (primary, first after Meal), walk +48.8 (−11.2),
  // served tree Δ+30/+60/+120 = +7.9/+29.9/+10.7 (unchanged values, now secondary columns) (API, 2026-10-23)
  // Layout changed on 2026-10-24 at the team's request: twin curve first and bold, tree columns after it.
  ok(`${label}: twin curve is the primary block right after Meal; tree deltas unchanged, to the right`,
    row[1] === "+42.5" && row[2] === "+60.0" && /^\+48\.8/.test(row[3]) && row[4] === "+7.9" && row[5] === "+29.9" && row[6] === "+10.7"
      && /twin curve \(primary/i.test(head) && /tree model — attenuated/i.test(head) && head.search(/twin curve/i) < head.search(/tree model/i), JSON.stringify(row));
  const bold = await p.evaluate(() => [...document.querySelectorAll(".sim-table tbody tr:first-child td.sim-primary")].map((c) => getComputedStyle(c).fontWeight));
  ok(`${label}: the three primary twin-curve cells are bold`, bold.length === 3 && bold.every((w) => Number(w) >= 700), JSON.stringify(bold));
  const lead = await p.evaluate(() => document.querySelector(".whatif-lead")?.textContent ?? "");
  ok(`${label}: lead sentence above the table states the 5.9 vs 37.3 mg/dL basis`,
    lead.startsWith("Primary meal & walk deltas below use the patient's validated Personalised Twin Response Curve (5.9 mg/dL MAE at +120m on held-out simulator truth)") && /37\.3 mg\/dL MAE/.test(lead), lead.slice(0, 80));
  const walk = await p.evaluate(() => { const r = document.querySelector(".sim-table tbody tr"); return [...r.querySelectorAll("td.sim-twin")].map((c) => c.textContent.trim()); });
  ok(`${label}: walk column shown by default with the walk's own effect`, walk.length === 3 && /\+48\.8/.test(walk[2]) && /walk −?-?11\.2|walk -11\.2/.test(walk[2]), JSON.stringify(walk));
  await p.evaluate(() => document.querySelector(".walk-toggle input").click()); await sleep(300);
  const nowalk = await p.evaluate(() => document.querySelectorAll(".sim-table tbody tr:first-child td.sim-twin").length);
  ok(`${label}: walk toggle hides the walk column`, nowalk === 2, String(nowalk));
  const agp = await p.evaluate(() => { const c = document.querySelector(".agp-card"); return c ? { txt: c.innerText, polys: c.querySelectorAll("polygon").length, med: !!c.querySelector("polyline") } : null; });
  ok(`${label}: AGP card with percentile bands, TIR, GMI and the sufficiency caveat`, !!agp && agp.polys === 2 && agp.med && /time in range/i.test(agp.txt) && /GMI/.test(agp.txt) && /below its 14-day/i.test(agp.txt), agp ? agp.txt.slice(0, 120).replace(/\n/g, " | ") : "");
  const ho = await p.evaluate(() => { const c = document.querySelector("details.handover.card"); return c ? c.innerText : null; });
  ok(`${label}: handover note verified 100% and grounded in the 07:55 state`, !!ho && /Verified: 100% of numbers/i.test(ho) && /07:55 local time/i.test(ho) && /not a treatment instruction/i.test(ho), ho ? ho.split("\n").slice(0, 3).join(" | ") : "");
  await p.evaluate(() => document.querySelector("details.fhir summary").click()); await sleep(900);
  const fh = await p.evaluate(() => { const d = document.querySelector("details.fhir details.handover"); if (!d) return null; d.open = true; return d.innerText; });
  ok(`${label}: FHIR panel carries the same verified handover note`, !!fh && /Verified: 100%/i.test(fh), fh ? fh.slice(0, 80).replace(/\n/g, " | ") : "");
  ok(`${label}: page does not overflow horizontally`, await p.evaluate((w) => document.documentElement.scrollWidth <= w, w));
  await p.evaluate(() => document.querySelector(".whatif").scrollIntoView()); await sleep(200);
  await p.screenshot({ path: `${OUT}/final-${label}-whatif.png` });
  await p.evaluate(() => document.querySelector(".insight-row").scrollIntoView()); await sleep(200);
  await p.screenshot({ path: `${OUT}/final-${label}-agp-handover.png` });
}
ok("no console errors or failed requests", errs.length === 0, errs.slice(0, 3).join(" | "));
await b.close();
process.exit(res.every(Boolean) ? 0 : 1);
