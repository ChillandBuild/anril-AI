import { describe, expect, it } from "vitest";
import { isSettingsPath } from "@/components/settingsNavigation";
import {
  ANALYTICS_LINK,
  CHIP_SETS,
  NAV_LINKS,
  NAV_MENU,
  NAV_SECTIONS,
  TELECALLING_ITEMS,
  chipSetFor,
  dashboardEntry,
  leafHref,
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
  { label: "Customers", href: "/dashboard/leads" },
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
  { label: "Send & check", href: "/dashboard/otp" },
  { label: "History", href: "/dashboard/otp/history" },
  { label: "Settings", href: "/dashboard/otp/settings" },
  { label: "API & docs", href: "/dashboard/otp/api" },
  { label: "Orders & payments", href: "/dashboard/deals" },
  { label: "Catalogue", href: "/dashboard/catalog" },
  { label: "Team Performance", href: "/dashboard/team" },
  { label: "Anril Brain", href: "/dashboard/brain" },
  { label: "Knowledge Base", href: "/dashboard/knowledge" },
  { label: "Templates", href: "/dashboard/templates" },
  { label: "Numbers Pool", href: "/dashboard/numbers" },
  { label: "Users & Roles", href: "/dashboard/roles" },
  { label: "Subscription", href: "/dashboard/subscription" },
  // Settings > Anril group, before Phase 2.
  { label: "Auto-Reply", href: "/dashboard/settings/auto-reply" },
  { label: "Follow-Ups", href: "/dashboard/settings/follow-ups" },
  { label: "Inbox & Handover", href: "/dashboard/settings/inbox" },
];

const TELECALLING_HREFS = [
  "/dashboard/telecalling/upload",
  "/dashboard/telecalling",
  "/dashboard/telecalling/scheduled",
  "/dashboard/notes",
];

function allEntries(): NavEntry[] {
  return [...NAV_LINKS, ...NAV_SECTIONS.flatMap((section) => section.entries)];
}

function allLeaves(): NavLeaf[] {
  return allEntries().filter((e): e is NavLeaf => e.kind === "link");
}

/** Menu rows that open this address: the row's own address or one of its pages. */
const rowsReaching = (href: string) =>
  allLeaves().filter((leaf) => leaf.href === href || leaf.pages?.some((page) => page.href === href));

const chipsReaching = (href: string) => CHIP_SETS.flatMap((set) => set.chips).filter((chip) => chip.href === href);

describe("navSections tab coverage", () => {
  it.each(OLD_TABS)("$label ($href) is reachable from exactly one row", ({ href, label }) => {
    const reachedByRow = rowsReaching(href).length;
    // The three Settings > Anril pages have no row of their own any more: they are pages of another row.
    expect(reachedByRow, label).toBe(1);
  });

  it.each(CHIP_SETS.flatMap((set) => set.chips.map((chip) => ({ set: set.key, href: chip.href, label: chip.label }))))(
    "chip $label ($href) is in exactly one chip set, on the row of that set",
    ({ href, set }) => {
      expect(chipsReaching(href)).toHaveLength(1);
      const rows = rowsReaching(href);
      expect(rows).toHaveLength(1);
      expect(rows[0].key).toBe(CHIP_SETS.find((s) => s.key === set)!.leafKey);
    },
  );

  it("holds all leaf tabs plus the Telecalling and Settings groups", () => {
    // Phase 2: Scheduled templates and API & docs lost their rows, Replies & handover gained one.
    expect(allLeaves()).toHaveLength(OLD_TABS.length - 3 /* settings pages */ - 2 + 1);
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
    expect(dashboardEntry(allAccess)).toEqual({ href: "/dashboard", label: "Home" });
    expect(dashboardEntry(noAccess)).toEqual({ href: "/dashboard/profile", label: "Overview" });
  });

  it("Developer is not part of any section (it is the pinned footer)", () => {
    expect(allLeaves().map((leaf) => leaf.href)).not.toContain("/dashboard/developer");
  });
});

