import { describe, expect, it } from "vitest";
import {
  ANALYTICS_LINK,
  NAV_SECTIONS,
  TELECALLING_ITEMS,
  dashboardEntry,
  resolveSectionOpen,
  sectionContainsPage,
  sidebarFoldsOn,
  visibleEntries,
  type NavAccess,
  type NavEntry,
  type NavLeaf,
} from "./navSections";

const allAccess: NavAccess = {
  isSubscribed: true,
  messagingOn: true,
  inboundOn: true,
  outboundOn: true,
  smsOn: true,
  canServices: true,
  canSettings: true,
  brainGate: true,
  telecallingVisible: true,
  can: () => true,
  canAny: () => true,
};

const noAccess: NavAccess = {
  ...allAccess,
  isSubscribed: false,
  messagingOn: false,
  inboundOn: false,
  outboundOn: false,
  smsOn: false,
  canServices: false,
  canSettings: false,
  brainGate: false,
  telecallingVisible: false,
  can: () => false,
  canAny: () => false,
};

// Every tab the sidebar showed before, as label -> href. Products and Services
// are merged into Catalogue, so only /dashboard/catalog appears here.
const OLD_TABS: Array<{ label: string; href: string }> = [
  { label: "Analytics", href: "/dashboard/analytics" },
  { label: "Conversations", href: "/dashboard/conversations" },
  { label: "Segments", href: "/dashboard/leads" },
  { label: "Inbound Leads", href: "/dashboard/inbound-leads" },
  { label: "Meta Ads", href: "/dashboard/meta-ads" },
  { label: "Auto-Messages", href: "/dashboard/auto-messages" },
  { label: "Scheduled templates", href: "/dashboard/scheduled-templates" },
  { label: "Outbound Leads", href: "/dashboard/outbound-leads" },
  { label: "SMS", href: "/dashboard/sms" },
  { label: "Deals", href: "/dashboard/deals" },
  { label: "Catalogue", href: "/dashboard/catalog" },
  { label: "Team Performance", href: "/dashboard/team" },
  { label: "Anril Brain", href: "/dashboard/brain" },
  { label: "Knowledge Base", href: "/dashboard/knowledge" },
  { label: "Templates", href: "/dashboard/templates" },
  { label: "Numbers Pool", href: "/dashboard/numbers" },
  { label: "Users & Roles", href: "/dashboard/roles" },
  { label: "Subscription", href: "/dashboard/subscription" },
];

const TELECALLING_HREFS = [
  "/dashboard/telecalling/upload",
  "/dashboard/telecalling",
  "/dashboard/telecalling/scheduled",
  "/dashboard/notes",
];

function allEntries(): NavEntry[] {
  return [ANALYTICS_LINK, ...NAV_SECTIONS.flatMap((section) => section.entries)];
}

function allLeaves(): NavLeaf[] {
  return allEntries().filter((e): e is NavLeaf => e.kind === "link");
}

describe("navSections tab coverage", () => {
  it.each(OLD_TABS)("$label ($href) appears in exactly one place", ({ href, label }) => {
    const matches = allLeaves().filter((leaf) => leaf.href === href);
    expect(matches, label).toHaveLength(1);
  });

  it("holds all leaf tabs plus the Telecalling and Settings groups", () => {
    expect(allLeaves()).toHaveLength(OLD_TABS.length);
    expect(allEntries().filter((e) => e.kind === "group")).toHaveLength(2);
  });

  it("the Telecalling group covers the four telecalling pages", () => {
    expect(TELECALLING_ITEMS.map((item) => item.href)).toEqual(TELECALLING_HREFS);
    const tcGroup = allEntries().find((e) => e.kind === "group" && e.key === "telecalling");
    expect(tcGroup).toBeDefined();
  });

  it("does not expose the old Products or Services tabs as separate entries", () => {
    const hrefs = allLeaves().map((leaf) => leaf.href);
    expect(hrefs).not.toContain("/dashboard/services");
  });

  it("the Dashboard slot falls back to Overview without dashboard.view", () => {
    expect(dashboardEntry(allAccess)).toEqual({ href: "/dashboard", label: "Dashboard" });
    expect(dashboardEntry(noAccess)).toEqual({ href: "/dashboard/profile", label: "Overview" });
  });

  it("Developer is not part of any section (it is the pinned footer)", () => {
    expect(allLeaves().map((leaf) => leaf.href)).not.toContain("/dashboard/developer");
  });
});

