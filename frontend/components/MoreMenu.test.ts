import { describe, expect, it } from "vitest";
import { MORE_ITEMS, MORE_SECTIONS, getVisibleMoreItems, isItemActive } from "./MoreMenu";
import { groupSettingsItems, isSettingsPath, settingsItemsForMember } from "./settingsNavigation";

const ALL_FEATURES = ["outbound_messaging", "inbound_messaging", "sms", "telecalling.upload", "telecalling.scheduled", "telecalling.notes"];

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
      null, "WhatsApp", "Anril Setup", "Engage", null, "Anril OTP", "Anril SMS", "Commerce", "Call IQ", null, null,
    ]);
  });

  it("lists rows per section in the Phase 2 order, with the new names", () => {
    const rows = owner();
    const byTitle = MORE_SECTIONS.map((s) => [s.title, rows.filter((r) => r.section === s.key).map((r) => r.label)]);
    expect(byTitle).toEqual([
      [null, ["Customers"]],
      ["WhatsApp", ["Templates", "Numbers"]],
      ["Anril Setup", ["Anril Brain", "Knowledge Base", "Teach & offers", "Replies & handover"]],
      ["Engage", ["Inbound Leads", "Meta Ads", "Auto-Messages"]],
      [null, ["Reach"]],
      ["Anril OTP", ["Send & check", "History", "Setup"]],
      ["Anril SMS", ["Dashboard", "DLT Setup", "Send SMS", "Address Book", "Delivery Reports", "Transactions", "Dev API"]],
      ["Commerce", ["Orders & payments", "Catalogue", "Purchases", "Expenses"]],
      ["Call IQ", ["Leads to call", "Call reviews", "Team"]],
      [null, ["Reports"]],
      [null, []],
    ]);
  });

  it("the Users & Roles row moved into the Settings box as Team & roles", () => {
    expect(MORE_ITEMS.map((r) => r.label)).not.toContain("Users & Roles");
    expect(MORE_SECTIONS[MORE_SECTIONS.length - 1].key).toBe("settings");
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
    ["/dashboard/telecalling/upload", "Leads to call"],
    ["/dashboard/telecalling/upload?tab=history", "Leads to call"],
    ["/dashboard/telecalling/scheduled", "Leads to call"],
    ["/dashboard/team?tab=log", "Leads to call"],
    ["/dashboard/notes", "Call reviews"],
    ["/dashboard/team", "Team"],
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

describe("Call IQ in the drawer: Leads to call, Call reviews, Team", () => {
  const SCHEDULED = ["telecalling.scheduled"];
  const hrefOf = (label: string, permissions: string[], features = ALL_FEATURES) => member(permissions, features).find((r) => r.label === label)?.href;
  const row = (label: string) => MORE_ITEMS.find((r) => r.label === label)!;

  it("the old Scheduled Calls, Call Review and Team Performance rows are gone", () => {
    const labels = MORE_ITEMS.map((r) => r.label);
    for (const old of ["Scheduled Calls", "Call Review", "Team Performance"]) expect(labels).not.toContain(old);
  });

  it("Leads to call shows for any one of its gates and opens the first allowed page, in order", () => {
    expect(hrefOf("Leads to call", ["telecalling.upload"])).toBe("/dashboard/telecalling/upload");
    expect(hrefOf("Leads to call", ["telecalling.scheduled"])).toBe("/dashboard/telecalling/scheduled");
    expect(hrefOf("Leads to call", ["team.view"])).toBe("/dashboard/team?tab=log");
    expect(hrefOf("Leads to call", ["team.manage"])).toBe("/dashboard/team?tab=log");
    expect(hrefOf("Leads to call", ["telecalling.upload", "telecalling.scheduled", "team.view"])).toBe("/dashboard/telecalling/upload");
    expect(hrefOf("Leads to call", ["telecalling.scheduled", "team.view"])).toBe("/dashboard/telecalling/scheduled");
    expect(owner().find((r) => r.label === "Leads to call")?.href).toBe("/dashboard/telecalling/upload");
  });

  it("each page keeps its gate: the scheduled feature, the upload feature, a permission, or none of them hides the row", () => {
    expect(hrefOf("Leads to call", SCHEDULED, ["outbound_messaging"])).toBeUndefined();
    expect(hrefOf("Leads to call", ["telecalling.upload"], ["telecalling.scheduled"])).toBeUndefined();
    expect(hrefOf("Leads to call", ["analytics.view"])).toBeUndefined();
  });

  it("Call reviews and Team keep the gates Call Review and Team Performance had", () => {
    expect(hrefOf("Call reviews", ["telecalling.notes"])).toBe("/dashboard/notes");
    expect(hrefOf("Call reviews", ["telecalling.notes"], ["outbound_messaging"])).toBeUndefined();
    expect(hrefOf("Call reviews", ["team.view"])).toBeUndefined();
    expect(hrefOf("Team", ["team.view"])).toBe("/dashboard/team");
    expect(hrefOf("Team", ["team.manage"])).toBe("/dashboard/team");
    expect(hrefOf("Team", ["telecalling.notes"])).toBeUndefined();
  });

  it.each([
    ["Leads to call", "/dashboard/telecalling/upload", "", true],
    ["Leads to call", "/dashboard/telecalling/upload", "history", true],
    ["Leads to call", "/dashboard/telecalling/upload", "scripts", false],
    ["Leads to call", "/dashboard/telecalling/scheduled", "", true],
    ["Leads to call", "/dashboard/team", "log", true],
    ["Leads to call", "/dashboard/team", "", false],
    ["Team", "/dashboard/team", "", true],
    ["Team", "/dashboard/team", "performance", true],
    ["Team", "/dashboard/team", "log", false],
    ["Call reviews", "/dashboard/notes", "", true],
    ["Call reviews", "/dashboard/telecalling/scheduled", "", false],
  ])("%s active on %s ?tab=%s: %s", (label, path, tab, expected) => {
    expect(isItemActive(row(label), path, tab)).toBe(expected);
  });

  it("exactly one Call IQ row is active on each address", () => {
    const callIq = MORE_ITEMS.filter((r) => r.section === "callIq");
    for (const [path, tab, expected] of [
      ["/dashboard/telecalling/upload", "", "Leads to call"],
      ["/dashboard/telecalling/upload", "history", "Leads to call"],
      ["/dashboard/telecalling/scheduled", "", "Leads to call"],
      ["/dashboard/team", "log", "Leads to call"],
      ["/dashboard/team", "", "Team"],
      ["/dashboard/notes", "", "Call reviews"],
    ]) {
      expect(callIq.filter((r) => isItemActive(r, path, tab)).map((r) => r.label), `${path}?${tab}`).toEqual([expected]);
    }
  });
});

describe("Settings box in the drawer", () => {
  const box = (role: string | null, permissions: string[]) => {
    const items = settingsItemsForMember(role, permissions, [], false);
    return {
      groups: groupSettingsItems(items).groups.map((g) => [g.group, g.items.map((i) => i.label)]),
      loose: groupSettingsItems(items).loose.map((i) => i.label),
    };
  };

  it("has the 4 groups then Plans & subscription for an owner", () => {
    expect(box("owner", [])).toEqual({
      groups: [
        ["My business", ["Business details"]],
        ["Connections", ["Channels", "Calling"]],
        ["Team & roles", ["Team & roles"]],
        ["Alerts & automations", ["Alerts"]],
      ],
      loose: ["Plans & subscription"],
    });
  });

  it("hides a group with no visible row, and keeps each row's gate", () => {
    expect(box("agent", ["roles.view"])).toEqual({ groups: [["Team & roles", ["Team & roles"]]], loose: [] });
    expect(box("agent", ["subscription.view"])).toEqual({ groups: [], loose: ["Plans & subscription"] });
    expect(box("agent", ["settings.view"]).groups.map(([g]) => g)).toEqual(["My business", "Connections", "Alerts & automations"]);
    expect(box("agent", [])).toEqual({ groups: [], loose: [] });
  });

  it("the box highlight and the sidebar use the same Settings-page rule", () => {
    for (const path of ["/dashboard/settings", "/dashboard/roles", "/dashboard/subscription", "/dashboard/settings/account"]) {
      expect(isSettingsPath(path), path).toBe(true);
    }
    expect(isSettingsPath("/dashboard/settings/inbox")).toBe(false);
  });
});
