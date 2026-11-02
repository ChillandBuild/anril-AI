// "What Aira sells" (Services page) check on the LIVE site (https://www.anrilaitech.com), logged in
// as the "Aira UI Test (Claude)" test owner. Read-only: it never clicks Save.
//   node backend/evals/ui/check_offerings_ui.js   -> screenshots in backend/evals/ui/screenshots/
// Also checks the old Intake Config URL redirects here. Credentials: backend/evals/ui/.test-account.json
// (gitignored). See .agents/context/subsystem-notes.md.
const path = require("path");
const { chromium } = require(path.join(__dirname, "../../../frontend/node_modules/playwright"));
const fs = require("fs");
const SP = path.join(__dirname, "screenshots");
fs.mkdirSync(SP, { recursive: true });
const acct = JSON.parse(fs.readFileSync(path.join(__dirname, ".test-account.json"), "utf8"));
const BASE = "https://www.anrilaitech.com";
(async () => {
  const b = await chromium.launch();
  for (const [label, viewport] of [["desktop", { width: 1440, height: 900 }], ["phone", { width: 390, height: 844 }]]) {
    const p = await b.newPage({ viewport });
    await p.goto(`${BASE}/login`, { waitUntil: "networkidle", timeout: 90000 });
    await p.fill('input[type="email"]', acct.email); await p.fill('input[placeholder="••••••••"]', acct.password);
    await p.click('button[type="submit"]'); await p.waitForURL(/\/dashboard/, { timeout: 90000 });

    // Since 7400cf7f the Services page is the home for offerings; the old URL lands there.
    await p.goto(`${BASE}/dashboard/settings/intake-config`, { waitUntil: "domcontentloaded", timeout: 90000 });
    await p.waitForURL(/dashboard\/services/, { timeout: 60000, waitUntil: "commit" });
    console.log(`${label}: old intake-config URL redirected to ${p.url()}`);

    await p.locator('[aria-label="Let Aira sell these in chat"]').first().waitFor({ timeout: 90000 });
    await p.waitForTimeout(2000);
    const body = await p.locator("body").innerText();
    for (const gone of ["Trigger description", "Offer message"]) {
      console.log(`${label}: "${gone}" present? ${body.includes(gone)}`);
    }
    const overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    console.log(`${label}: horizontal overflow px = ${overflow}`);
    await p.screenshot({ path: `${SP}/offerings_${label}.png`, fullPage: true });
    console.log(`saved offerings_${label}.png`);
    await p.close();
  }
  await b.close();
})().catch(e => { console.error("FAILED", e.message); process.exit(1); });
