import { describe, expect, it } from "vitest";
import {
  ANALYTICS_LINK,
  NAV_SECTIONS,
  TELECALLING_ITEMS,
  dashboardEntry,
  resolveOpenSection,
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
  { label: "SMS Dashboard", href: "/dashboard/sms" },
  { label: "DLT Setup", href: "/dashboard/sms/setup" },
  { label: "Send SMS", href: "/dashboard/sms/send" },
  { label: "Address Book", href: "/dashboard/sms/contacts" },
  { label: "Delivery Reports", href: "/dashboard/sms/reports" },
  { label: "Transactions", href: "/dashboard/sms/transactions" },
  { label: "Dev API", href: "/dashboard/sms/developer" },
  { label: "Smart OTP", href: "/dashboard/sms/otp" },
  { label: "Send & check", href: "/dashboard/otp" },
  { label: "History", href: "/dashboard/otp/history" },
  { label: "Settings", href: "/dashboard/otp/settings" },
  { label: "API & docs", href: "/dashboard/otp/api" },
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
  it("uses the click when one is set, including all shut", () => {
    expect(resolveOpenSection("reach", NAV_SECTIONS, "/dashboard/conversations")).toBe("reach");
    expect(resolveOpenSection(null, NAV_SECTIONS, "/dashboard/conversations")).toBeNull();
  });

  it("opens only the section holding the current page", () => {
    const aiSetup = NAV_SECTIONS.find((s) => s.key === "aiSetup")!;
    expect(sectionContainsPage(aiSetup, "/dashboard/brain/rules")).toBe(true);
    expect(resolveOpenSection(undefined, NAV_SECTIONS, "/dashboard/brain/rules")).toBe("aiSetup");
  });

  it("shuts every section on pages outside them (Dashboard, Analytics)", () => {
    expect(resolveOpenSection(undefined, NAV_SECTIONS, "/dashboard")).toBeNull();
    expect(resolveOpenSection(undefined, NAV_SECTIONS, "/dashboard/analytics")).toBeNull();
  });

  it("the Catalogue entry is active on both catalog and services pages", () => {
    const catalogue = allLeaves().find((leaf) => leaf.key === "catalogue")!;
    expect(catalogue.isActive("/dashboard/catalog")).toBe(true);
    expect(catalogue.isActive("/dashboard/services")).toBe(true);
    expect(catalogue.isActive("/dashboard/deals")).toBe(false);
  });
});

describe("Anril SMS section", () => {
  const smsSection = NAV_SECTIONS.find((section) => section.key === "sms")!;
  const smsLinks = (access: NavAccess) => visibleEntries(smsSection, access) as NavLeaf[];

  it("is its own main-menu section with the 8 pages in Bulk9's order", () => {
    expect(smsSection.title).toBe("Anril SMS");
    expect(smsLinks(allAccess).map((leaf) => leaf.label)).toEqual([
      "Dashboard", "DLT Setup", "Send SMS", "Address Book", "Delivery Reports", "Transactions", "Dev API", "Smart OTP",
    ]);
    const reach = NAV_SECTIONS.find((section) => section.key === "reach")!;
    expect(reach.entries.some((entry) => entry.key.startsWith("sms"))).toBe(false);
  });

  it.each(["sms.view", "sms.manage"])("shows the pages with %s when SMS is enabled, independently of WhatsApp features", (permission) => {
    const access: NavAccess = {
      ...noAccess,
      isSubscribed: true,
      smsOn: true,
      can: (value) => value === permission,
      canAny: (values) => values.includes(permission),
    };
    expect(smsLinks(access)).toHaveLength(8);
  });

  it("hides the section when the tenant feature is off", () => {
    expect(smsLinks({ ...allAccess, smsOn: false })).toHaveLength(0);
  });

  it("hides the section without SMS permission", () => {
    expect(smsLinks({ ...allAccess, can: () => false, canAny: () => false })).toHaveLength(0);
  });

  it("hides the section without an active subscription", () => {
    expect(smsLinks({ ...allAccess, isSubscribed: false })).toHaveLength(0);
  });

  it("opens Anril SMS on any SMS page and marks only that page active", () => {
    const [dashboard, setup] = smsLinks(allAccess);
    expect(dashboard.isActive("/dashboard/sms")).toBe(true);
    expect(dashboard.isActive("/dashboard/sms/setup")).toBe(false);
    expect(setup.isActive("/dashboard/sms/setup")).toBe(true);
    expect(setup.isActive("/dashboard/sms/setup-other")).toBe(false);
    expect(sectionContainsPage(smsSection, "/dashboard/sms/otp")).toBe(true);
    expect(sectionContainsPage(smsSection, "/dashboard/sms-other")).toBe(false);
    expect(resolveOpenSection(undefined, NAV_SECTIONS, "/dashboard/sms")).toBe("sms");
    expect(resolveOpenSection(undefined, NAV_SECTIONS, "/dashboard/sms/send")).toBe("sms");
  });
});

describe("Anril OTP section", () => {
  const otpSection = NAV_SECTIONS.find((section) => section.key === "otp")!;
  const otpLinks = (access: NavAccess) => visibleEntries(otpSection, access) as NavLeaf[];

  it("is its own main-menu section with the 4 pages, after Anril SMS", () => {
    expect(otpSection.title).toBe("Anril OTP");
    expect(otpLinks(allAccess).map((leaf) => leaf.label)).toEqual(["Send & check", "History", "Settings", "API & docs"]);
    expect(otpLinks(allAccess).map((leaf) => leaf.href)).toEqual([
      "/dashboard/otp",
      "/dashboard/otp/history",
      "/dashboard/otp/settings",
      "/dashboard/otp/api",
    ]);
    const keys = NAV_SECTIONS.map((section) => section.key);
    expect(keys.indexOf("otp")).toBe(keys.indexOf("sms") + 1);
  });

  it.each(["sms.view", "sms.manage", "settings.view", "settings.manage"])("shows with %s when SMS is off", (permission) => {
    const access: NavAccess = {
      ...noAccess,
      isSubscribed: true,
      smsOn: false,
      can: (value) => value === permission,
      canAny: (values) => values.includes(permission),
    };
    expect(otpLinks(access)).toHaveLength(4);
  });

  it("hides the section without an active subscription", () => {
    expect(otpLinks({ ...allAccess, isSubscribed: false })).toHaveLength(0);
  });

  it("hides the section without SMS or settings permission", () => {
    expect(otpLinks({ ...allAccess, canSettings: false, can: () => false, canAny: () => false })).toHaveLength(0);
  });

  it("marks the root page active only on its exact path", () => {
    const [sendCheck, history] = otpLinks(allAccess);
    expect(sendCheck.isActive("/dashboard/otp")).toBe(true);
    expect(sendCheck.isActive("/dashboard/otp/history")).toBe(false);
    expect(history.isActive("/dashboard/otp/history")).toBe(true);
    expect(history.isActive("/dashboard/otp/history-other")).toBe(false);
    expect(resolveOpenSection(undefined, NAV_SECTIONS, "/dashboard/otp/api")).toBe("otp");
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
