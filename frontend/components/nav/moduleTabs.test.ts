import { describe, expect, it } from "vitest";
import { buildNavAccess, type NavAccessInput } from "./useNavAccess";
import { NAV_SECTIONS, moduleForPage, moduleTabsFor, withModuleTitle } from "./navSections";

const access = (input: Partial<NavAccessInput>) =>
  buildNavAccess({ role: "caller", permissions: [], enabledFeatures: [], subStatus: "active", ...input }).access;

const owner = access({
  role: "owner",
  enabledFeatures: ["whatsapp", "inbound_messaging", "outbound_messaging", "sms", "telecalling_telecmi"],
});

const labels = (pathname: string, a = owner, tab = "") => moduleTabsFor(pathname, a, tab)?.tabs.map((t) => t.label);

describe("moduleTabsFor: which tabs show", () => {
  it("shows one tab per entry of the module, in order, for an owner with everything on", () => {
    expect(labels("/dashboard/templates")).toEqual(["Templates", "Numbers", "QR & links"]);
    expect(labels("/dashboard/brain")).toEqual([
      "Anril Brain", "Couldn't answer", "AI report card", "Questions & scoring", "Knowledge Base", "Teach & offers", "Replies & handover",
    ]);
    expect(labels("/dashboard/bookings")).toEqual(["Inbound Leads", "Bookings", "Meta Ads", "Google Ads", "Auto-Messages"]);
    expect(labels("/dashboard/otp/history")).toEqual(["Overview", "Send & check", "History", "Setup"]);
    expect(labels("/dashboard/sms/send")).toEqual([
      "Dashboard", "DLT Setup", "Send SMS", "Address Book", "Delivery Reports", "Transactions", "Dev API",
    ]);
    expect(labels("/dashboard/deals")).toEqual(["Orders & payments", "Catalogue", "Purchases", "Expenses"]);
    expect(labels("/dashboard/call-iq/live")).toEqual([
      "Calling", "Leads to call", "Call reviews", "Team", "Live", "Evaluation", "Results",
    ]);
  });

  it("every tab opens its own first page; a tab for several pages opens the first one the user may open", () => {
    const tabs = moduleTabsFor("/dashboard/bookings", owner)!.tabs;
    expect(tabs.map((t) => t.href)).toEqual([
      "/dashboard/inbound-leads", "/dashboard/bookings", "/dashboard/meta-ads", "/dashboard/google-ads", "/dashboard/auto-messages",
    ]);
    // Only the settings gate: Auto-Messages opens Follow-ups.
    const settingsOnly = access({ permissions: ["settings.view", "bookings.view"], enabledFeatures: ["outbound_messaging"] });
    const t = moduleTabsFor("/dashboard/bookings", settingsOnly, "")!.tabs;
    expect(t.map((x) => [x.label, x.href])).toEqual([
      ["Bookings", "/dashboard/bookings"],
      ["Auto-Messages", "/dashboard/settings/follow-ups"],
    ]);
  });

  it("hides the tabs the user may not open", () => {
    const a = access({ permissions: ["bookings.view", "meta_ads.view"], enabledFeatures: ["inbound_messaging"] });
    // No inbound_leads.view and no Auto-Messages gate: those two tabs are gone.
    expect(labels("/dashboard/bookings", a)).toEqual(["Bookings", "Meta Ads", "Google Ads"]);
    // Templates and Numbers/QR are separate gates: templates.view alone leaves one tab, so no bar.
    const templatesOnly = access({ permissions: ["templates.view"], enabledFeatures: ["outbound_messaging"] });
    expect(moduleTabsFor("/dashboard/templates", templatesOnly)).toBeNull();
    const withNumbers = access({ permissions: ["templates.view", "numbers.view"], enabledFeatures: ["outbound_messaging"] });
    expect(labels("/dashboard/templates", withNumbers)).toEqual(["Templates", "Numbers", "QR & links"]);
  });

  it("Call IQ tabs follow the Team and Telecalling gates", () => {
    const teamOnly = access({ permissions: ["team.view"], enabledFeatures: [] });
    expect(labels("/dashboard/team", teamOnly)).toEqual(["Leads to call", "Team", "Live", "Evaluation", "Results"]);
    const dialerOnly = access({ permissions: ["telecalling.dialer"], enabledFeatures: ["telecalling_telecmi"] });
    // Calling alone is one tab: no bar.
    expect(moduleTabsFor("/dashboard/telecalling", dialerOnly)).toBeNull();
  });

  it("hides the bar with fewer than two tabs, and shows nothing without an active subscription", () => {
    const one = access({ permissions: ["bookings.view"], enabledFeatures: [] });
    expect(moduleTabsFor("/dashboard/bookings", one)).toBeNull();
    const expired = access({ role: "owner", enabledFeatures: ["inbound_messaging", "outbound_messaging"], subStatus: "expired" });
    expect(moduleTabsFor("/dashboard/templates", expired)).toBeNull();
  });

  it("Anril SMS and Anril OTP follow their own gates (OTP does not need the SMS feature)", () => {
    const otpOnly = access({ permissions: ["settings.view"], enabledFeatures: [] });
    expect(labels("/dashboard/otp", otpOnly)).toEqual(["Overview", "Send & check", "History", "Setup"]);
    expect(moduleTabsFor("/dashboard/sms", otpOnly)).toBeNull();
  });

  it("pages outside a module (Home, Chats, Customers, Reach, Reports, Settings) have no bar", () => {
    for (const path of [
      "/dashboard", "/dashboard/conversations", "/dashboard/leads", "/dashboard/outbound-leads",
      "/dashboard/analytics", "/dashboard/settings", "/dashboard/roles", "/dashboard/subscription",
    ]) {
      expect(moduleTabsFor(path, owner), path).toBeNull();
    }
  });
});