describe("navSections defaults and gating", () => {
  it("only the INBOX & LEADS section is open by default", () => {
    const open = NAV_SECTIONS.filter((s) => s.defaultOpen).map((s) => s.key);
    expect(open).toEqual(["inbox"]);
  });

  it("a section with no visible items is empty, so the sidebar hides its heading", () => {
    const inbox = NAV_SECTIONS.find((s) => s.key === "inbox");
    expect(inbox).toBeDefined();
    expect(visibleEntries(inbox!, noAccess)).toHaveLength(0);
  });

  it("every section that is shown has at least one visible item with all access", () => {
    for (const section of NAV_SECTIONS) {
      expect(visibleEntries(section, allAccess).length, section.key).toBeGreaterThan(0);
    }
  });
});

describe("section open state", () => {
  it("uses the explicit user choice when one is set", () => {
    expect(resolveSectionOpen(false, true, true)).toBe(false);
    expect(resolveSectionOpen(true, false, false)).toBe(true);
  });

  it("falls back to the default when the user has not chosen", () => {
    expect(resolveSectionOpen(undefined, true, false)).toBe(true);
    expect(resolveSectionOpen(undefined, false, false)).toBe(false);
  });

  it("auto-opens a section that holds the current page when not chosen", () => {
    const aiSetup = NAV_SECTIONS.find((s) => s.key === "aiSetup")!;
    expect(sectionContainsPage(aiSetup, "/dashboard/brain/rules")).toBe(true);
    expect(resolveSectionOpen(undefined, aiSetup.defaultOpen, true)).toBe(true);
  });

  it("the Catalogue entry is active on both catalog and services pages", () => {
    const catalogue = allLeaves().find((leaf) => leaf.key === "catalogue")!;
    expect(catalogue.isActive("/dashboard/catalog")).toBe(true);
    expect(catalogue.isActive("/dashboard/services")).toBe(true);
    expect(catalogue.isActive("/dashboard/deals")).toBe(false);
  });
});

describe("SMS sidebar access", () => {
  const reach = NAV_SECTIONS.find((section) => section.key === "reach")!;
  const smsLinks = (access: NavAccess) => visibleEntries(reach, access).filter((entry) => entry.key === "sms");

  it.each(["sms.view", "sms.manage"])("shows SMS with %s when SMS is enabled, independently of WhatsApp features", (permission) => {
    const access: NavAccess = {
      ...noAccess,
      isSubscribed: true,
      smsOn: true,
      can: (value) => value === permission,
      canAny: (values) => values.includes(permission),
    };
    expect(smsLinks(access)).toHaveLength(1);
  });

  it("hides SMS when the tenant feature is off", () => {
    expect(smsLinks({ ...allAccess, smsOn: false })).toHaveLength(0);
  });

  it("hides SMS without SMS permission", () => {
    expect(smsLinks({ ...allAccess, can: () => false, canAny: () => false })).toHaveLength(0);
  });

  it("hides SMS without an active subscription", () => {
    expect(smsLinks({ ...allAccess, isSubscribed: false })).toHaveLength(0);
  });

  it("opens ANRIL REACH and marks SMS active on its page", () => {
    expect(sectionContainsPage(reach, "/dashboard/sms")).toBe(true);
    const sms = smsLinks(allAccess)[0] as NavLeaf;
    expect(sms.href).toBe("/dashboard/sms");
    expect(sms.isActive("/dashboard/sms")).toBe(true);
    expect(sms.isActive("/dashboard/sms-other")).toBe(false);
    expect(resolveSectionOpen(undefined, reach.defaultOpen, true)).toBe(true);
  });
});

describe("sidebarFoldsOn", () => {
  it.each([
    "/dashboard/conversations",
    "/dashboard/conversations/abc",
    "/dashboard/leads",
    "/dashboard/inbound-leads",
    "/dashboard/outbound-leads",
    "/dashboard/deals",
    "/dashboard/telecalling",
    "/dashboard/telecalling/scheduled",
  ])("folds the sidebar on the wide page %s", (path) => {
    expect(sidebarFoldsOn(path)).toBe(true);
  });

  it.each(["/dashboard", "/dashboard/analytics", "/dashboard/brain", "/dashboard/settings/account", "/dashboard/developer"])(
    "keeps the sidebar open on %s",
    (path) => {
      expect(sidebarFoldsOn(path)).toBe(false);
    },
  );
});