describe("navSections defaults and gating", () => {
  it("a section with no visible items is empty, so the sidebar hides its heading", () => {
    const engage = NAV_SECTIONS.find((s) => s.key === "engage");
    expect(engage).toBeDefined();
    expect(visibleEntries(engage!, noAccess)).toHaveLength(0);
  });

  it("plain menu links keep their permission gates", () => {
    for (const leaf of NAV_LINKS) {
      expect(leaf.visible(noAccess), leaf.key).toBe(false);
      expect(leaf.visible(allAccess), leaf.key).toBe(true);
    }
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

  it("shuts every section on pages outside them (Home and the plain links)", () => {
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

  it("is its own main-menu section with the 7 pages in Bulk9's order", () => {
    expect(smsSection.title).toBe("Anril SMS");
    expect(smsLinks(allAccess).map((leaf) => leaf.label)).toEqual([
      "Dashboard", "DLT Setup", "Send SMS", "Address Book", "Delivery Reports", "Transactions", "Dev API",
    ]);
    expect(NAV_LINKS.some((leaf) => leaf.key.startsWith("sms"))).toBe(false);
  });

  it.each(["sms.view", "sms.manage"])("shows the pages with %s when SMS is enabled, independently of WhatsApp features", (permission) => {
    const access: NavAccess = {
      ...noAccess,
      isSubscribed: true,
      smsOn: true,
      can: (value) => value === permission,
      canAny: (values) => values.includes(permission),
    };
    expect(smsLinks(access)).toHaveLength(7);
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
    expect(sectionContainsPage(smsSection, "/dashboard/sms/otp")).toBe(false);
    expect(sectionContainsPage(smsSection, "/dashboard/sms-other")).toBe(false);
    expect(resolveOpenSection(undefined, NAV_SECTIONS, "/dashboard/sms")).toBe("sms");
    expect(resolveOpenSection(undefined, NAV_SECTIONS, "/dashboard/sms/send")).toBe("sms");
  });
});

describe("Anril OTP section", () => {
  const otpSection = NAV_SECTIONS.find((section) => section.key === "otp")!;
  const otpLinks = (access: NavAccess) => visibleEntries(otpSection, access) as NavLeaf[];

  it("is its own main-menu section with the 3 rows, just before Anril SMS", () => {
    expect(otpSection.title).toBe("Anril OTP");
    expect(otpLinks(allAccess).map((leaf) => leaf.label)).toEqual(["Send & check", "History", "Setup"]);
    expect(otpLinks(allAccess).map((leaf) => leaf.href)).toEqual([
      "/dashboard/otp",
      "/dashboard/otp/history",
      "/dashboard/otp/settings",
    ]);
    const keys = NAV_SECTIONS.map((section) => section.key);
    expect(keys.indexOf("sms")).toBe(keys.indexOf("otp") + 1);
  });

  it.each(["sms.view", "sms.manage", "settings.view", "settings.manage"])("shows with %s when SMS is off", (permission) => {
    const access: NavAccess = {
      ...noAccess,
      isSubscribed: true,
      smsOn: false,
      can: (value) => value === permission,
      canAny: (values) => values.includes(permission),
    };
    expect(otpLinks(access)).toHaveLength(3);
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

// A user who can open exactly the pages that `permissions` / flags allow.
const only = (permissions: string[], extra: Partial<NavAccess> = {}): NavAccess => ({
  ...noAccess,
  isSubscribed: true,
  messagingOn: true,
  can: (value) => permissions.includes(value),
  canAny: (values) => values.some((value) => permissions.includes(value)),
  ...extra,
});

const leafByKey = (key: string) => allLeaves().find((leaf) => leaf.key === key)!;

describe("Phase 2: Auto-Messages row stands for 3 pages", () => {
  const row = leafByKey("auto-messages");

  it("is visible and opens One-time sends for a user who only has the scheduled-templates gate", () => {
    const access = only(["telecalling.dialer"]);
    expect(row.visible(access)).toBe(true);
    expect(leafHref(row, access)).toBe("/dashboard/scheduled-templates");
  });

  it("opens Follow-ups for a user who only has settings.view", () => {
    const access = only(["settings.view"], { canSettings: true, messagingOn: false });
    expect(row.visible(access)).toBe(true);
    expect(leafHref(row, access)).toBe("/dashboard/settings/follow-ups");
  });

  it("opens When something happens first when the user can reach it", () => {
    const access = only(["auto_messages.view", "settings.view"], { canSettings: true, outboundOn: true });
    expect(leafHref(row, access)).toBe("/dashboard/auto-messages");
  });

  it("is hidden for a user with none of the three gates, and without a subscription", () => {
    expect(row.visible(noAccess)).toBe(false);
    expect(row.visible(only([]))).toBe(false);
    expect(row.visible({ ...allAccess, isSubscribed: false })).toBe(false);
  });

  it("sits in Engage and the old Scheduled templates row is gone", () => {
    const engage = NAV_SECTIONS.find((s) => s.key === "engage")!;
    expect(engage.entries.map((e) => (e as NavLeaf).label)).toEqual(["Inbound Leads", "Meta Ads", "Auto-Messages"]);
  });
});

describe("Phase 2: Replies & handover and OTP Setup gates", () => {
  it("Replies & handover keeps the old Settings gate (subscribed and settings.view/manage)", () => {
    const row = leafByKey("replies-handover");
    expect(row.visible(allAccess)).toBe(true);
    expect(row.visible({ ...allAccess, canSettings: false })).toBe(false);
    expect(row.visible({ ...allAccess, isSubscribed: false })).toBe(false);
    expect(leafHref(row, allAccess)).toBe("/dashboard/settings/auto-reply");
  });

  it("OTP Setup follows otpVisible and opens Rules", () => {
    const row = leafByKey("otp-settings");
    expect(row.label).toBe("Setup");
    expect(row.visible(only(["sms.view"]))).toBe(true);
    expect(row.visible(only([]))).toBe(false);
    expect(leafHref(row, allAccess)).toBe("/dashboard/otp/settings");
  });

  it("Numbers is the new name of Numbers Pool", () => {
    expect(leafByKey("numbers-pool").label).toBe("Numbers");
  });
});

describe("Phase 2: the 7 moved or renamed addresses", () => {
  const CASES: Array<{ path: string; row: string; section: string; chipSet: string }> = [
    { path: "/dashboard/auto-messages", row: "auto-messages", section: "engage", chipSet: "autoMessages" },
    { path: "/dashboard/settings/follow-ups", row: "auto-messages", section: "engage", chipSet: "autoMessages" },
    { path: "/dashboard/scheduled-templates", row: "auto-messages", section: "engage", chipSet: "autoMessages" },
    { path: "/dashboard/settings/auto-reply", row: "replies-handover", section: "aiSetup", chipSet: "replies" },
    { path: "/dashboard/settings/inbox", row: "replies-handover", section: "aiSetup", chipSet: "replies" },
    { path: "/dashboard/otp/settings", row: "otp-settings", section: "otp", chipSet: "otpSetup" },
    { path: "/dashboard/otp/api", row: "otp-settings", section: "otp", chipSet: "otpSetup" },
  ];

  const EXPECTED_CHIPS: Record<string, Array<[string, string]>> = {
    autoMessages: [
      ["When something happens", "/dashboard/auto-messages"],
      ["Follow-ups", "/dashboard/settings/follow-ups"],
      ["One-time sends", "/dashboard/scheduled-templates"],
    ],
    replies: [
      ["Auto-reply", "/dashboard/settings/auto-reply"],
      ["Handover", "/dashboard/settings/inbox"],
    ],
    otpSetup: [
      ["Rules", "/dashboard/otp/settings"],
      ["Connect your website", "/dashboard/otp/api"],
    ],
  };

  it.each(CASES)("$path lights only the $row row and opens $section", ({ path, row, section }) => {
    const active = allLeaves().filter((leaf) => leaf.isActive(path)).map((leaf) => leaf.key);
    expect(active).toEqual([row]);
    expect(resolveOpenSection(undefined, NAV_SECTIONS, path)).toBe(section);
    expect(NAV_SECTIONS.filter((s) => sectionContainsPage(s, path)).map((s) => s.key)).toEqual([section]);
  });

  it.each(CASES)("$path gets the $chipSet chips, in order", ({ path, chipSet }) => {
    const set = chipSetFor(path);
    expect(set?.key).toBe(chipSet);
    expect(set!.chips.map((chip) => [chip.label, chip.href])).toEqual(EXPECTED_CHIPS[chipSet]);
  });

  it.each(CASES)("$path is no longer a Settings page, and the Settings group is not active on it", ({ path }) => {
    expect(isSettingsPath(path)).toBe(false);
    const settingsGroup = allEntries().find((e) => e.kind === "group" && e.key === "settings")!;
    expect(settingsGroup.isActive(path)).toBe(false);
  });

  it("chipSetFor is null on pages with no siblings", () => {
    for (const path of [
      "/dashboard", "/dashboard/otp", "/dashboard/otp/history", "/dashboard/settings/account",
      "/dashboard/settings/notifications", "/dashboard/brain", "/dashboard/numbers", "/dashboard/auto",
    ]) {
      expect(chipSetFor(path), path).toBeNull();
    }
  });

  it("a chip is hidden for a user who cannot open that page", () => {
    const access = only(["telecalling.dialer"]);
    const visible = chipSetFor("/dashboard/scheduled-templates")!.chips.filter((chip) => chip.visible(access));
    expect(visible.map((chip) => chip.label)).toEqual(["One-time sends"]);
  });

  it("Settings pages that stayed still count as Settings pages", () => {
    expect(isSettingsPath("/dashboard/settings/account")).toBe(true);
  });
});

describe("v9.2 main menu (Phase 1)", () => {
  const row = (item: (typeof NAV_MENU)[number]) => (item.kind === "link" ? item.leaf.label : item.section.title);

  it("follows the redesign order and names", () => {
    expect(NAV_MENU.map(row)).toEqual([
      "Chats", "Customers", "WhatsApp", "Anril Setup", "Engage", "Reach",
      "Anril OTP", "Anril SMS", "Commerce", "Call IQ", "Reports", "Account",
    ]);
  });

  it("one-page modules are plain links that keep their addresses", () => {
    expect(NAV_LINKS.map((leaf) => [leaf.label, leaf.href])).toEqual([
      ["Chats", "/dashboard/conversations"],
      ["Customers", "/dashboard/leads"],
      ["Reach", "/dashboard/outbound-leads"],
      ["Reports", "/dashboard/analytics"],
    ]);
    expect(ANALYTICS_LINK.label).toBe("Reports");
  });

  it("Reach opens the outbound page on its sub-routes too", () => {
    const reach = NAV_LINKS.find((leaf) => leaf.label === "Reach")!;
    expect(reach.isActive("/dashboard/outbound-leads")).toBe(true);
    expect(resolveOpenSection(undefined, NAV_SECTIONS, "/dashboard/outbound-leads")).toBeNull();
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