describe("moduleTabsFor: which tab is active", () => {
  const active = (pathname: string, tab = "", a = owner) =>
    moduleTabsFor(pathname, a, tab)?.tabs.filter((t) => t.active).map((t) => t.label);

  it("is exactly one tab on every page of a module, sub-pages included", () => {
    expect(active("/dashboard/templates")).toEqual(["Templates"]);
    expect(active("/dashboard/templates/new")).toEqual(["Templates"]);
    expect(active("/dashboard/meta-ads/all-ads")).toEqual(["Meta Ads"]);
    expect(active("/dashboard/sms/send")).toEqual(["Send SMS"]);
    expect(active("/dashboard/sms")).toEqual(["Dashboard"]);
    expect(active("/dashboard/otp")).toEqual(["Send & check"]);
    expect(active("/dashboard/otp/api")).toEqual(["Setup"]);
    expect(active("/dashboard/deals/orders/42")).toEqual(["Orders & payments"]);
    expect(active("/dashboard/services")).toEqual(["Catalogue"]);
    expect(active("/dashboard/brain")).toEqual(["Anril Brain"]);
    expect(active("/dashboard/brain/scoring")).toEqual(["Questions & scoring"]);
  });

  it("a tab that stands for several pages is active on each of them", () => {
    expect(active("/dashboard/auto-messages")).toEqual(["Auto-Messages"]);
    expect(active("/dashboard/auto-messages/sent")).toEqual(["Auto-Messages"]);
    expect(active("/dashboard/scheduled-templates")).toEqual(["Auto-Messages"]);
    expect(active("/dashboard/settings/follow-ups")).toEqual(["Auto-Messages"]);
    expect(active("/dashboard/settings/auto-reply")).toEqual(["Replies & handover"]);
    expect(active("/dashboard/settings/inbox")).toEqual(["Replies & handover"]);
  });

  it("splits pages that are one path by ?tab= (Upload and Team)", () => {
    expect(active("/dashboard/telecalling/upload", "")).toEqual(["Leads to call"]);
    expect(active("/dashboard/telecalling/upload", "history")).toEqual(["Leads to call"]);
    expect(active("/dashboard/telecalling/upload", "scripts")).toEqual(["Calling"]);
    expect(active("/dashboard/team", "")).toEqual(["Team"]);
    expect(active("/dashboard/team", "performance")).toEqual(["Team"]);
    expect(active("/dashboard/team", "log")).toEqual(["Leads to call"]);
  });

  it("Calling and Leads to call do not both light on the Telecalling sub-pages", () => {
    expect(active("/dashboard/telecalling")).toEqual(["Calling"]);
    expect(active("/dashboard/telecalling/dial")).toEqual(["Calling"]);
    expect(active("/dashboard/telecalling/scheduled")).toEqual(["Leads to call"]);
    expect(active("/dashboard/notes")).toEqual(["Call reviews"]);
  });

  it("a user who may not open the page they are on still sees the bar, with no tab lit", () => {
    const a = access({ permissions: ["bookings.view", "meta_ads.view"], enabledFeatures: ["inbound_messaging"] });
    const bar = moduleTabsFor("/dashboard/inbound-leads", a)!;
    expect(bar.section.key).toBe("engage");
    expect(bar.tabs.some((t) => t.active)).toBe(false);
  });

  it("reports the module's section so the bar can name itself", () => {
    expect(moduleTabsFor("/dashboard/otp", owner)?.section.title).toBe("Anril OTP");
    expect(moduleForPage("/dashboard/analytics")).toBeNull();
    expect(NAV_SECTIONS.map((s) => s.title)).toEqual(["WhatsApp", "Anril Setup", "Engage", "Anril OTP", "Anril SMS", "Commerce", "Call IQ"]);
  });
});

describe("withModuleTitle", () => {
  it("puts the module in front of the page's own title", () => {
    expect(withModuleTitle("Templates", "/dashboard/templates")).toBe("WhatsApp / Templates");
    expect(withModuleTitle("Orders & payments", "/dashboard/deals")).toBe("Commerce / Orders & payments");
    expect(withModuleTitle("Calling / Scripts", "/dashboard/telecalling/upload", "scripts")).toBe("Call IQ / Calling / Scripts");
    expect(withModuleTitle("Team", "/dashboard/team")).toBe("Call IQ / Team");
  });

  it("leaves a title that already starts with the module name, and pages outside a module", () => {
    expect(withModuleTitle("Anril SMS / Send SMS", "/dashboard/sms/send")).toBe("Anril SMS / Send SMS");
    expect(withModuleTitle("Anril OTP", "/dashboard/otp")).toBe("Anril OTP");
    expect(withModuleTitle("Reports", "/dashboard/analytics")).toBe("Reports");
    expect(withModuleTitle("Home", "/dashboard")).toBe("Home");
  });
});
