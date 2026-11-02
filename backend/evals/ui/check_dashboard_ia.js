// Dashboard layout check on the LIVE site, logged in as the "Aira UI Test (Claude)" test owner.
// Read-only: never clicks Save, Fix or Keep. Checks the 2026-09-26 regrouping:
//   node backend/evals/ui/check_dashboard_ia.js   -> screenshots in backend/evals/ui/screenshots/
// Credentials: backend/evals/ui/.test-account.json (gitignored).
const path = require("path");
const { chromium } = require(path.join(__dirname, "../../../frontend/node_modules/playwright"));
const fs = require("fs");
const SP = path.join(__dirname, "screenshots");
fs.mkdirSync(SP, { recursive: true });
const acct = JSON.parse(fs.readFileSync(path.join(__dirname, ".test-account.json"), "utf8"));
const BASE = "https://www.anrilaitech.com";

const REDIRECTS = [
  ["/dashboard/settings/packages", /\/dashboard\/services/],
  ["/dashboard/settings/intake-config", /\/dashboard\/services/],
  ["/dashboard/settings/general", /\/dashboard\/settings\/account/],
  ["/dashboard/settings/business", /\/dashboard\/settings\/account/],
  ["/dashboard/settings/telecalling", /\/dashboard\/settings\/connect-channels/],
  ["/dashboard/settings/business-hours", /\/dashboard\/knowledge/],
  ["/dashboard/settings/quick-replies", /\/dashboard\/services/],
];
const PAGES = [
  ["services", "/dashboard/services", ["Sell in chat", "Details to collect", "What you call it"]],
  ["account", "/dashboard/settings/account", ["Business details"]],
  ["knowledge", "/dashboard/knowledge?tab=description", ["What Aira says when it brings in your team"]],
];

(async () => {
  const b = await chromium.launch();
  let failures = 0;
  const fail = (msg) => { failures += 1; console.log(`FAIL ${msg}`); };
  for (const [label, viewport] of [["desktop", { width: 1440, height: 900 }], ["phone", { width: 375, height: 812 }]]) {
    const p = await b.newPage({ viewport });
    await p.goto(`${BASE}/login`, { waitUntil: "networkidle", timeout: 90000 });
    await p.fill('input[type="email"]', acct.email);
    await p.fill('input[placeholder="••••••••"]', acct.password);
    await p.click('button[type="submit"]');
    await p.waitForURL(/\/dashboard/, { timeout: 90000 });

    for (const [from, to] of REDIRECTS) {
      await p.goto(`${BASE}${from}`, { waitUntil: "domcontentloaded", timeout: 90000 });
      try { await p.waitForURL(to, { timeout: 30000 }); console.log(`${label}: ${from} -> ${p.url().replace(BASE, "")}`); }
      catch { fail(`${label}: ${from} stayed at ${p.url().replace(BASE, "")}`); }
    }

    for (const [name, route, texts] of PAGES) {
      await p.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded", timeout: 90000 });
      await p.locator(`:text("${texts[texts.length - 1]}"):visible`).first().waitFor({ timeout: 45000 }).catch(() => {});
      await p.waitForTimeout(1500);
      const body = await p.locator("body").innerText();
      for (const t of texts) if (!body.includes(t)) fail(`${label}: ${name} is missing "${t}"`);
      const overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (overflow > 0) fail(`${label}: ${name} overflows by ${overflow}px`);
      await p.screenshot({ path: `${SP}/ia_${name}_${label}.png`, fullPage: true });
      console.log(`${label}: ${name} ok-checked, overflow ${overflow}px, saved ia_${name}_${label}.png`);
    }

    if (label === "desktop") {
      // The main menu, not the Settings sub-menu that replaces it on settings pages.
      await p.goto(`${BASE}/dashboard`, { waitUntil: "domcontentloaded", timeout: 90000 });
      await p.locator(':text("Services"):visible').first().waitFor({ timeout: 45000 }).catch(() => {});
      const nav = await p.locator("body").innerText();
      // Services is gated like Products (messaging plan + permission): they appear together.
      const hasServices = /\bServices\b/.test(nav), hasProducts = /\bProducts\b/.test(nav);
      if (hasServices !== hasProducts) fail(`desktop: Services shown=${hasServices} but Products shown=${hasProducts}`);
      else console.log(`desktop: sidebar Services shown=${hasServices}, Products shown=${hasProducts} (same gate)`);
      await p.screenshot({ path: `${SP}/ia_sidebar_${label}.png` });
    }
    await p.close();
  }
  await b.close();
  console.log(failures ? `${failures} failure(s)` : "all checks passed");
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error("FAILED", e.message); process.exit(1); });
