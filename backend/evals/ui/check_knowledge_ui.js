// Knowledge page UI check on the LIVE site (https://www.anrilaitech.com), logged in as the
// "Aira UI Test (Claude)" test owner. Read-only: it never clicks Save / Apply / Use this line.
//   node backend/evals/ui/check_knowledge_ui.js   -> screenshots in backend/evals/ui/screenshots/
// Credentials: backend/evals/ui/.test-account.json (gitignored). See .agents/context/subsystem-notes.md.
const path = require("path");
const { chromium } = require(path.join(__dirname, "../../../frontend/node_modules/playwright"));
const fs = require("fs");
const SP = path.join(__dirname, "screenshots");
fs.mkdirSync(SP, { recursive: true });
const acct = JSON.parse(fs.readFileSync(path.join(__dirname, ".test-account.json"), "utf8"));
const BASE = "https://www.anrilaitech.com";
const go = (p, url) => p.goto(url, { waitUntil: "domcontentloaded", timeout: 90000 });
(async () => {
  const b = await chromium.launch();
  for (const [label, viewport] of [["desktop", { width: 1440, height: 900 }], ["phone", { width: 390, height: 844 }]]) {
    const p = await b.newPage({ viewport });
    await p.goto(`${BASE}/login`, { waitUntil: "networkidle", timeout: 90000 });
    await p.fill('input[type="email"]', acct.email); await p.fill('input[placeholder="••••••••"]', acct.password);
    await p.click('button[type="submit"]'); await p.waitForURL(/\/dashboard/, { timeout: 90000 });
    if (label === "phone") {
      await go(p, `${BASE}/dashboard/knowledge?tab=description`);
      await p.getByText("How customers buy").first().waitFor({ timeout: 90000 });
      await p.waitForTimeout(1500);
      await p.screenshot({ path: `${SP}/ui_phone_description.png`, fullPage: true }); console.log("saved phone_description");
    }
    await go(p, `${BASE}/dashboard/knowledge`);
    await p.locator(':text("Smile Care price list.txt"):visible').first().waitFor({ timeout: 90000 });
    await p.waitForTimeout(1500);
    if (label === "phone") { await p.screenshot({ path: `${SP}/ui_phone_documents.png`, fullPage: true }); console.log("saved phone_documents"); }
    await p.locator('button:visible', { hasText: /^\s*Review\s*$/ }).first().click();
    const card = p.getByText("Contact line found in this file").first();
    await card.waitFor({ timeout: 90000 });
    await card.scrollIntoViewIfNeeded(); await p.waitForTimeout(800);
    await p.screenshot({ path: `${SP}/ui_${label}_review_card.png` }); console.log(`saved ${label}_review_card`);
    await p.close();
  }
  await b.close();
})().catch(e => { console.error("FAILED", e.message); process.exit(1); });
