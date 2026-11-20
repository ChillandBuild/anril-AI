import { describe, expect, it } from "vitest";
import { MORE_ITEMS, MORE_SECTIONS, getVisibleMoreItems, isItemActive } from "./MoreMenu";

const ALL_FEATURES = ["outbound_messaging", "inbound_messaging", "sms", "telecalling.scheduled", "telecalling.notes"];

function owner() {
  return getVisibleMoreItems("owner", ALL_FEATURES, []);
}
function member(permissions: string[], features = ALL_FEATURES) {
  return getVisibleMoreItems("agent", features, permissions);
}
/** Rows whose pages include this address (any page, not just the one they open). */
function rowsFor(href: string) {
  return MORE_ITEMS.filter((item) => item.pages.some((page) => page.href === href));
}

describe("More drawer layout", () => {
  it("lists sections in the Phase 2 order, with the new names", () => {
    expect(MORE_SECTIONS.map((s) => s.title)).toEqual([
      null, "WhatsApp", "Anril Setup", "Engage", null, "Anril OTP", "Anril SMS", "Commerce", "Call IQ", null, "Account",
    ]);
  });

  it("lists rows per section in the Phase 2 order, with the new names", () => {
    const rows = owner();
    const byTitle = MORE_SECTIONS.map((s) => [s.title, rows.filter((r) => r.section === s.key).map((r) => r.label)]);
    expect(byTitle).toEqual([
      [null, ["Customers"]],
      ["WhatsApp", ["Templates", "Numbers"]],
      ["Anril Setup", ["Anril Brain", "Knowledge Base", "Replies & handover"]],
      ["Engage", ["Inbound Leads", "Meta Ads", "Auto-Messages"]],
      [null, ["Reach"]],
      ["Anril OTP", ["Send & check", "History", "Setup"]],
      ["Anril SMS", ["Dashboard", "DLT Setup", "Send SMS", "Address Book", "Delivery Reports", "Transactions", "Dev API"]],
      ["Commerce", ["Orders & payments", "Catalogue"]],
      ["Call IQ", ["Scheduled Calls", "Call Review", "Team Performance"]],
      [null, ["Reports"]],
      ["Account", ["Users & Roles"]],
    ]);
  });
});

describe("pages that moved or merged are each reachable from exactly one row", () => {
  it.each([
    ["/dashboard/settings/auto-reply", "Replies & handover"],
    ["/dashboard/settings/inbox", "Replies & handover"],
    ["/dashboard/settings/follow-ups", "Auto-Messages"],
    ["/dashboard/scheduled-templates", "Auto-Messages"],
    ["/dashboard/otp/settings", "Setup"],
    ["/dashboard/otp/api", "Setup"],
  ])("%s -> %s", (href, label) => {
    expect(rowsFor(href).map((r) => r.label)).toEqual([label]);
  });

  it("no row is left for the removed Scheduled templates / API & docs entries", () => {
    const labels = MORE_ITEMS.map((r) => r.label);
    expect(labels).not.toContain("Scheduled templates");
    expect(labels).not.toContain("API & docs");
    expect(labels).not.toContain("Numbers Pool");
  });

  it("each moved row is active on every page it stands for", () => {
    const active = (label: string, path: string) => isItemActive(MORE_ITEMS.find((r) => r.label === label)!, path);
    for (const p of ["/dashboard/auto-messages", "/dashboard/settings/follow-ups", "/dashboard/scheduled-templates"]) {
      expect(active("Auto-Messages", p)).toBe(true);
    }
    expect(active("Replies & handover", "/dashboard/settings/auto-reply")).toBe(true);
    expect(active("Replies & handover", "/dashboard/settings/inbox")).toBe(true);
    expect(active("Setup", "/dashboard/otp/settings")).toBe(true);
    expect(active("Setup", "/dashboard/otp/api")).toBe(true);
    expect(active("Auto-Messages", "/dashboard/settings/inbox")).toBe(false);
    expect(active("Send & check", "/dashboard/otp/history")).toBe(false);
  });
});

describe("combined rows keep every page's gate", () => {
  it("Auto-Messages opens scheduled-templates for a user who only has that gate", () => {
    const row = member(["outbound_leads.view"]).find((r) => r.label === "Auto-Messages");
    expect(row?.href).toBe("/dashboard/scheduled-templates");
  });

  it("Auto-Messages opens follow-ups for a user with only the settings gate", () => {
    const row = member(["settings.view"]).find((r) => r.label === "Auto-Messages");
    expect(row?.href).toBe("/dashboard/settings/follow-ups");
  });

  it("Auto-Messages opens auto-messages first when allowed, and hides with none of the gates", () => {
    const all = member(["auto_messages.view", "settings.view", "leads.manage"]).find((r) => r.label === "Auto-Messages");
    expect(all?.href).toBe("/dashboard/auto-messages");
    expect(member(["analytics.view"]).some((r) => r.label === "Auto-Messages")).toBe(false);
  });

  it("scheduled-templates still needs a messaging feature", () => {
    const row = member(["outbound_leads.view"], ["sms"]).find((r) => r.label === "Auto-Messages");
    expect(row).toBeUndefined();
  });

  it("Replies & handover needs the settings gate and opens auto-reply", () => {
    expect(member(["settings.manage"]).find((r) => r.label === "Replies & handover")?.href).toBe("/dashboard/settings/auto-reply");
    expect(member(["leads.view"]).some((r) => r.label === "Replies & handover")).toBe(false);
    expect(owner().find((r) => r.label === "Replies & handover")?.href).toBe("/dashboard/settings/auto-reply");
  });

  it("OTP Setup opens settings and shows for the OTP gate", () => {
    expect(member(["sms.view"]).find((r) => r.label === "Setup")?.href).toBe("/dashboard/otp/settings");
    expect(member(["leads.view"]).some((r) => r.label === "Setup")).toBe(false);
  });

  it("Catalogue still shows for a services-only user", () => {
    expect(member(["services.view"]).some((r) => r.label === "Catalogue")).toBe(true);
  });
});
