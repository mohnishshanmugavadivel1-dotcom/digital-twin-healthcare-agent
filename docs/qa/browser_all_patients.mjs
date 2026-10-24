// Browser checks: every one of the 12 held-out test patients opens a real patient view in the STATIC snapshot.
// SYN-0039 and SYN-0019 have full replays; the other 10 have one recorded moment (record, state, forecast, AGP,
// FHIR, every What-If amount).
//   BASE_URL=http://127.0.0.1:8080/<sub-path>/ CHROME_PATH=/path/to/chromium node browser_all_patients.mjs
// Exits 1 if any check fails.
import puppeteer from "puppeteer-core";
const BASE = process.env.BASE_URL;
const b = await puppeteer.launch({ executablePath: process.env.CHROME_PATH, headless: true, args: (process.env.CHROME_ARGS ?? "--no-sandbox").split(" ") });
const errs = []; const res = [];
const ok = (name, cond, info = "") => { res.push(cond); console.log(`${cond ? "PASS" : "FAIL"} ${name}${info ? " — " + info : ""}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const p = await b.newPage(); await p.setViewport({ width: 1366, height: 900 });
p.on("console", (m) => { if (m.type() === "error") errs.push(m.text()); }); p.on("requestfailed", (r) => errs.push("failed " + r.url()));
await p.goto(BASE, { waitUntil: "networkidle0" }); await sleep(900);
const list = await p.evaluate(() => [...document.querySelectorAll(".sidebar .pt")].map((e) => ({ name: e.querySelector(".pt-name")?.textContent, disabled: e.disabled })));
ok("patient list shows 12 held-out patients, none disabled", list.length === 12 && list.every((x) => !x.disabled), `${list.length}`);
const first = await p.evaluate(() => document.querySelector(".patient-header .muted.small")?.textContent);
ok("default patient is still the SYN-0039 full replay", first === "SYN-0039", String(first));
for (let i = 0; i < list.length; i++) {
  await p.evaluate((i) => document.querySelectorAll(".sidebar .pt")[i].click(), i); await sleep(900);
  const v = await p.evaluate(() => ({
    id: document.querySelector(".patient-header .muted.small")?.textContent ?? "",
    err: document.querySelector(".card.error")?.textContent ?? "",
    chart: !!document.querySelector(".chart-card svg"),
    agp: /time in range/i.test(document.querySelector(".agp-card")?.textContent ?? ""),
    handover: /Verified: 100% of numbers/i.test(document.querySelector("details.handover.card")?.textContent ?? ""),
    moment: document.querySelector(".static-moment")?.textContent ?? "",
  }));
  const full = v.id === "SYN-0039" || v.id === "SYN-0019";
  ok(`${v.id}: patient view loads (chart, AGP, verified handover)${full ? " — full replay" : " — one recorded moment, labelled"}`,
    !v.err && v.chart && v.agp && v.handover && (full ? v.moment === "" : /one recorded moment/i.test(v.moment)), v.err.slice(0, 120));
  if (!full && i === list.length - 1) { // one What-If on a moment patient: the twin curve and tree columns both answer
    await p.evaluate(() => { const s = document.querySelector('select[aria-label^="Indian meal preset"]');
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(s, "idli2"); s.dispatchEvent(new Event("change", { bubbles: true })); });
    await p.evaluate(() => [...document.querySelectorAll("button")].find((x) => /Simulate meal|Add scenario/.test(x.textContent)).click()); await sleep(900);
    const row = await p.evaluate(() => [...(document.querySelector(".sim-table tbody tr")?.querySelectorAll("td") ?? [])].map((c) => c.textContent.trim()));
    ok(`${v.id}: a recorded What-If (35 g) answers with twin-curve and tree columns`, row.length >= 8 && /^[+−-]\d/.test(row[1]) && /^[+−-]\d/.test(row[4]), JSON.stringify(row.slice(0, 7)));
  }
}
ok("no console errors or failed requests", errs.length === 0, errs.slice(0, 3).join(" | "));
await b.close();
process.exit(res.every(Boolean) ? 0 : 1);
