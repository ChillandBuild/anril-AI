import { describe, expect, it } from "vitest";
import { HEADER_TABS, activeHeaderTab, phoneHeaderTabs } from "./headerTabs";

describe("phoneHeaderTabs", () => {
  it("gives phones the Customers tabs", () => {
    const set = phoneHeaderTabs("/dashboard/leads");
    expect(set?.tabs).toHaveLength(5);
    expect(set?.tabs[0].value).toBe("people");
  });

  it("gives phones the Reach, Roles, Knowledge and Purchases tabs", () => {
    for (const path of ["/dashboard/outbound-leads", "/dashboard/roles", "/dashboard/knowledge", "/dashboard/purchases"]) {
      expect(phoneHeaderTabs(path)?.tabs.length).toBeGreaterThan(1);
    }
  });

  it("skips pages that already have their own phone switch", () => {
    expect(phoneHeaderTabs("/dashboard/deals")).toBeNull();
    expect(phoneHeaderTabs("/dashboard/numbers")).toBeNull();
    expect(phoneHeaderTabs("/dashboard/analytics")).toBeNull();
  });

  it("returns null for pages without tabs", () => {
    expect(phoneHeaderTabs("/dashboard/more")).toBeNull();
    expect(phoneHeaderTabs("")).toBeNull();
  });
});

describe("activeHeaderTab", () => {
  it("follows old ?tab= names", () => {
    expect(activeHeaderTab(HEADER_TABS["/dashboard/leads"], "reengagement").value).toBe("follow-ups");
  });

  it("falls back to the first tab", () => {
    expect(activeHeaderTab(HEADER_TABS["/dashboard/roles"], "nope").value).toBe("roles");
  });
});
